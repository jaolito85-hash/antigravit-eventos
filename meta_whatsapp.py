"""Integração mínima e segura com a WhatsApp Cloud API oficial da Meta."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests


class MetaAPIError(RuntimeError):
    """Erro controlado ao chamar a Graph API."""


@dataclass(frozen=True)
class IncomingMessage:
    """Mensagem recebida normalizada, sem depender do payload bruto da Meta."""

    external_message_id: str
    channel_account_id: str
    sender: str
    sender_name: str | None
    message_type: str
    content: str | None
    media_id: str | None
    occurred_at: str | None


@dataclass(frozen=True)
class MessageStatus:
    """Atualização de entrega de uma mensagem enviada."""

    provider_message_id: str
    status: str
    occurred_at: str | None
    error: str | None


def verify_webhook_signature(raw_body: bytes, signature: str | None, app_secret: str) -> bool:
    """Valida a assinatura HMAC enviada pela Meta sem comparação vulnerável a timing."""

    if not signature or not app_secret or not signature.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    provided = signature.removeprefix("sha256=")
    return hmac.compare_digest(expected, provided)


def _iso_timestamp(value: Any) -> str | None:
    """Converte o timestamp Unix da Meta para UTC em ISO-8601."""

    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _message_content(message: dict[str, Any], message_type: str) -> tuple[str | None, str | None]:
    """Extrai somente o conteúdo necessário, evitando persistir o payload inteiro."""

    payload = message.get(message_type) or {}
    if message_type == "text":
        return payload.get("body"), None
    if message_type in {"audio", "image", "video", "document"}:
        return payload.get("caption"), payload.get("id")
    if message_type == "button":
        return payload.get("text") or payload.get("payload"), None
    if message_type == "interactive":
        interactive_type = payload.get("type")
        reply = payload.get(f"{interactive_type}_reply") or {}
        return reply.get("title") or reply.get("id"), None
    if message_type == "location":
        latitude = payload.get("latitude")
        longitude = payload.get("longitude")
        if latitude is not None and longitude is not None:
            return f"{latitude},{longitude}", None
    return None, None


def parse_webhook(payload: dict[str, Any]) -> tuple[list[IncomingMessage], list[MessageStatus]]:
    """Normaliza mensagens e atualizações de status presentes em um webhook."""

    messages: list[IncomingMessage] = []
    statuses: list[MessageStatus] = []
    if payload.get("object") != "whatsapp_business_account":
        return messages, statuses

    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            if change.get("field") != "messages":
                continue
            value = change.get("value") or {}
            channel_account_id = (value.get("metadata") or {}).get("phone_number_id")
            contact_names = {
                str(contact.get("wa_id")): (contact.get("profile") or {}).get("name")
                for contact in value.get("contacts") or []
                if contact.get("wa_id")
            }

            for message in value.get("messages") or []:
                external_id = message.get("id")
                sender = message.get("from")
                if not external_id or not sender or not channel_account_id:
                    continue
                raw_type = str(message.get("type") or "unknown")
                message_type = raw_type if raw_type in {
                    "text", "audio", "image", "video", "document",
                    "location", "interactive",
                } else "unknown"
                content, media_id = _message_content(message, raw_type)
                messages.append(IncomingMessage(
                    external_message_id=str(external_id),
                    channel_account_id=str(channel_account_id),
                    sender=str(sender),
                    sender_name=contact_names.get(str(sender)),
                    message_type=message_type,
                    content=content,
                    media_id=media_id,
                    occurred_at=_iso_timestamp(message.get("timestamp")),
                ))

            for status in value.get("statuses") or []:
                provider_message_id = status.get("id")
                raw_status = status.get("status")
                if not provider_message_id or raw_status not in {
                    "sent", "delivered", "read", "failed",
                }:
                    continue
                errors = status.get("errors") or []
                error = None
                if errors:
                    first_error = errors[0]
                    error = str(first_error.get("code") or first_error.get("title") or "meta_error")[:2000]
                statuses.append(MessageStatus(
                    provider_message_id=str(provider_message_id),
                    status=str(raw_status),
                    occurred_at=_iso_timestamp(status.get("timestamp")),
                    error=error,
                ))

    return messages, statuses


class MetaWhatsAppClient:
    """Cliente HTTP enxuto para enviar mensagens de serviço."""

    def __init__(self, access_token: str, phone_number_id: str, graph_api_version: str) -> None:
        if not access_token or not phone_number_id or not graph_api_version:
            raise ValueError("Configuração da Meta incompleta")
        self._access_token = access_token
        self._phone_number_id = phone_number_id
        self._base_url = (
            f"https://graph.facebook.com/{graph_api_version}/{phone_number_id}"
        )

    def send_text(self, recipient: str, text: str) -> str:
        """Envia texto dentro da janela de atendimento e retorna o ID da Meta."""

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient,
            "type": "text",
            "text": {"preview_url": False, "body": text},
        }
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }
        try:
            response = requests.post(
                f"{self._base_url}/messages",
                json=payload,
                headers=headers,
                timeout=15,
            )
            response.raise_for_status()
            data = response.json()
            message_id = ((data.get("messages") or [{}])[0]).get("id")
            if not message_id:
                raise MetaAPIError("Resposta da Meta sem ID de mensagem")
            return str(message_id)
        except requests.Timeout as exc:
            raise MetaAPIError("Timeout ao enviar mensagem para a Meta") from exc
        except requests.RequestException as exc:
            status = exc.response.status_code if exc.response is not None else "network"
            raise MetaAPIError(f"Falha da Meta HTTP {status}") from exc
        except (TypeError, ValueError) as exc:
            raise MetaAPIError("Resposta inválida da Meta") from exc
