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

    def replies_for_feedback(self, feedback_id: int) -> list[dict[str, Any]]:
        """O que já saiu para o participante por causa deste chamado.

        O worker grava feedback_id ao enfileirar a resposta, então isso liga a
        mensagem recebida ao texto exato que o bot devolveu, com o estado de
        entrega que a Meta confirmou.
        """

        response = (
            self._get_client()
            .table("outbound_messages")
            .select("content,origin,delivery_status,created_at,sent_at,delivered_at,read_at,last_error")
            .eq("event_id", self.event_id())
            .eq("feedback_id", feedback_id)
            .order("created_at")
            .execute()
        )
        return [
            {
                "content": row.get("content"),
                "origin": row.get("origin") or "bot",
                "status": row.get("delivery_status"),
                "at": row.get("sent_at") or row.get("created_at"),
                "error": row.get("last_error"),
            }
            for row in (response.data or [])
        ]

    def feedback_by_id(self, feedback_id: int) -> dict[str, Any] | None:
        """Carrega um chamado do evento atual."""

        response = (
            self._get_client()
            .table("feedbacks")
            .select("*")
            .eq("event_id", self.event_id())
            .eq("id", feedback_id)
            .limit(1)
            .execute()
        )
        return response.data[0] if response.data else None

    # ------------------------------------------------------------------
    # Base de perguntas e respostas do bot
    # ------------------------------------------------------------------

    # O worker consulta a base em toda mensagem. Sem cache seria uma ida ao
    # banco por participante; com 30s o operador ainda ve o efeito na hora.
    _KNOWLEDGE_TTL_SECONDS = 30

    def knowledge(self, only_active: bool = True) -> list[dict[str, Any]]:
        """Perguntas e respostas do evento, da maior para a menor prioridade."""

        cache = getattr(self, "_knowledge_cache", None)
        now = datetime.now(timezone.utc)
        if (
            only_active
            and cache
            and (now - cache["at"]).total_seconds() < self._KNOWLEDGE_TTL_SECONDS
        ):
            return cache["rows"]

        query = (
            self._get_client()
            .table("bot_knowledge")
            .select("id,question,answer,keywords,priority,active")
            .eq("event_id", self.event_id())
        )
        if only_active:
            query = query.eq("active", True)
        try:
            response = query.order("priority", desc=True).execute()
        except Exception as exc:  # noqa: BLE001 - base indisponível não cala o bot
            logger.error("Falha ao ler base do bot: %s", type(exc).__name__)
            return cache["rows"] if cache else []

        rows = list(response.data or [])
        if only_active:
            self._knowledge_cache = {"rows": rows, "at": now}
        return rows

    def save_knowledge(self, entry: dict[str, Any]) -> dict[str, Any]:
        """Cria ou atualiza uma pergunta e resposta."""

        row = {
            "event_id": self.event_id(),
            "question": str(entry.get("question") or "").strip()[:300],
            "answer": str(entry.get("answer") or "").strip()[:1500],
            "keywords": [
                str(k).strip().lower()[:80]
                for k in (entry.get("keywords") or [])
                if str(k).strip()
            ][:30],
            "priority": max(0, min(100, int(entry.get("priority") or 0))),
            "active": bool(entry.get("active", True)),
        }
        client = self._get_client()
        if entry.get("id"):
            response = (
                client.table("bot_knowledge")
                .update(row)
                .eq("id", entry["id"])
                .eq("event_id", row["event_id"])
                .execute()
            )
        else:
            response = client.table("bot_knowledge").insert(row).execute()
        self._knowledge_cache = None
        if not response.data:
            raise RuntimeError("Supabase não retornou a pergunta salva")
        return response.data[0]

    def delete_knowledge(self, entry_id: str) -> bool:
        """Remove uma pergunta da base."""

        response = (
            self._get_client()
            .table("bot_knowledge")
            .delete()
            .eq("id", entry_id)
            .eq("event_id", self.event_id())
            .execute()
        )
        self._knowledge_cache = None
        return bool(response.data)

    def bot_settings(self) -> dict[str, Any]:
        """Tom de voz e boas-vindas configurados, com cache curto."""

        cache = getattr(self, "_settings_cache", None)
        now = datetime.now(timezone.utc)
        if cache and (now - cache["at"]).total_seconds() < self._KNOWLEDGE_TTL_SECONDS:
            return cache["row"]
        try:
            response = (
                self._get_client()
                .table("bot_settings")
                .select("persona,welcome")
                .eq("event_id", self.event_id())
                .limit(1)
                .execute()
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Falha ao ler ajustes do bot: %s", type(exc).__name__)
            return cache["row"] if cache else {}
        row = (response.data or [{}])[0]
        self._settings_cache = {"row": row, "at": now}
        return row

    def save_bot_settings(self, persona: str | None, welcome: str | None) -> dict[str, Any]:
        """Grava tom de voz e boas-vindas, uma linha por evento."""

        row = {
            "event_id": self.event_id(),
            "persona": (persona or "").strip()[:2000] or None,
            "welcome": (welcome or "").strip()[:1500] or None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        response = (
            self._get_client()
            .table("bot_settings")
            .upsert(row, on_conflict="event_id")
            .execute()
        )
        self._settings_cache = None
        return (response.data or [row])[0]

    # ------------------------------------------------------------------
    # Atendimento humano (handon / handoff)
    # ------------------------------------------------------------------

    def conversation_mode(self, sender_hash: str) -> str:
        """Diz se a conversa está no bot ou com um operador.

        Em qualquer falha devolve "bot": o pior cenário é o participante
        receber uma resposta automática, nunca ficar sem resposta.
        """

        if not sender_hash:
            return "bot"
        try:
            response = (
                self._get_client()
                .table("conversation_handoff")
                .select("mode")
                .eq("event_id", self.event_id())
                .eq("sender_hash", sender_hash)
                .limit(1)
                .execute()
            )
        except Exception as exc:  # noqa: BLE001 - indisponibilidade não pode calar o bot
            logger.error("Falha ao ler modo da conversa: %s", type(exc).__name__)
            return "bot"
        if not response.data:
            return "bot"
        return str(response.data[0].get("mode") or "bot")

    def set_conversation_mode(
        self,
        sender_hash: str,
        mode: str,
        operator: str | None = None,
    ) -> dict[str, Any]:
        """Assume (human) ou devolve ao bot, mantendo uma linha por conversa."""

        if mode not in {"bot", "human"}:
            raise ValueError("modo inválido")
        now = datetime.now(timezone.utc).isoformat()
        row = {
            "event_id": self.event_id(),
            "sender_hash": sender_hash,
            "mode": mode,
            "operator": (operator or None) if mode == "human" else None,
            "taken_at": now if mode == "human" else None,
            "released_at": now if mode == "bot" else None,
            "updated_at": now,
        }
        response = (
            self._get_client()
            .table("conversation_handoff")
            .upsert(row, on_conflict="event_id,sender_hash")
            .execute()
        )
        return (response.data or [row])[0]

    def conversation_modes(self) -> dict[str, str]:
        """Modo de todas as conversas que já saíram do padrão."""

        try:
            response = (
                self._get_client()
                .table("conversation_handoff")
                .select("sender_hash,mode,operator,taken_at")
                .eq("event_id", self.event_id())
                .execute()
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Falha ao listar modos: %s", type(exc).__name__)
            return {}
        return {
            str(row["sender_hash"]): str(row.get("mode") or "bot")
            for row in (response.data or [])
        }

    def sender_hash_for_feedback(self, feedback_id: int) -> str | None:
        """Resolve a conversa a partir de um chamado do dashboard."""

        response = (
            self._get_client()
            .table("feedbacks")
            .select("sender_hash")
            .eq("event_id", self.event_id())
            .eq("id", feedback_id)
            .limit(1)
            .execute()
        )
        if not response.data:
            return None
        return response.data[0].get("sender_hash")

    def conversation_thread(self, sender_hash: str, limit: int = 100) -> dict[str, Any]:
        """Monta a conversa nos dois sentidos, sem devolver o telefone.

        O painel precisa ver o que o participante mandou e o que já foi
        respondido, para o operador não repetir o que o bot acabou de dizer.
        """

        client = self._get_client()
        event_id = self.event_id()

        inbound = (
            client.table("message_inbox")
            .select("id,message_type,content,occurred_at,created_at,sender_name")
            .eq("event_id", event_id)
            .eq("sender_hash", sender_hash)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )

        # A caixa de saída não guarda o hash, então o vínculo é o telefone,
        # que fica só no servidor e nunca sai nesta resposta.
        recipient = self._recipient_for(sender_hash)
        outbound_rows: list[dict[str, Any]] = []
        if recipient:
            outbound = (
                client.table("outbound_messages")
                .select("id,content,origin,delivery_status,created_at,sent_at")
                .eq("event_id", event_id)
                .eq("recipient", recipient)
                .order("created_at", desc=True)
                .limit(limit)
                .execute()
            )
            outbound_rows = list(outbound.data or [])

        messages = [
            {
                "direction": "in",
                "content": row.get("content"),
                "type": row.get("message_type"),
                "at": row.get("occurred_at") or row.get("created_at"),
            }
            for row in (inbound.data or [])
        ] + [
            {
                "direction": "out",
                "content": row.get("content"),
                "origin": row.get("origin") or "bot",
                "status": row.get("delivery_status"),
                "at": row.get("sent_at") or row.get("created_at"),
            }
            for row in outbound_rows
        ]
        messages.sort(key=lambda m: m.get("at") or "")

        last_inbound = max(
            (m["at"] for m in messages if m["direction"] == "in" and m.get("at")),
            default=None,
        )
        return {
            "messages": messages,
            "mode": self.conversation_mode(sender_hash),
            "lastInboundAt": last_inbound,
            # Sem telefone conhecido nao existe para quem enviar. Acontece com
            # a massa de demonstracao, que nasce direto na tabela de feedbacks.
            "hasContact": recipient is not None,
            "canReply": self._within_service_window(last_inbound),
        }

    def _recipient_for(self, sender_hash: str) -> str | None:
        """Telefone do participante, usado só para enfileirar o envio."""

        response = (
            self._get_client()
            .table("message_inbox")
            .select("sender,channel_account_id")
            .eq("event_id", self.event_id())
            .eq("sender_hash", sender_hash)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if not response.data:
            return None
        return response.data[0].get("sender")

    @staticmethod
    def _within_service_window(last_inbound_at: str | None) -> bool:
        """A Meta só aceita texto livre até 24h após a última mensagem recebida."""

        if not last_inbound_at:
            return False
        try:
            moment = datetime.fromisoformat(str(last_inbound_at).replace("Z", "+00:00"))
        except ValueError:
            return False
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - moment < timedelta(hours=24)

    def enqueue_operator_message(self, sender_hash: str, content: str) -> bool:
        """Enfileira uma mensagem escrita no painel; o worker faz o envio."""

        response = (
            self._get_client()
            .table("message_inbox")
            .select("sender,channel_account_id")
            .eq("event_id", self.event_id())
            .eq("sender_hash", sender_hash)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if not response.data:
            return False
        contact = response.data[0]

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        row = {
            "event_id": self.event_id(),
            "provider": "meta",
            "channel_account_id": contact["channel_account_id"],
            "recipient": contact["sender"],
            "message_type": "text",
            "content": content[:4096],
            "origin": "operator",
            "idempotency_key": f"operator:{sender_hash[:24]}:{stamp}",
            "delivery_status": "queued",
        }
        self._get_client().table("outbound_messages").insert(row).execute()
        return True

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
