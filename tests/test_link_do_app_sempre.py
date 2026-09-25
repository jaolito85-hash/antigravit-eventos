"""Resposta que fala do app sai com o link cadastrado, sem depender da IA.

Print de 25/09: "Perdi minha carteira onde eu vou?" voltou com "Confira a
rota completa no aplicativo oficial do festival" e nada para clicar. As
fichas dizem "baixe o aplicativo", as regras mandam "envie o link", e a IA
colava o link só às vezes. Agora o link entra por código.
"""

import json
import os
import unittest
from unittest import mock

import server

LINK = "https://apps.apple.com/br/app/tropicadelia/id6497061308"


def _ia_respondendo(texto):
    resposta = mock.MagicMock()
    resposta.choices = [mock.MagicMock()]
    resposta.choices[0].message.content = texto
    cliente = mock.MagicMock()
    cliente.chat.completions.create.return_value = resposta
    return cliente


class ComLinkDoAppTests(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(server, "link_do_app", return_value=LINK)
        p.start()
        self.addCleanup(p.stop)

    def test_mencao_ao_app_ganha_o_link_na_linha_de_baixo(self):
        r = server.com_link_do_app("Procure o Achados e Perdidos. Confira a rota no aplicativo oficial do festival. 📍")
        self.assertTrue(r.endswith(f"\n📲 {LINK}"))
        self.assertTrue(r.startswith("Procure o Achados e Perdidos."))

    def test_app_e_apk_tambem_contam(self):
        for texto in ("Baixa o app oficial que tem tudo!", "o apk tá na loja"):
            self.assertIn(LINK, server.com_link_do_app(texto), texto)

    def test_quem_ja_tem_o_link_nao_recebe_de_novo(self):
        texto = f"Tá tudo no app: {LINK} 📲"
        self.assertEqual(server.com_link_do_app(texto), texto)

    def test_baladapp_e_bilheteria_nao_e_o_app_do_festival(self):
        texto = "Ingresso só pelo BaladApp, o aplicativo BaladAPP é a bilheteria oficial."
        self.assertEqual(server.com_link_do_app(texto), texto)

    def test_sem_mencao_nada_muda(self):
        texto = "O SAC fica atrás da praça de alimentação."
        self.assertEqual(server.com_link_do_app(texto), texto)

    def test_sem_link_cadastrado_nada_muda(self):
        with mock.patch.object(server, "link_do_app", return_value=""):
            texto = "Baixe o aplicativo e veja a rota."
            self.assertEqual(server.com_link_do_app(texto), texto)


class ComposicaoComLinkTests(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(server, "link_do_app", return_value=LINK)
        p.start()
        self.addCleanup(p.stop)

    def test_duvida_respondida_pela_ia_sai_com_o_link(self):
        with mock.patch.object(server, "generate_ai_response", return_value="Procure o Achados e Perdidos. Confira a rota no aplicativo oficial. 📍"):
            r = server._compose_reply("perdi minha carteira", "Estrutura", "Neutro", None, False, known={"answer": "x"})
        self.assertIn(LINK, r)

    def test_perda_marcada_como_urgente_tambem_ganha_o_link(self):
        # A triagem oscila entre Neutro e Urgente para "perdi minha carteira";
        # o link não pode depender disso.
        with mock.patch.object(server, "generate_ai_response", return_value="😢 Poxa! Procure o Achados e Perdidos; o app oficial mostra a rota."):
            r = server._compose_reply("perdi minha carteira", "Estrutura", "Urgente", None, False, known=None)
        self.assertIn(LINK, r)

    def test_critico_e_protocolo_fixo_sem_link(self):
        with mock.patch.object(server, "link_do_app", return_value=LINK):
            r = server._compose_reply("tem uma briga aqui", "Segurança", "Critico", None, False, known=None)
        self.assertNotIn(LINK, r)

    def test_sem_ia_a_ficha_que_manda_baixar_o_app_sai_com_o_link(self):
        with mock.patch.object(server, "generate_ai_response", return_value=None):
            r = server._compose_reply(
                "perdi um objeto", "Estrutura", "Neutro", None, False,
                known={"answer": "Procure o Achados e Perdidos. Baixe o aplicativo e veja a rota até o local"},
            )
        self.assertTrue(r.endswith(f"\n📲 {LINK}"), r)

    def test_conversa_com_o_tuca_tambem_sai_com_o_link(self):
        cliente = _ia_respondendo("Tô nos bastidores! Tudo que rola tá no app oficial 🦜")
        with mock.patch.object(server, "_openai_chat_client", return_value=cliente), \
                mock.patch.object(server, "_bot_config", return_value={"settings": {}, "rules": []}), \
                mock.patch.object(server, "_rules_block", return_value=""), \
                mock.patch.object(server, "resposta_segura", return_value=True):
            r = server.compose_smalltalk("cadê você?", ja_falou=True)
        self.assertIn(LINK, r)


class CarinhaTristeTests(unittest.TestCase):
    def test_prompt_manda_abrir_com_empatia_para_quem_perdeu_algo(self):
        cliente = _ia_respondendo("😢 Poxa, que chato! Procure o Achados e Perdidos, na pista.")
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}), \
                mock.patch.object(server, "_openai_chat_client", return_value=cliente), \
                mock.patch.object(server, "_bot_config", return_value={"settings": {}, "rules": []}), \
                mock.patch.object(server, "_rules_block", return_value=""), \
                mock.patch.object(server, "resposta_segura", return_value=True):
            r = server.generate_ai_response("perdi minha carteira", "Estrutura", "Neutro", official_answer="Procure o Achados e Perdidos.")
        self.assertTrue(r.startswith("😢"))
        system = cliente.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        self.assertIn("lost something (wallet, phone, wristband, a friend)", system)
        self.assertIn("one caring emoji", system)


if __name__ == "__main__":
    unittest.main()
