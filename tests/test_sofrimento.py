"""Sofrimento nunca vira festa, e empolgação nunca vira acolhimento.

O medo do Lucas (20/09): "pô, tô indo à loucura aqui" de alguém em surto ser
lido como alegria. A triagem decide isso com uma orientação explícita, e a
composição respeita a decisão em vez de reabrir o julgamento pela regra.
"""

import json
import unittest
from unittest import mock

import server


def _cliente(conteudo):
    resposta = mock.MagicMock()
    resposta.choices = [mock.MagicMock()]
    resposta.choices[0].message.content = conteudo
    cliente = mock.MagicMock()
    cliente.chat.completions.create.return_value = resposta
    return cliente


class TriagemTests(unittest.TestCase):
    def test_prompt_da_triagem_manda_errar_para_o_lado_da_ajuda(self):
        cliente = _cliente(json.dumps({"tipo": "relato", "urgencia": "Urgente"}))
        with mock.patch.object(server, "_openai_chat_client", return_value=cliente):
            server.triar_mensagem_ia("po, tô indo à loucura aqui")
        system = cliente.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        self.assertIn("SOFRIMENTO NUNCA É POSITIVO", system)
        self.assertIn("tô indo à loucura aqui", system)
        self.assertIn("tô ansioso pro show", system)
        self.assertIn("escolha Urgente", system)


class ComposicaoTests(unittest.TestCase):
    def _mensagem_do_usuario(self, urgencia):
        cliente = _cliente("ok")
        with mock.patch.object(server, "_openai_chat_client", return_value=cliente), \
                mock.patch.object(server, "_bot_config", return_value={"settings": {}, "rules": []}):
            server.generate_ai_response("tô ansioso pro festival", "Experiência Geral", urgencia)
        return cliente.chat.completions.create.call_args.kwargs["messages"][1]["content"]

    def test_positivo_nao_pergunta_se_a_pessoa_esta_mal(self):
        msg = self._mensagem_do_usuario("Positivo")
        self.assertIn("NOT distress", msg)
        self.assertIn("Do NOT ask whether they feel unwell", msg)

    def test_urgente_segue_as_regras_de_acolhimento(self):
        msg = self._mensagem_do_usuario("Urgente")
        self.assertIn("request for help", msg)
        self.assertNotIn("NOT distress", msg)

    def test_neutro_nao_ganha_instrucao_de_sentimento(self):
        msg = self._mensagem_do_usuario("Neutro")
        self.assertNotIn("triage", msg.lower())


class CriticoTests(unittest.TestCase):
    def test_critico_pede_referencia_e_nao_manda_andar(self):
        texto = server._reply("Critico")
        self.assertIn("ponto de referência", texto)
        self.assertIn("o que está vestindo", texto)
        self.assertNotIn("procure agora", texto)


if __name__ == "__main__":
    unittest.main()
