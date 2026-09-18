"""Persistência durável do pipeline de mensagens no Supabase."""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from meta_whatsapp import IncomingMessage, MessageStatus

logger = logging.getLogger(__name__)


class StoreConfigurationError(RuntimeError):
    """Configuração obrigatória do banco ausente ou inválida."""


try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


class EventStore:
    """Acesso centralizado às tabelas operacionais do evento."""

    def __init__(self) -> None:
        self._url = os.getenv("SUPABASE_URL", "")
        self._key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
        self._event_slug = os.getenv("EVENT_SLUG", "tropicadelia-2026")
        self._hash_secret = os.getenv("PII_HASH_SECRET", "")
        self._client: Any = None
        self._event_id: str | None = None
        # event_id() inicializa o cliente dentro da região crítica; o lock
        # reentrante evita deadlock sem abrir uma corrida entre workers.
        self._lock = threading.RLock()

    def _get_client(self) -> Any:
        """Cria o cliente somente quando necessário para facilitar health checks."""

        if not self._url or not self._key:
            raise StoreConfigurationError(
                "SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY são obrigatórios"
            )
        if self._client is None:
            with self._lock:
                if self._client is None:
                    try:
                        from supabase import create_client

                        self._client = create_client(self._url, self._key)
                    except Exception as exc:
                        raise StoreConfigurationError(
                            "Não foi possível inicializar o cliente Supabase"
                        ) from exc
        return self._client

    def event_id(self) -> str:
        """Resolve o evento configurado e mantém apenas seu identificador em cache."""

        if self._event_id:
            return self._event_id
        with self._lock:
            if self._event_id:
                return self._event_id
            response = (
                self._get_client()
                .table("events")
                .select("id")
                .eq("slug", self._event_slug)
                .limit(1)
                .execute()
            )
            if not response.data:
                raise StoreConfigurationError(
                    f"Evento configurado não existe: {self._event_slug}"
                )
            self._event_id = str(response.data[0]["id"])
            return self._event_id

    def healthcheck(self) -> bool:
        """Confirma acesso à service role e existência do evento."""

        try:
            return bool(self.event_id())
        except Exception as exc:  # noqa: BLE001 - health check must never crash the web process
            logger.error("Health check do banco falhou: %s", type(exc).__name__)
            return False

    def sender_hash(self, sender: str) -> str:
        """Pseudonimiza telefone com HMAC para impedir ataques por enumeração."""

        if not self._hash_secret:
            raise StoreConfigurationError("PII_HASH_SECRET é obrigatório")
        return hmac.new(
            self._hash_secret.encode("utf-8"),
            sender.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def ingest_messages(self, messages: list[IncomingMessage]) -> int:
        """Insere mensagens normalizadas e ignora repetições da Meta."""

        if not messages:
            return 0
        event_id = self.event_id()
        rows = [
            {
                "event_id": event_id,
                "provider": "meta",
                "channel_account_id": message.channel_account_id,
                "external_message_id": message.external_message_id,
                "sender": message.sender,
                "sender_hash": self.sender_hash(message.sender),
                "sender_name": (message.sender_name or "")[:200] or None,
                "message_type": message.message_type,
                "content": (message.content or "")[:5000] or None,
                "media_id": message.media_id,
                "occurred_at": message.occurred_at,
                "processing_status": "pending",
            }
            for message in messages
        ]
        response = (
            self._get_client()
            .table("message_inbox")
            .upsert(
                rows,
                on_conflict="provider,channel_account_id,external_message_id",
                ignore_duplicates=True,
            )
            .execute()
        )
        return len(response.data or [])

    def apply_message_statuses(self, statuses: list[MessageStatus]) -> None:
        """Atualiza estados de entrega sem registrar destinatários nos logs."""

        client = self._get_client()
        for status in statuses:
            updates: dict[str, Any] = {"delivery_status": status.status}
            if status.occurred_at:
                updates[f"{status.status}_at"] = status.occurred_at
            if status.error:
                updates["last_error"] = status.error
            client.table("outbound_messages").update(updates).eq(
                "provider", "meta"
            ).eq("provider_message_id", status.provider_message_id).execute()

    def pending_inbox(self, limit: int = 20) -> list[dict[str, Any]]:
        """Busca um lote pequeno para manter o worker responsivo."""

        now = datetime.now(timezone.utc).isoformat()
        response = (
            self._get_client()
            .table("message_inbox")
            .select("*")
            .in_("processing_status", ["pending", "failed"])
            .lt("attempts", int(os.getenv("WORKER_MAX_ATTEMPTS", "8")))
            .lte("next_attempt_at", now)
            .order("created_at")
            .limit(limit)
            .execute()
        )
        return list(response.data or [])

    def claim_inbox(self, message: dict[str, Any]) -> bool:
        """Reivindica atomicamente uma mensagem caso outro worker não a tenha pego."""

        attempts = int(message.get("attempts") or 0)
        response = (
            self._get_client()
            .table("message_inbox")
            .update({"processing_status": "processing", "attempts": attempts + 1})
            .eq("id", message["id"])
            .eq("attempts", attempts)
            .in_("processing_status", ["pending", "failed"])
            .execute()
        )
        return bool(response.data)

    def finish_inbox(self, message_id: str, status: str = "processed") -> None:
        """Marca processamento concluído ou ignorado."""

        self._get_client().table("message_inbox").update({
            "processing_status": status,
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "last_error": None,
        }).eq("id", message_id).execute()

    def fail_inbox(self, message: dict[str, Any], error: Exception) -> None:
        """Agenda nova tentativa com backoff limitado."""

        attempts = int(message.get("attempts") or 0) + 1
        terminal = attempts >= int(os.getenv("WORKER_MAX_ATTEMPTS", "8"))
        delay = min(300, 2 ** min(attempts, 8))
        self._get_client().table("message_inbox").update({
            "processing_status": "failed",
            "next_attempt_at": (
                datetime.now(timezone.utc) + timedelta(seconds=delay)
            ).isoformat(),
            "last_error": f"{type(error).__name__}: processamento falhou"[:2000],
            "processed_at": datetime.now(timezone.utc).isoformat() if terminal else None,
        }).eq("id", message["id"]).execute()

    def recent_sender_count(self, sender_hash: str) -> int:
        """Conta mensagens recentes para limitar abuso de forma compartilhada."""

        since = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        response = (
            self._get_client()
            .table("message_inbox")
            .select("id", count="exact")
            .eq("event_id", self.event_id())
            .eq("sender_hash", sender_hash)
            .gte("created_at", since)
            .execute()
        )
        return int(response.count or 0)

    def sector_by_code(self, code: str | None) -> dict[str, Any] | None:
        """Resolve o setor codificado no QR sem inferência por IA."""

        if not code:
            return None
        response = (
            self._get_client()
            .table("event_sectors")
            .select("id,code,name,metadata")
            .eq("event_id", self.event_id())
            .eq("code", code)
            .eq("active", True)
            .limit(1)
            .execute()
        )
        return response.data[0] if response.data else None

    def list_sectors(self) -> list[dict[str, Any]]:
        """Lista os setores ativos com a metadata de posicionamento na planta."""

        response = (
            self._get_client()
            .table("event_sectors")
            .select("id,code,name,metadata")
            .eq("event_id", self.event_id())
            .eq("active", True)
            .order("code")
            .execute()
        )
        return list(response.data or [])

    def create_feedback(
        self,
        message: dict[str, Any],
        content: str,
        category: str,
        region: str,
        urgency: str,
        topic: str,
        sector_id: str | None,
    ) -> int:
        """Cria um feedback 1:1 com a mensagem para manter rastreabilidade."""

        sentiment = (
            "Positivo"
            if urgency == "Positivo"
            else "Negativo"
            if urgency in {"Critico", "Urgente"}
            else "Neutro"
        )
        row = {
            "event_id": self.event_id(),
            "sector_id": sector_id,
            "inbox_message_id": message["id"],
            "sender": None,
            "sender_hash": message.get("sender_hash"),
            "name": "Anônimo",
            "message": content[:5000],
            "category": category,
            "region": region,
            "urgency": urgency,
            "sentiment": sentiment,
            "topic": topic[:200],
            "status": "aberto",
            "resolved_at": None,
            "source": "meta",
        }
        response = (
            self._get_client()
            .table("feedbacks")
            .upsert(
                row,
                on_conflict="inbox_message_id",
                ignore_duplicates=True,
            )
            .execute()
        )
        if response.data:
            return int(response.data[0]["id"])
        existing = (
            self._get_client()
            .table("feedbacks")
            .select("id")
            .eq("inbox_message_id", message["id"])
            .limit(1)
            .execute()
        )
        if not existing.data:
            raise RuntimeError("Supabase não retornou o feedback criado")
        return int(existing.data[0]["id"])

    def enqueue_text(
        self,
        message: dict[str, Any],
        content: str,
        feedback_id: int | None = None,
    ) -> None:
        """Enfileira resposta idempotente para envio fora do processamento."""

        row = {
            "event_id": self.event_id(),
            "feedback_id": feedback_id,
            "provider": "meta",
            "channel_account_id": message["channel_account_id"],
            "recipient": message["sender"],
            "message_type": "text",
            "content": content[:4096],
            "idempotency_key": f"inbox:{message['id']}:reply",
            "delivery_status": "queued",
        }
        (
            self._get_client()
            .table("outbound_messages")
            .upsert(row, on_conflict="idempotency_key", ignore_duplicates=True)
            .execute()
        )

    def pending_outbox(self, limit: int = 20) -> list[dict[str, Any]]:
        """Busca respostas prontas para envio."""

        now = datetime.now(timezone.utc).isoformat()
        response = (
            self._get_client()
            .table("outbound_messages")
            .select("*")
            .in_("delivery_status", ["queued", "failed"])
            .lte("next_attempt_at", now)
            .order("created_at")
            .limit(limit)
            .execute()
        )
        return list(response.data or [])

    def claim_outbox(self, message: dict[str, Any]) -> bool:
        """Reivindica atomicamente um envio pendente."""

        attempts = int(message.get("attempts") or 0)
        response = (
            self._get_client()
            .table("outbound_messages")
            .update({"delivery_status": "sending", "attempts": attempts + 1})
            .eq("id", message["id"])
            .eq("attempts", attempts)
            .in_("delivery_status", ["queued", "failed"])
            .execute()
        )
        return bool(response.data)

    def mark_outbox_sent(self, message_id: str, provider_message_id: str) -> None:
        """Registra o aceite síncrono da Graph API."""

        self._get_client().table("outbound_messages").update({
            "delivery_status": "sent",
            "provider_message_id": provider_message_id,
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "last_error": None,
        }).eq("id", message_id).execute()

    def fail_outbox(self, message: dict[str, Any], error: Exception) -> None:
        """Agenda reenvio; nunca registra token, telefone ou resposta da Meta."""

        attempts = int(message.get("attempts") or 0) + 1
        terminal = attempts >= int(os.getenv("WORKER_MAX_ATTEMPTS", "8"))
        delay = min(300, 4 ** min(attempts, 4))
        self._get_client().table("outbound_messages").update({
            "delivery_status": "cancelled" if terminal else "failed",
            "next_attempt_at": (
                datetime.now(timezone.utc) + timedelta(seconds=delay)
            ).isoformat(),
            "last_error": f"{type(error).__name__}: envio falhou"[:2000],
            "failed_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", message["id"]).execute()
