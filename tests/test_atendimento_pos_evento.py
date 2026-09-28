"""Defeitos vistos na operação do Tropicadelia (26/09/2026).

- A saudação "equipe assumindo a conversa" saiu três vezes na mesma
  conversa, porque cada "assumir" mandava de novo.
- O operador perguntou onde a pessoa estava com o setor já no chamado: a
  janela da conversa não mostrava o lugar.
- O Tuca citou "Sanitários Femininos" numa resposta carinhosa, porque o
  prompt mandava citar o setor sempre.
"""

import unittest
from unittest import mock

import server

CONVERSA = "a" * 64


class SaudacaoDoOperadorTests(unittest.TestCase):
    def setUp(self):
        self.client = server.app.test_client()
        with self.client.session_transaction() as s:
            s["logged_in"] = True
        self.store = mock.MagicMock()
        patcher = mock.patch.object(server, "EVENT_STORE", self.store)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _assumir(self):
        return self.client.put(f"/api/conversations/{CONVERSA}/mode", json={"mode": "human"})

    def test_primeira_vez_manda_a_saudacao(self):
        self.store.conversation_mode.return_value = "bot"
        self.store.operator_message_sent_recently.return_value = False
        self.assertEqual(self._assumir().status_code, 200)
        self.store.enqueue_operator_message.assert_called_once_with(CONVERSA, server.SAUDACAO_OPERADOR)

    def test_ja_assumida_nao_saúda_de_novo(self):
        self.store.conversation_mode.return_value = "human"
        self.assertEqual(self._assumir().status_code, 200)
        self.store.enqueue_operator_message.assert_not_called()

    def test_reassumida_logo_depois_de_devolver_nao_saúda(self):
        self.store.conversation_mode.return_value = "bot"
        self.store.operator_message_sent_recently.return_value = True
        self.assertEqual(self._assumir().status_code, 200)
        self.store.enqueue_operator_message.assert_not_called()
        self.store.set_conversation_mode.assert_called_once()

    def test_devolver_nunca_saúda(self):
        self.store.conversation_mode.return_value = "human"
        self.client.put(f"/api/conversations/{CONVERSA}/mode", json={"mode": "bot"})
        self.store.enqueue_operator_message.assert_not_called()


class LugarNaConversaTests(unittest.TestCase):
    def test_conversa_leva_o_lugar(self):
        store = mock.MagicMock()
        store.conversation_thread.return_value = {"messages": [], "mode": "bot"}
        store.conversation_location.return_value = {"name": "Bar Hype • Backstage Hype", "source": "qr_recente"}
        with mock.patch.object(server, "EVENT_STORE", store):
            payload = server._conversation_payload(CONVERSA)
        self.assertEqual(payload["location"]["name"], "Bar Hype • Backstage Hype")

    def test_falha_no_lugar_nao_derruba_a_conversa(self):
        store = mock.MagicMock()
        store.conversation_thread.return_value = {"messages": [], "mode": "bot"}
        store.conversation_location.side_effect = RuntimeError("fora do ar")
        with mock.patch.object(server, "EVENT_STORE", store):
            payload = server._conversation_payload(CONVERSA)
        self.assertIsNone(payload["location"])


class SetorNaRespostaTests(unittest.TestCase):
    SETOR = {"id": "s1", "name": "Sanitários Femininos Hype • Pista"}

    def _setor_enviado(self, urgencia):
        with mock.patch.object(server, "generate_ai_response", return_value="ok") as gen:
            server._compose_reply("texto", "Experiência Geral", urgencia, self.SETOR, False, known=None)
        return gen.call_args.args[3]

    def test_elogio_nao_recebe_o_setor(self):
        self.assertIsNone(self._setor_enviado("Positivo"))

    def test_problema_recebe_o_setor(self):
        self.assertEqual(self._setor_enviado("Urgente"), self.SETOR["name"])

    def test_prompt_diz_que_o_setor_e_a_placa_e_nao_o_assunto(self):
        cliente = mock.MagicMock()
        cliente.chat.completions.create.return_value.choices = [mock.MagicMock()]
        cliente.chat.completions.create.return_value.choices[0].message.content = "Valeu! 🦜"
        with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "x"}), \
                mock.patch.object(server, "_openai_chat_client", return_value=cliente):
            server.generate_ai_response("o show do Livinho foi playback", "Programação", "Neutro",
                                        self.SETOR["name"])
        mensagens = cliente.chat.completions.create.call_args.kwargs["messages"]
        prompt = " ".join(str(m.get("content")) for m in mensagens)
        self.assertIn("not necessarily what they are talking about", prompt)
        self.assertNotIn("Mention the place naturally", prompt)


if __name__ == "__main__":
    unittest.main()
