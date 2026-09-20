"""Integração mínima e segura com a WhatsApp Cloud API oficial da Meta."""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests

logger = logging.getLogger(__name__)

# A Meta encerra cada versão da Graph API dois anos depois do lançamento. A
# v20.0, que este projeto usava, expira em 24/09/2026, dois dias antes do
# Tropicadelia. Por isso a versão tem piso no código: variável esquecida no
# Coolify não pode derrubar o envio no meio do evento.
DEFAULT_GRAPH_API_VERSION = "v26.0"
MIN_GRAPH_API_MAJOR = 21


def graph_api_version() -> str:
    """Versão da Graph API a usar, ignorando valor vencido ou ilegível."""

    configurada = (os.getenv("META_GRAPH_API_VERSION") or "").strip()
    try:
        maior = int(configurada.removeprefix("v").split(".")[0])
    except (AttributeError, IndexError, ValueError):
        if configurada:
            logger.warning(
                "META_GRAPH_API_VERSION ilegível, usando %s", DEFAULT_GRAPH_API_VERSION
            )
        return DEFAULT_GRAPH_API_VERSION
    if maior < MIN_GRAPH_API_MAJOR:
        logger.warning(
            "META_GRAPH_API_VERSION %s está vencida ou perto do fim, usando %s",
            configurada,
            DEFAULT_GRAPH_API_VERSION,
        )
        return DEFAULT_GRAPH_API_VERSION
    return configurada


class MetaAPIError(RuntimeError):
    """Erro controlado ao chamar a Graph API."""


_LONG_DIGITS = re.compile(r"\d{7,}")


def _sanitize(text: str) -> str:
    """Tira telefone do texto de erro antes de logar ou persistir.

    Código da Meta tem no máximo 6 dígitos, então mascarar sequências de 7
    para cima preserva o diagnóstico e descarta identificador de participante.
    """

    return _LONG_DIGITS.sub("[numero]", text)


def describe_api_error(response: Any) -> str:
    """Resume o erro da Graph API em uma linha, sem token e sem telefone.

    Sem isso o operador só vê "envio falhou" e precisa abrir log de container
    para saber se o problema é token, permissão ou janela de atendimento.
    """

    status = getattr(response, "status_code", None) or "sem status"
    try:
        error = (response.json() or {}).get("error") or {}
    except (AttributeError, TypeError, ValueError):
        error = {}
    partes = [f"HTTP {status}"]
    codigo = error.get("code")
    if codigo is not None:
        subcodigo = error.get("error_subcode")
        partes.append(f"code {codigo}.{subcodigo}" if subcodigo else f"code {codigo}")
    detalhe = (
        error.get("error_user_title")
        or ((error.get("error_data") or {}).get("details") if isinstance(error.get("error_data"), dict) else None)
        or error.get("message")
    )
    if detalhe:
        partes.append(_sanitize(str(detalhe))[:300])
    return " | ".join(partes)


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


@dataclass(frozen=True)
class Media:
    """Mídia baixada da Meta, ou o motivo de não ter sido."""

    content: bytes | None
    mime_type: str | None
    file_size: int | None
    # "ok", "muito_grande" ou "indisponivel"
    status: str


DEFAULT_MEDIA_MAX_BYTES = 25 * 1024 * 1024


def fetch_media(
    media_id: str,
    access_token: str,
    graph_api_version: str,
    max_bytes: int = DEFAULT_MEDIA_MAX_BYTES,
) -> Media:
    """Baixa uma mídia recebida (ex.: áudio) em duas etapas da Graph API.

    A Meta não entrega o binário no webhook: primeiro resolvemos a URL
    temporária do media_id e só então baixamos o conteúdo autenticado. O
    tamanho declarado na primeira etapa já barra arquivo grande demais antes
    de gastar banda, e o teto real é conferido de novo depois do download.
    """

    if not media_id or not access_token or not graph_api_version:
        return Media(None, None, None, "indisponivel")
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        lookup = requests.get(
            f"https://graph.facebook.com/{graph_api_version}/{media_id}",
            headers=headers,
            timeout=15,
        )
        lookup.raise_for_status()
        dados = lookup.json() or {}
        media_url = dados.get("url")
        mime_type = dados.get("mime_type")
        try:
            file_size = int(dados.get("file_size")) if dados.get("file_size") is not None else None
        except (TypeError, ValueError):
            file_size = None
        if not media_url:
            return Media(None, mime_type, file_size, "indisponivel")
        if file_size is not None and file_size > max_bytes:
            return Media(None, mime_type, file_size, "muito_grande")
        response = requests.get(media_url, headers=headers, timeout=30)
        response.raise_for_status()
        content = response.content
        if not content:
            return Media(None, mime_type, file_size, "indisponivel")
        if len(content) > max_bytes:
            return Media(None, mime_type, len(content), "muito_grande")
        return Media(content, mime_type, len(content), "ok")
    except requests.RequestException:
        return Media(None, None, None, "indisponivel")
    except (TypeError, ValueError):
        return Media(None, None, None, "indisponivel")


def download_media(media_id: str, access_token: str, graph_api_version: str) -> bytes | None:
    """Compatibilidade: só o binário, ou None."""

    return fetch_media(media_id, access_token, graph_api_version).content


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

        return self._enviar({
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient,
            "type": "text",
            "text": {"preview_url": False, "body": text},
        })

    def send_image(self, recipient: str, link: str, caption: str = "") -> str:
        """Envia uma imagem pública (banner) com legenda opcional.

        A Meta baixa a imagem pela URL no momento do envio, por isso o banner
        precisa estar num endereço público, como o bucket do Supabase.
        """

        imagem: dict[str, Any] = {"link": link}
        if caption:
            imagem["caption"] = caption[:1024]
        return self._enviar({
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient,
            "type": "image",
            "image": imagem,
        })

    def _enviar(self, payload: dict[str, Any]) -> str:
        """Faz o POST em /messages e devolve o ID da Meta, ou levanta MetaAPIError."""

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
            if exc.response is not None:
                raise MetaAPIError(describe_api_error(exc.response)) from exc
            raise MetaAPIError(f"Falha de rede: {type(exc).__name__}") from exc
        except (TypeError, ValueError) as exc:
            raise MetaAPIError("Resposta inválida da Meta") from exc

    def check_credentials(self) -> str:
        """Confere token e número na Graph API sem enviar mensagem para ninguém.

        Serve de diagnóstico: uma leitura do próprio número revela token
        vencido ou sem permissão antes de o evento começar.
        """

        try:
            response = requests.get(
                self._base_url,
                params={"fields": "id,display_phone_number,quality_rating,verified_name"},
                headers={"Authorization": f"Bearer {self._access_token}"},
                timeout=15,
            )
            response.raise_for_status()
            dados = response.json() or {}
            return (
                "ok | numero "
                f"{_sanitize(str(dados.get('display_phone_number') or 'sem numero'))}"
                f" | qualidade {dados.get('quality_rating') or 'sem dado'}"
            )
        except requests.Timeout:
            return "Timeout ao consultar a Meta"
        except requests.RequestException as exc:
            if exc.response is not None:
                return describe_api_error(exc.response)
            return f"Falha de rede: {type(exc).__name__}"
        except (TypeError, ValueError):
            return "Resposta inválida da Meta"
