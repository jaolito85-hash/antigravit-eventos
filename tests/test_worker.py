"""Testes do worker da API oficial da Meta."""

import unittest
from unittest import mock

import worker
from worker import _extract_sector, process_inbox


class FakeStore:
    def __init__(self):
        self.feedback = None
        self.response = None
        self.finished = None
        self.failed = None

    def claim_inbox(self, _message):
        return True

    def recent_sender_count(self, _sender_hash):
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
        # Nenhum teste toca a rede: a resposta criativa e o enriquecimento de
        # categoria ficam desligados, então sobra o texto determinístico.
        for target in ("generate_ai_response", "classificar_com_ia"):
            patcher = mock.patch.object(worker, target, lambda *a, **k: None)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_extract_sector_marker(self):
        code, content = _extract_sector("#SETOR:PALCO\nBanheiro sujo")
        self.assertEqual(code, "PALCO")
        self.assertEqual(content, "Banheiro sujo")

    @mock.patch("server.classificar_sentimento_ia", return_value="Urgente")
    def test_falta_de_estoque_vai_para_a_ia(self, mock_ia):
        store = FakeStore()

        process_inbox(store, _message(content="Falta cerveja no bar do camarote"))

        self.assertIsNone(store.failed)
        self.assertEqual(store.finished, "processed")
        mock_ia.assert_called_once_with("Falta cerveja no bar do camarote")
        self.assertEqual(store.feedback["urgency"], "Urgente")
        self.assertEqual(store.feedback["category"], "Alimentação & Bebidas")
        self.assertIn("destacamos", store.response[1])

    @mock.patch("server.classificar_sentimento_ia", return_value="Urgente")
    def test_frase_incomum_ainda_passa_pela_ia(self, mock_ia):
        store = FakeStore()
        content = "no camarote ninguem consegue mais beber o que pediu"

        process_inbox(store, _message(content=content))

        mock_ia.assert_called_once_with(content)
        self.assertEqual(store.feedback["urgency"], "Urgente")

    @mock.patch("server.classificar_sentimento_ia", return_value=None)
    def test_palavras_chave_assumem_quando_a_ia_cai(self, _mock_ia):
        """Com a OpenAI fora do ar, um relato de falta não pode virar Neutro."""

        store = FakeStore()

        process_inbox(store, _message(content="Falta cerveja no bar do camarote"))

        self.assertEqual(store.finished, "processed")
        self.assertEqual(store.feedback["urgency"], "Urgente")

    @mock.patch("server.classificar_sentimento_ia", return_value="Urgente")
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

    @mock.patch("server.classificar_sentimento_ia", return_value="Urgente")
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

    def test_saudacao_recebe_boas_vindas_sem_criar_card(self):
        store = FakeStore()

        process_inbox(store, _message(content="Oi!"))

        self.assertIsNone(store.feedback)
        self.assertEqual(store.finished, "ignored")
        self.assertIn("ChatBob", store.response[1])
        self.assertIn("Tropicadelia", store.response[1])

    def test_scan_de_qr_sem_texto_responde_o_convite_do_setor(self):
        store = FakeStore()

        process_inbox(store, _message(content="#SETOR:PALCO\n"))

        self.assertIsNone(store.feedback)
        self.assertEqual(store.finished, "ignored")
        self.assertIn("Palco Tropical", store.response[1])
        self.assertIn("som", store.response[1])

    def test_video_pede_texto_ou_audio(self):
        store = FakeStore()

        process_inbox(store, _message(message_type="video", content=None))

        self.assertIsNone(store.feedback)
        self.assertEqual(store.finished, "ignored")
        self.assertIn("texto", store.response[1])


if __name__ == "__main__":
    unittest.main()
