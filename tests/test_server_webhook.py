"""Testes das bordas HTTP do webhook oficial."""

import hashlib
import hmac
import json
import unittest

import server


class FakeStore:
    def __init__(self):
        self.messages = []
        self.statuses = []

    def ingest_messages(self, messages):
        self.messages.extend(messages)
        return len(messages)

    def apply_message_statuses(self, statuses):
        self.statuses.extend(statuses)

    def healthcheck(self):
        return True


class ServerWebhookTests(unittest.TestCase):
    def setUp(self):
        self.original_store = server.EVENT_STORE
        self.store = FakeStore()
        server.EVENT_STORE = self.store
        server.META_APP_SECRET = "test-secret"
        server.META_VERIFY_TOKEN = "verify-token"
        server.META_PHONE_NUMBER_ID = "phone-id"
        server.app.config.update(TESTING=True)
        self.client = server.app.test_client()

    def tearDown(self):
        server.EVENT_STORE = self.original_store

    def _post(self, payload, valid_signature=True):
        body = json.dumps(payload, separators=(",", ":")).encode()
        secret = "test-secret" if valid_signature else "wrong-secret"
        signature = "sha256=" + hmac.new(
            secret.encode(), body, hashlib.sha256
        ).hexdigest()
        return self.client.post(
            "/webhook",
            data=body,
            content_type="application/json",
            headers={"X-Hub-Signature-256": signature},
        )

    def test_verification_challenge(self):
        response = self.client.get(
            "/webhook?hub.mode=subscribe&hub.verify_token=verify-token&hub.challenge=123"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "123")

    def test_verification_rejects_wrong_token(self):
        response = self.client.get(
            "/webhook?hub.mode=subscribe&hub.verify_token=wrong&hub.challenge=123"
        )
        self.assertEqual(response.status_code, 403)

    def test_post_requires_valid_signature(self):
        response = self._post(
            {"object": "whatsapp_business_account", "entry": []},
            valid_signature=False,
        )
        self.assertEqual(response.status_code, 401)

    def test_post_persists_only_configured_number(self):
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "changes": [{
                    "field": "messages",
                    "value": {
                        "metadata": {"phone_number_id": "phone-id"},
                        "messages": [{
                            "from": "5543999999999",
                            "id": "wamid.test",
                            "timestamp": "1789495200",
                            "type": "text",
                            "text": {"body": "Banheiro precisa de limpeza"},
                        }],
                    },
                }],
            }],
        }
        response = self._post(payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.store.messages), 1)
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")


if __name__ == "__main__":
    unittest.main()
