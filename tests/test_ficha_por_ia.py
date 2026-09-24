"""A IA escolhe a ficha da base pelo sentido; gatilho é só reserva.

Contrato: a triagem recebe as fichas ativas e devolve a escolhida (ou None
quando a IA diz que nenhuma responde); a composição usa exatamente essa
ficha; e com a IA fora, o casamento por gatilho volta a valer.
"""

import json
import unittest
from unittest import mock

import server

FICHAS = [
    {"id": "f1", "question": "Onde fica o festival e como chego?", "answer": "No Parque Ney Braga.",
     "keywords": ["onde fica", "local"], "priority": 80, "active": True},
    {"id": "f2", "question": "Onde fica o SAC?", "answer": "Ao lado da praça de alimentação da pista.",
     "keywords": [], "priority": 70, "active": True},
    {"id": "f3", "question": "Guarda-volumes", "answer": "Não tem.", "keywords": ["locker"],
     "priority": 10, "active": False},
]


def _ia_respondendo(payload):
    """Cliente OpenAI falso que devolve o JSON dado."""

    resposta = mock.MagicMock()
    resposta.choices = [mock.MagicMock()]
    resposta.choices[0].message.content = json.dumps(payload)
    cliente = mock.MagicMock()
    cliente.chat.completions.create.return_value = resposta
    return cliente


class TriagemComFichasTests(unittest.TestCase):
    def test_ia_escolhe_a_ficha_pelo_numero(self):
        cliente = _ia_respondendo({"tipo": "relato", "urgencia": "Neutro", "ficha": 2})
        with mock.patch.object(server, "_openai_chat_client", return_value=cliente):
            r = server.triar_mensagem_ia("onde fica o sac?", FICHAS[:2])
        self.assertEqual(r["ficha"]["id"], "f2")
        prompt = cliente.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        self.assertIn("1. Onde fica o festival e como chego?", prompt)
        self.assertIn("2. Onde fica o SAC?", prompt)

    def test_zero_ou_numero_invalido_e_nenhuma_ficha(self):
        for valor in (0, 9, "x", None):
            cliente = _ia_respondendo({"tipo": "relato", "urgencia": "Urgente", "ficha": valor})
            with mock.patch.object(server, "_openai_chat_client", return_value=cliente):
                r = server.triar_mensagem_ia("acabou o papel no banheiro", FICHAS[:2])
            self.assertIsNone(r["ficha"], valor)

    def test_sem_fichas_o_prompt_nao_pede_ficha(self):
        cliente = _ia_respondendo({"tipo": "conversa", "urgencia": "Neutro"})
        with mock.patch.object(server, "_openai_chat_client", return_value=cliente):
            r = server.triar_mensagem_ia("oi", [])
        self.assertIsNone(r["ficha"])
        prompt = cliente.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        self.assertNotIn("FICHAS", prompt)

    def test_triar_mensagem_passa_so_as_fichas_ativas(self):
        with mock.patch.object(server, "_fichas_ativas", return_value=[f for f in FICHAS if f["active"]]), \
                mock.patch.object(server, "triar_mensagem_ia", return_value={"tipo": "relato", "urgencia": "Neutro", "ficha": FICHAS[1]}) as ia:
            r = server.triar_mensagem("onde é o sac")
        self.assertEqual([f["id"] for f in ia.call_args.args[1]], ["f1", "f2"])
        self.assertEqual(r["ficha_por"], "ia")

    def test_ia_fora_cai_no_gatilho(self):
        with mock.patch.object(server, "_fichas_ativas", return_value=FICHAS), \
                mock.patch.object(server, "triar_mensagem_ia", return_value=None):
            r = server.triar_mensagem("onde fica o sac?")
        # Pelo gatilho, "onde fica" pega a ficha do festival: é a reserva, pior mesmo.
        self.assertEqual(r["ficha"]["id"], "f1")
        self.assertEqual(r["ficha_por"], "gatilho")


class ComposicaoTests(unittest.TestCase):
    def test_ficha_informada_e_a_que_vai_para_a_resposta(self):
        with mock.patch.object(server, "generate_ai_response", return_value="ok") as gen, \
                mock.patch.object(server, "match_knowledge") as por_gatilho:
            server._compose_reply("onde fica o sac", "Estrutura", "Neutro", None, False, known=FICHAS[1])
        self.assertEqual(gen.call_args.kwargs["official_answer"], FICHAS[1]["answer"])
        por_gatilho.assert_not_called()

    def test_ia_disse_nenhuma_nao_cai_no_gatilho(self):
        with mock.patch.object(server, "generate_ai_response", return_value="ok") as gen, \
                mock.patch.object(server, "match_knowledge") as por_gatilho:
            server._compose_reply("onde fica o sac", "Estrutura", "Neutro", None, False, known=None)
        self.assertIsNone(gen.call_args.kwargs["official_answer"])
        por_gatilho.assert_not_called()

    def test_quem_nao_informa_usa_o_gatilho(self):
        with mock.patch.object(server, "generate_ai_response", return_value="ok"), \
                mock.patch.object(server, "match_knowledge", return_value=FICHAS[0]) as por_gatilho:
            server._compose_reply("onde fica o festival", "Estrutura", "Neutro", None, False)
        por_gatilho.assert_called_once()

    def test_elogio_nunca_usa_ficha(self):
        with mock.patch.object(server, "generate_ai_response", return_value="ok") as gen:
            server._compose_reply("show incrível", "Experiência", "Positivo", None, False, known=FICHAS[1])
        self.assertIsNone(gen.call_args.kwargs["official_answer"])


class SimuladorTests(unittest.TestCase):
    def test_simulador_mostra_a_ficha_escolhida(self):
        triagem = {"tipo": "relato", "urgencia": "Neutro", "ficha": FICHAS[1], "ficha_por": "ia"}
        with mock.patch.object(server, "triar_mensagem", return_value=triagem), \
                mock.patch.object(server, "moderar_texto", return_value={"bloquear": False, "motivo": None}), \
                mock.patch.object(server, "_classify", return_value=("Neutro", "Estrutura & Espaço", "N/A")), \
                mock.patch.object(server, "_compose_reply", return_value="resposta") as compor:
            r = server._simular("onde fica o sac?", None)
        self.assertEqual(r["matched"], {
            "question": "Onde fica o SAC?", "id": "f2", "por": "ia",
            "kind": "faq", "image_url": None,
        })
        self.assertIn("A IA escolheu a ficha", r["explain"])
        self.assertEqual(compor.call_args.kwargs["known"], FICHAS[1])

    def test_simulador_responde_pergunta_ao_tuca_sem_abrir_chamado(self):
        """Igual ao worker: "cadê você?" é respondido pelo modelo de resposta, sem card."""

        triagem = {"tipo": "conversa", "urgencia": "Neutro", "ficha": None, "ficha_por": "ia"}
        with mock.patch.object(server, "triar_mensagem", return_value=triagem), \
                mock.patch.object(server, "moderar_texto", return_value={"bloquear": False, "motivo": None}), \
                mock.patch.object(server, "compose_smalltalk") as oi, \
                mock.patch.object(server, "_compose_reply", return_value="tô aqui") as compor:
            r = server._simular("Voce nao gosta de festa? Kd vc?", None)
        self.assertEqual(r["reply"], "tô aqui")
        self.assertFalse(r["createsCard"])
        self.assertEqual(r["kind"], "conversa")
        oi.assert_not_called()
        self.assertEqual(compor.call_args.args[0], "Voce nao gosta de festa? Kd vc?")

    def test_simulador_cumprimento_puro_vai_para_o_oi(self):
        triagem = {"tipo": "conversa", "urgencia": "Neutro", "ficha": None, "ficha_por": "ia"}
        with mock.patch.object(server, "triar_mensagem", return_value=triagem), \
                mock.patch.object(server, "moderar_texto", return_value={"bloquear": False, "motivo": None}), \
                mock.patch.object(server, "compose_smalltalk", return_value="salve!") as oi, \
                mock.patch.object(server, "_compose_reply") as compor:
            r = server._simular("oi tuca", None)
        self.assertEqual(r["reply"], "salve!")
        oi.assert_called_once()
        compor.assert_not_called()


class PerguntaDuplaTests(unittest.TestCase):
    """Duas perguntas numa mensagem: as duas fichas viram uma resposta oficial."""

    GUIA = FICHAS[:2] + [
        {"id": "f4", "question": "Line-up do Palco Tropical", "answer": "20:25 | Luísa Sonza",
         "kind": "lineup", "image_url": "https://x/lineup.png", "active": True},
    ]

    def test_ficha2_junta_as_duas_respostas(self):
        cliente = _ia_respondendo({"tipo": "relato", "urgencia": "Neutro", "ficha": 2, "ficha2": 3})
        with mock.patch.object(server, "_openai_chat_client", return_value=cliente):
            r = server.triar_mensagem_ia("onde fica o sac e quem toca no tropical?", self.GUIA)
        ficha = r["ficha"]
        self.assertIn("Ao lado da praça de alimentação", ficha["answer"])
        self.assertIn("Luísa Sonza", ficha["answer"])
        # O guia manda no prompt, e a foto sai: banner responderia só pela imagem.
        self.assertEqual(ficha["kind"], "lineup")
        self.assertIsNone(ficha["image_url"])
        prompt = cliente.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        self.assertIn("ficha2", prompt)

    def test_ficha2_igual_ou_invalida_nao_muda_nada(self):
        for segundo in (2, 0, 9, "x", None):
            cliente = _ia_respondendo({"tipo": "relato", "urgencia": "Neutro", "ficha": 2, "ficha2": segundo})
            with mock.patch.object(server, "_openai_chat_client", return_value=cliente):
                r = server.triar_mensagem_ia("onde fica o sac?", self.GUIA)
            self.assertEqual(r["ficha"]["id"], "f2", segundo)
            self.assertEqual(r["ficha"]["answer"], "Ao lado da praça de alimentação da pista.")

    def test_sem_primeira_ficha_a_segunda_e_ignorada(self):
        cliente = _ia_respondendo({"tipo": "relato", "urgencia": "Neutro", "ficha": 0, "ficha2": 3})
        with mock.patch.object(server, "_openai_chat_client", return_value=cliente):
            r = server.triar_mensagem_ia("acabou o papel", self.GUIA)
        self.assertIsNone(r["ficha"])


if __name__ == "__main__":
    unittest.main()
