"""Testes do contrato de webhook da WhatsApp Cloud API."""

import hashlib
import hmac
import unittest

from meta_whatsapp import parse_webhook, verify_webhook_signature


class MetaWebhookTests(unittest.TestCase):
    def test_signature_validation(self):
        body = b'{"object":"whatsapp_business_account"}'
        secret = "app-secret"
        signature = "sha256=" + hmac.new(
            secret.encode(), body, hashlib.sha256
        ).hexdigest()

        self.assertTrue(verify_webhook_signature(body, signature, secret))
        self.assertFalse(verify_webhook_signature(body + b" ", signature, secret))
        self.assertFalse(verify_webhook_signature(body, None, secret))

    def test_parse_text_and_delivery_status(self):
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "changes": [{
                    "field": "messages",
                    "value": {
                        "metadata": {"phone_number_id": "1057348230804380"},
                        "contacts": [{
                            "wa_id": "5543999999999",
                            "profile": {"name": "Participante"},
                        }],
                        "messages": [{
                            "from": "5543999999999",
                            "id": "wamid.inbound",
                            "timestamp": "1789495200",
                            "type": "text",
                            "text": {"body": "#SETOR:PALCO\nShow excelente"},
                        }],
                        "statuses": [{
                            "id": "wamid.outbound",
                            "status": "delivered",
                            "timestamp": "1789495201",
                        }],
                    },
                }],
            }],
        }

        messages, statuses = parse_webhook(payload)

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].content, "#SETOR:PALCO\nShow excelente")
        self.assertEqual(messages[0].sender_name, "Participante")
        self.assertEqual(messages[0].message_type, "text")
        self.assertEqual(len(statuses), 1)
        self.assertEqual(statuses[0].status, "delivered")

    def test_unknown_payload_is_ignored(self):
        messages, statuses = parse_webhook({"object": "page", "entry": []})
        self.assertEqual(messages, [])
        self.assertEqual(statuses, [])


if __name__ == "__main__":
    unittest.main()
