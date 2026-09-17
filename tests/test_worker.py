"""Testes do worker da API oficial da Meta."""

import unittest
from unittest.mock import patch

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
        return {"id": "sector-id", "name": "Palco Tropical"} if code == "PALCO" else None

    def create_feedback(self, **kwargs):
        self.feedback = kwargs
        return 42

    def enqueue_text(self, message, content, feedback_id=None):
        self.response = (message, content, feedback_id)

    def finish_inbox(self, _message_id, status="processed"):
        self.finished = status

    def fail_inbox(self, message, error):
        self.failed = (message, error)


def _text_message(content):
    return {
        "id": "inbox-id",
        "sender": "5543999999999",
        "sender_hash": "hash",
        "channel_account_id": "phone-id",
        "message_type": "text",
        "content": content,
        "attempts": 0,
    }


class WorkerTests(unittest.TestCase):
    def test_extract_sector_marker(self):
        code, content = _extract_sector("#SETOR:PALCO\nBanheiro sujo")
        self.assertEqual(code, "PALCO")
        self.assertEqual(content, "Banheiro sujo")

    @patch("server.classificar_sentimento_ia", return_value="Urgente")
    def test_shortage_report_uses_ai_not_word_list(self, mock_ia):
        store = FakeStore()
        process_inbox(store, _text_message("Falta cerveja no bar do camarote"))

        self.assertIsNone(store.failed)
        self.assertEqual(store.finished, "processed")
        mock_ia.assert_called_once_with("Falta cerveja no bar do camarote")
        self.assertEqual(store.feedback["urgency"], "Urgente")
        self.assertEqual(store.feedback["category"], "Alimentação & Bebidas")
        self.assertIn("destacamos", store.response[1])

    @patch("server.classificar_sentimento_ia", return_value="Urgente")
    def test_unusual_phrasing_still_goes_to_ai(self, mock_ia):
        store = FakeStore()
        content = "no camarote ninguem consegue mais beber o que pediu"
        process_inbox(store, _text_message(content))

        mock_ia.assert_called_once_with(content)
        self.assertEqual(store.feedback["urgency"], "Urgente")

    @patch("server.classificar_sentimento_ia", return_value="Urgente")
    def test_processes_text_with_sector(self, _mock_ia):
        store = FakeStore()
        process_inbox(store, _text_message("#SETOR:PALCO\nBanheiro está sujo"))

        self.assertIsNone(store.failed)
        self.assertEqual(store.finished, "processed")
        self.assertEqual(store.feedback["region"], "Palco Tropical")
        self.assertEqual(store.feedback["urgency"], "Urgente")
        self.assertEqual(store.response[2], 42)

    def test_rejects_media_with_guidance(self):
        store = FakeStore()
        message = {
            "id": "inbox-id",
            "sender": "5543999999999",
            "sender_hash": "hash",
            "channel_account_id": "phone-id",
            "message_type": "audio",
            "content": None,
            "attempts": 0,
        }
        process_inbox(store, message)

        self.assertIsNone(store.feedback)
        self.assertEqual(store.finished, "ignored")
        self.assertIn("texto", store.response[1])


if __name__ == "__main__":
    unittest.main()
