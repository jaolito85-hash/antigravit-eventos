"""Testes do processamento desacoplado do webhook."""

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
    base = {
        "id": "inbox-id",
        "sender": "5543999999999",
        "sender_hash": "hash",
        "channel_account_id": "phone-id",
        "message_type": "text",
        "content": "#SETOR:PALCO\nBanheiro está sujo",
        "attempts": 0,
    }
    base.update(overrides)
    return base


class WorkerTests(unittest.TestCase):
    def setUp(self):
        # IA desligada nos testes: o pipeline precisa funcionar 100% offline.
        patches = [
            mock.patch.object(worker, "classificar_sentimento_ia", lambda _t: None),
            mock.patch.object(worker, "classificar_com_ia", lambda _t: None),
            mock.patch.object(
                worker, "generate_ai_response", lambda *_a, **_k: None
            ),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_extract_sector_marker(self):
        code, content = _extract_sector("#SETOR:PALCO\nBanheiro sujo")
        self.assertEqual(code, "PALCO")
        self.assertEqual(content, "Banheiro sujo")

    def test_processes_text_without_calling_ai(self):
        store = FakeStore()

        process_inbox(store, _message())

        self.assertIsNone(store.failed)
        self.assertEqual(store.finished, "processed")
        self.assertEqual(store.feedback["region"], "Palco Tropical")
        self.assertEqual(store.feedback["urgency"], "Urgente")
        self.assertEqual(store.response[2], 42)

    def test_rejects_media_without_id_with_guidance(self):
        store = FakeStore()

        process_inbox(store, _message(message_type="audio", content=None))

        self.assertIsNone(store.feedback)
        self.assertEqual(store.finished, "ignored")
        self.assertIn("texto", store.response[1])

    def test_audio_with_media_id_is_transcribed(self):
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

    def test_greeting_receives_welcome_without_creating_card(self):
        store = FakeStore()

        process_inbox(store, _message(content="Oi!"))

        self.assertIsNone(store.feedback)
        self.assertEqual(store.finished, "ignored")
        self.assertIn("ChatBob", store.response[1])
        self.assertIn("Tropicadelia", store.response[1])

    def test_empty_qr_scan_replies_with_sector_cta(self):
        store = FakeStore()

        process_inbox(store, _message(content="#SETOR:PALCO\n"))

        self.assertIsNone(store.feedback)
        self.assertEqual(store.finished, "ignored")
        self.assertIn("Palco Tropical", store.response[1])
        self.assertIn("som", store.response[1])

    def test_video_still_asks_for_text_or_audio(self):
        store = FakeStore()

        process_inbox(store, _message(message_type="video", content=None))

        self.assertIsNone(store.feedback)
        self.assertEqual(store.finished, "ignored")
        self.assertIn("texto", store.response[1])


if __name__ == "__main__":
    unittest.main()
