"""Testes do processamento desacoplado do webhook."""

import unittest

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


class WorkerTests(unittest.TestCase):
    def test_extract_sector_marker(self):
        code, content = _extract_sector("#SETOR:PALCO\nBanheiro sujo")
        self.assertEqual(code, "PALCO")
        self.assertEqual(content, "Banheiro sujo")

    def test_shortage_report_is_urgent_not_neutral(self):
        store = FakeStore()
        message = {
            "id": "inbox-id",
            "sender": "5543999999999",
            "sender_hash": "hash",
            "channel_account_id": "phone-id",
            "message_type": "text",
            "content": "Falta cerveja no bar do camarote",
            "attempts": 0,
        }

        process_inbox(store, message)

        self.assertIsNone(store.failed)
        self.assertEqual(store.finished, "processed")
        self.assertEqual(store.feedback["urgency"], "Urgente")
        self.assertEqual(store.feedback["category"], "Alimentação & Bebidas")
        self.assertIn("destacamos", store.response[1])

    def test_processes_text_without_calling_ai(self):
        store = FakeStore()
        message = {
            "id": "inbox-id",
            "sender": "5543999999999",
            "sender_hash": "hash",
            "channel_account_id": "phone-id",
            "message_type": "text",
            "content": "#SETOR:PALCO\nBanheiro está sujo",
            "attempts": 0,
        }

        process_inbox(store, message)

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
