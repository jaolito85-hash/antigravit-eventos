"""Testes do worker da API oficial da Meta."""

import unittest
from unittest import mock

import server
import worker
from worker import _extract_sector, process_inbox


class FakeStore:
    def __init__(self, mode="bot"):
        self.feedback = None
        self.response = None
        self.finished = None
        self.failed = None
        self.mode = mode
        self.rate_checked = False

    def claim_inbox(self, _message):
        return True

    def conversation_mode(self, _sender_hash):
        return self.mode

    def recent_sender_count(self, _sender_hash):
        self.rate_checked = True
        return 1

    def sector_by_code(self, code):
        if code == "PALCO":
            return {
                "id": "sector-id",
                "name": "Palco Tropical",
                "metadata": {"cta": "Como está o som por aí?"},
            }
        return None

    def create_feedback(self, **kwargs):
        self.feedback = kwargs
        return 42

    def enqueue_text(self, message, content, feedback_id=None):
        self.response = (message, content, feedback_id)

    def finish_inbox(self, _message_id, status="processed"):
        self.finished = status

    def fail_inbox(self, message, error):
        self.failed = (message, error)


def _message(**overrides):
    """Mensagem de entrada padrão com os campos que o worker consome."""

    base = {
        "id": "inbox-id",
        "sender": "5543999999999",
        "sender_hash": "hash",
        "channel_account_id": "phone-id",
        "message_type": "text",
        "content": "#SETOR:PALCO\nBanheiro está sujo",
        "media_id": None,
        "attempts": 0,
    }
    base.update(overrides)
    return base


class WorkerTests(unittest.TestCase):
    def setUp(self):
        # Nenhum teste toca a rede. A decisão do bot mora no server, então é
        # lá que a resposta criativa e o enriquecimento de categoria ficam
        # desligados, sobrando o texto determinístico.
        for target in ("generate_ai_response", "classificar_com_ia"):
            patcher = mock.patch.object(server, target, lambda *a, **k: None)
            patcher.start()
            self.addCleanup(patcher.stop)

        # A conversa por IA também sai do caminho. O patch vai no worker, que é
        # quem chama a função: o nome foi importado para o namespace dele.
        smalltalk = mock.patch.object(
            worker, "compose_smalltalk", lambda _c: "BOAS-VINDAS DO CHATBOB"
        )
        smalltalk.start()
        self.addCleanup(smalltalk.stop)

    def test_extract_sector_marker(self):
        code, content = _extract_sector("#SETOR:PALCO\nBanheiro sujo")
        self.assertEqual(code, "PALCO")
        self.assertEqual(content, "Banheiro sujo")

    @mock.patch("server.triar_mensagem_ia",
                return_value={"tipo": "relato", "urgencia": "Urgente"})
    def test_falta_de_estoque_vai_para_a_ia(self, mock_ia):
        store = FakeStore()

        process_inbox(store, _message(content="Falta cerveja no bar do camarote"))

        self.assertIsNone(store.failed)
        self.assertEqual(store.finished, "processed")
        mock_ia.assert_called_once_with("Falta cerveja no bar do camarote")
        self.assertEqual(store.feedback["urgency"], "Urgente")
        self.assertEqual(store.feedback["category"], "Alimentação & Bebidas")
        self.assertIn("destacamos", store.response[1])

    @mock.patch("server.triar_mensagem_ia",
                return_value={"tipo": "relato", "urgencia": "Urgente"})
    def test_frase_incomum_ainda_passa_pela_ia(self, mock_ia):
        store = FakeStore()
        content = "no camarote ninguem consegue mais beber o que pediu"

        process_inbox(store, _message(content=content))

        mock_ia.assert_called_once_with(content)
        self.assertEqual(store.feedback["urgency"], "Urgente")

    @mock.patch("server.triar_mensagem_ia", return_value=None)
    def test_palavras_chave_assumem_quando_a_ia_cai(self, _mock_ia):
        """Com a OpenAI fora do ar, um relato de falta não pode virar Neutro."""

        store = FakeStore()

        process_inbox(store, _message(content="Falta cerveja no bar do camarote"))

        self.assertEqual(store.finished, "processed")
        self.assertEqual(store.feedback["urgency"], "Urgente")

    @mock.patch("server.triar_mensagem_ia",
                return_value={"tipo": "relato", "urgencia": "Urgente"})
    def test_processa_texto_com_setor(self, _mock_ia):
        store = FakeStore()

        process_inbox(store, _message())

        self.assertIsNone(store.failed)
        self.assertEqual(store.finished, "processed")
        self.assertEqual(store.feedback["region"], "Palco Tropical")
        self.assertEqual(store.feedback["urgency"], "Urgente")
        self.assertEqual(store.response[2], 42)

    def test_audio_sem_media_id_pede_texto(self):
        store = FakeStore()

        process_inbox(store, _message(message_type="audio", content=None))

        self.assertIsNone(store.feedback)
        self.assertEqual(store.finished, "ignored")
        self.assertIn("texto", store.response[1])

    @mock.patch("server.triar_mensagem_ia",
                return_value={"tipo": "relato", "urgencia": "Urgente"})
    def test_audio_com_media_id_e_transcrito(self, _mock_ia):
        store = FakeStore()

        with mock.patch.object(
            worker, "_transcribe_inbox_audio", lambda _m: "fila enorme no bar"
        ):
            process_inbox(
                store,
                _message(message_type="audio", content=None, media_id="media-1"),
            )

        self.assertEqual(store.finished, "processed")
        self.assertEqual(store.feedback["urgency"], "Urgente")
        self.assertIn("áudio", store.response[1])

    @mock.patch("server.triar_mensagem_ia",
                return_value={"tipo": "conversa", "urgencia": "Neutro"})
    def test_conversa_recebe_resposta_sem_criar_card(self, _mock_ia):
        """A IA disse que e conversa: responde e nao entra na fila de trabalho."""

        store = FakeStore()

        process_inbox(store, _message(content="Oi!"))

        self.assertIsNone(store.feedback)
        self.assertEqual(store.finished, "ignored")
        self.assertIn("CHATBOB", store.response[1])

    def test_scan_de_qr_sem_texto_responde_o_convite_do_setor(self):
        store = FakeStore()

        process_inbox(store, _message(content="#SETOR:PALCO\n"))

        self.assertIsNone(store.feedback)
        self.assertEqual(store.finished, "ignored")
        self.assertIn("Palco Tropical", store.response[1])
        self.assertIn("som", store.response[1])

    # ------------------------------------------------------------------
    # Atendimento humano: o bot registra e cala a boca
    # ------------------------------------------------------------------

    @mock.patch("server.triar_mensagem_ia",
                return_value={"tipo": "relato", "urgencia": "Urgente"})
    def test_operador_no_comando_registra_sem_responder(self, _mock_ia):
        """Com o operador na conversa, o chamado entra mas nada e enviado."""

        store = FakeStore(mode="human")

        process_inbox(store, _message(content="a fila do bar travou de novo"))

        self.assertIsNone(store.failed)
        self.assertEqual(store.finished, "processed")
        self.assertIsNotNone(store.feedback)
        self.assertEqual(store.feedback["urgency"], "Urgente")
        # O participante esta falando com uma pessoa: nada de resposta do bot.
        self.assertIsNone(store.response)

    @mock.patch("server.triar_mensagem_ia",
                return_value={"tipo": "conversa", "urgencia": "Neutro"})
    def test_operador_no_comando_nao_manda_boas_vindas(self, _mock_ia):
        store = FakeStore(mode="human")

        process_inbox(store, _message(content="oi"))

        self.assertIsNone(store.feedback)
        self.assertEqual(store.finished, "ignored")
        self.assertIsNone(store.response)

    @mock.patch("server.triar_mensagem_ia", return_value=None)
    def test_operador_no_comando_nao_manda_convite_do_setor(self, _mock_ia):
        store = FakeStore(mode="human")

        conteudo = "#SETOR:PALCO" + chr(10)
        process_inbox(store, _message(content=conteudo))

        self.assertIsNone(store.feedback)
        self.assertIsNone(store.response)

    @mock.patch("server.triar_mensagem_ia",
                return_value={"tipo": "relato", "urgencia": "Positivo"})
    def test_operador_no_comando_ignora_o_limite_de_mensagens(self, _mock_ia):
        """Quem esta conversando com a equipe pode escrever a vontade."""

        store = FakeStore(mode="human")
        store.recent_sender_count = lambda _h: 99

        process_inbox(store, _message(content="obrigado pela ajuda de voces"))

        self.assertEqual(store.finished, "processed")
        self.assertIsNone(store.response)

    @mock.patch("server.triar_mensagem_ia",
                return_value={"tipo": "relato", "urgencia": "Urgente"})
    def test_bot_volta_a_responder_quando_devolvem_a_conversa(self, _mock_ia):
        store = FakeStore(mode="bot")

        process_inbox(store, _message(content="a fila do bar travou de novo"))

        self.assertEqual(store.finished, "processed")
        self.assertIsNotNone(store.response)
        self.assertIn("destacamos", store.response[1])

    def test_video_pede_texto_ou_audio(self):
        store = FakeStore()

        process_inbox(store, _message(message_type="video", content=None))

        self.assertIsNone(store.feedback)
        self.assertEqual(store.finished, "ignored")
        self.assertIn("texto", store.response[1])


if __name__ == "__main__":
    unittest.main()
