"""Persistência durável do pipeline de mensagens no Supabase."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from meta_whatsapp import IncomingMessage, MessageStatus, MetaAPIError

logger = logging.getLogger(__name__)

# Tipos de ficha da base: pergunta comum e as quatro do guia do evento.
KNOWLEDGE_KINDS = ("faq", "lineup", "food", "bar", "activation")


def _linha_de_erro(error: Exception) -> str:
    """Texto de falha para o painel: detalha o que é nosso e omite o resto.

    A mensagem de MetaAPIError é montada por nós e já sai sem token nem
    telefone, então pode ir para o banco. Exceção de terceiro pode carregar
    dado do participante no texto, e dessas guardamos só o tipo.
    """

    if isinstance(error, MetaAPIError):
        return f"MetaAPIError: {error}"
    return f"{type(error).__name__}: envio falhou"


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

    def table(self, name: str) -> Any:
        """Consulta direta a uma tabela, para leituras operacionais do monitor.

        O monitor do Telegram faz dezenas de leituras pequenas e diferentes;
        uma por método aqui viraria ruído. Ele usa isto e filtra por evento.
        """

        return self._get_client().table(name)

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
            # Falha relatada pela Meta DEPOIS do aceite e terminal: a mensagem
            # ja saiu, reenviar so geraria copia na conversa do participante.
            # Gravar "failed" aqui devolvia a linha para pending_outbox com o
            # next_attempt_at no passado, sem backoff e sem teto de tentativas,
            # e o worker reenviava em laco a cada segundo. "cancelled" fica
            # fora da fila e o painel ja o mostra como "nao entregue".
            estado = "cancelled" if status.status == "failed" else status.status
            updates: dict[str, Any] = {"delivery_status": estado}
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

    def recent_sender_count(self, sender_hash: str, minutes: int = 10) -> int:
        """Conta mensagens recentes para limitar abuso de forma compartilhada."""

        since = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
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

    def recent_sender_audio_count(self, sender_hash: str, minutes: int = 60) -> int:
        """Quantos áudios este número mandou na janela, inclusive o atual.

        Cada áudio custa transcrição; a cota por número é o que impede um
        celular só de gastar a conta do Whisper.
        """

        since = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
        response = (
            self._get_client()
            .table("message_inbox")
            .select("id", count="exact")
            .eq("event_id", self.event_id())
            .eq("sender_hash", sender_hash)
            .eq("message_type", "audio")
            .gte("created_at", since)
            .execute()
        )
        return int(response.count or 0)

    def recent_event_count(self, minutes: int = 1) -> int:
        """Mensagens de todos os números na janela: detecta inundação geral."""

        since = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
        response = (
            self._get_client()
            .table("message_inbox")
            .select("id", count="exact")
            .eq("event_id", self.event_id())
            .gte("created_at", since)
            .execute()
        )
        return int(response.count or 0)

    def block_inbox(self, message_id: str, reason: str) -> None:
        """Marca a mensagem como bloqueada, guardando o motivo.

        O schema só aceita os estados existentes, então o bloqueio é um
        "ignored" com o motivo em last_error. É por esse prefixo que os
        strikes de um número são contados.
        """

        self._get_client().table("message_inbox").update({
            "processing_status": "ignored",
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "last_error": f"bloqueado: {reason}"[:2000],
        }).eq("id", message_id).execute()

    def recent_blocked_count(self, sender_hash: str, minutes: int = 10) -> int:
        """Quantas mensagens deste número foram bloqueadas por conteúdo na janela."""

        since = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
        response = (
            self._get_client()
            .table("message_inbox")
            .select("id", count="exact")
            .eq("event_id", self.event_id())
            .eq("sender_hash", sender_hash)
            .like("last_error", "bloqueado: conteudo%")
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

    def marcar_setor_do_inbox(self, message_id: str, sector_id: str) -> None:
        """Guarda na mensagem o setor que veio na etiqueta do QR.

        A mensagem que carrega `#SETOR:CODIGO` costuma ser só a etiqueta: a
        pessoa escaneia a placa, o WhatsApp abre com o texto pronto e ela
        envia. Essa mensagem vira cumprimento e não abre chamado, então o setor
        morria ali. Guardado aqui, ele ainda serve para as mensagens seguintes,
        que é onde o relato de verdade chega.
        """

        if not message_id or not sector_id:
            return
        (
            self._get_client()
            .table("message_inbox")
            .update({"sector_id": sector_id})
            .eq("id", message_id)
            .execute()
        )

    def ultimo_setor_escaneado(
        self, sender_hash: str, janela_minutos: int = 30
    ) -> dict[str, Any] | None:
        """A última placa que esta pessoa escaneou, se foi há pouco.

        A janela é curta de propósito: no festival as pessoas andam, e setor
        velho manda a equipe para onde alguém esteve, não para onde está. Sem
        nada na janela devolve None, e o chamado segue sem lugar, que é melhor
        que lugar errado.
        """

        if not sender_hash:
            return None
        desde = (
            datetime.now(timezone.utc) - timedelta(minutes=janela_minutos)
        ).isoformat()
        response = (
            self._get_client()
            .table("message_inbox")
            .select("sector_id")
            .eq("event_id", self.event_id())
            .eq("sender_hash", sender_hash)
            .not_.is_("sector_id", "null")
            .gte("created_at", desde)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        linhas = list(response.data or [])
        if not linhas:
            return None
        return self.sector_by_id(str(linhas[0]["sector_id"]))

    def sector_by_id(self, sector_id: str | None) -> dict[str, Any] | None:
        """Setor ativo pelo id, para resolver o que ficou guardado na mensagem."""

        if not sector_id:
            return None
        response = (
            self._get_client()
            .table("event_sectors")
            .select("id,code,name,metadata")
            .eq("event_id", self.event_id())
            .eq("id", sector_id)
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
        sector_source: str | None = None,
        place_group: str | None = None,
    ) -> int:
        """Cria um feedback 1:1 com a mensagem para manter rastreabilidade.

        `sector_source` diz de onde veio o setor: "qr" quando a pessoa
        escaneou a placa, "ia" ou "texto" quando ele foi deduzido do que ela
        escreveu. A sala de controle precisa saber a diferença antes de mandar
        equipe: pino lido é fato, pino deduzido é palpite bom.
        """

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
        extra = {}
        if sector_source:
            extra["sector_source"] = sector_source
        # Tipo de lugar de quem não tem setor: é o que mantém a reclamação na
        # conta do relatório mesmo sem pino no mapa.
        if place_group:
            extra["place_group"] = place_group
        if extra:
            row["metadata"] = extra
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

    def attach_location(
        self,
        sender_hash: str,
        lat: float,
        lon: float,
        janela_minutos: int = 60,
    ) -> dict[str, Any] | None:
        """Prende a coordenada ao chamado em aberto mais recente da pessoa.

        A localização chega depois de o Tuca pedir, e sozinha não diz nada:
        quem dá sentido a ela é o relato que veio antes. Por isso ela não abre
        chamado próprio, ela completa um. Sem chamado recente, devolve None
        para o worker perguntar o que está acontecendo.
        """

        if not sender_hash:
            return None
        desde = (
            datetime.now(timezone.utc) - timedelta(minutes=janela_minutos)
        ).isoformat()
        client = self._get_client()
        response = (
            client.table("feedbacks")
            .select("id,message,urgency,status,metadata")
            .eq("event_id", self.event_id())
            .eq("sender_hash", sender_hash)
            .neq("status", "resolvido")
            .gte("created_at", desde)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        linhas = list(response.data or [])
        if not linhas:
            return None

        alvo = linhas[0]
        agora = datetime.now(timezone.utc).isoformat()
        metadata = dict(alvo.get("metadata") or {})
        metadata["coords"] = {"lat": lat, "lon": lon}
        metadata["coords_at"] = agora
        (
            client.table("feedbacks")
            .update({"metadata": metadata, "updated_at": agora})
            .eq("id", alvo["id"])
            .execute()
        )
        return {
            "id": int(alvo["id"]),
            "urgency": alvo.get("urgency"),
            "message": alvo.get("message"),
        }

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

    def enqueue_image(
        self,
        message: dict[str, Any],
        media_url: str,
        caption: str,
        feedback_id: int | None = None,
    ) -> None:
        """Enfileira um banner (imagem pública) para ir depois da resposta em texto.

        Chave própria de idempotência: a resposta em texto usa `:reply`, e o
        banner não pode derrubá-la nem ser derrubado por ela.
        """

        row = {
            "event_id": self.event_id(),
            "feedback_id": feedback_id,
            "provider": "meta",
            "channel_account_id": message["channel_account_id"],
            "recipient": message["sender"],
            "message_type": "image",
            "content": (caption or "")[:1024],
            "media_url": media_url[:500],
            "idempotency_key": f"inbox:{message['id']}:banner",
            "delivery_status": "queued",
        }
        (
            self._get_client()
            .table("outbound_messages")
            .upsert(row, on_conflict="idempotency_key", ignore_duplicates=True)
            .execute()
        )

    def upload_banner(self, content: bytes, mime_type: str) -> str:
        """Sobe um banner para o bucket público e devolve a URL que a Meta vai buscar."""

        import secrets

        extensao = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[mime_type]
        nome = (
            f"{self.event_id()}/"
            f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(4)}.{extensao}"
        )
        storage = self._get_client().storage.from_("banners")
        storage.upload(nome, content, {"content-type": mime_type})
        return str(storage.get_public_url(nome)).split("?")[0]

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

    def live_config(self) -> dict[str, Any]:
        """A versão publicada, que é a única que o bot enxerga.

        O worker roda em outro processo, então o cache de 30s é também o tempo
        máximo entre alguém publicar e o WhatsApp responder com o conteúdo novo.
        """

        cache = getattr(self, "_live_cache", None)
        now = datetime.now(timezone.utc)
        if cache and (now - cache["at"]).total_seconds() < self._KNOWLEDGE_TTL_SECONDS:
            return cache["payload"]

        try:
            response = (
                self._get_client()
                .table("bot_config_version")
                .select("payload")
                .eq("event_id", self.event_id())
                .eq("is_live", True)
                .limit(1)
                .execute()
            )
        except Exception as exc:  # noqa: BLE001 - base indisponível não cala o bot
            logger.error("Falha ao ler versão publicada: %s", type(exc).__name__)
            return cache["payload"] if cache else self._fallback_para_rascunho()

        rows = response.data or []
        if not rows:
            # Sem versão no ar o bot ficaria sem base nenhuma e responderia
            # genérico sem ninguém perceber. Num festival isso é pior que
            # publicar sem revisão, então o rascunho assume.
            logger.warning("Nenhuma versão publicada: o bot vai usar o rascunho")
            payload = self._fallback_para_rascunho()
        else:
            payload = dict(rows[0].get("payload") or {})
        self._live_cache = {"payload": payload, "at": now}
        return payload

    def _fallback_para_rascunho(self) -> dict[str, Any]:
        """Último recurso: o cadastro cru, quando não há versão publicada legível."""

        try:
            return self.draft_payload()
        except Exception as exc:  # noqa: BLE001
            logger.error("Rascunho também indisponível: %s", type(exc).__name__)
            return {}

    def knowledge(self, only_active: bool = True) -> list[dict[str, Any]]:
        """Perguntas e respostas no ar, da maior para a menor prioridade.

        Lê da versão publicada: o que está em rascunho não chega no participante
        enquanto ninguém apertar Publicar.
        """

        entries = list(self.live_config().get("knowledge") or [])
        if only_active:
            entries = [e for e in entries if e.get("active", True)]
        return entries

    def rules(self) -> list[dict[str, Any]]:
        """Regras de negócio no ar, da maior para a menor prioridade."""

        entries = list(self.live_config().get("rules") or [])
        return [e for e in entries if e.get("active", True)]

    def draft_knowledge(self) -> list[dict[str, Any]]:
        """Perguntas como estão no cadastro, publicadas ou não. Só o painel usa."""

        try:
            response = (
                self._get_client()
                .table("bot_knowledge")
                .select("id,question,answer,keywords,priority,active,kind,scope,image_url")
                .eq("event_id", self.event_id())
                .order("priority", desc=True)
                .execute()
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Falha ao ler rascunho da base: %s", type(exc).__name__)
            return []
        return list(response.data or [])

    def save_knowledge(self, entry: dict[str, Any]) -> dict[str, Any]:
        """Cria ou atualiza uma pergunta e resposta, ou uma ficha do guia."""

        kind = str(entry.get("kind") or "faq").strip().lower()
        if kind not in KNOWLEDGE_KINDS:
            kind = "faq"
        row = {
            "event_id": self.event_id(),
            "question": str(entry.get("question") or "").strip()[:300],
            "answer": str(entry.get("answer") or "").strip()[:4000],
            "keywords": [
                str(k).strip().lower()[:80]
                for k in (entry.get("keywords") or [])
                if str(k).strip()
            ][:30],
            "priority": max(0, min(100, int(entry.get("priority") or 0))),
            "active": bool(entry.get("active", True)),
            "kind": kind,
            "scope": (str(entry.get("scope") or "").strip()[:120] or None),
            "image_url": (str(entry.get("image_url") or "").strip()[:500] or None),
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
        return bool(response.data)

    def bot_settings(self) -> dict[str, Any]:
        """Tom de voz, boas-vindas e link do app que estão no ar."""

        return dict(self.live_config().get("settings") or {})

    def draft_settings(self) -> dict[str, Any]:
        """Ajustes como estão no cadastro. Só o painel usa."""

        try:
            response = (
                self._get_client()
                .table("bot_settings")
                .select("persona,welcome,app_url")
                .eq("event_id", self.event_id())
                .limit(1)
                .execute()
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Falha ao ler rascunho dos ajustes: %s", type(exc).__name__)
            return {}
        row = (response.data or [{}])[0]
        # O painel e a versão publicada falam appUrl; só a coluna é app_url.
        return {
            "persona": row.get("persona"),
            "welcome": row.get("welcome"),
            "appUrl": row.get("app_url"),
        }

    def save_bot_settings(
        self,
        persona: str | None,
        welcome: str | None,
        app_url: str | None = None,
    ) -> dict[str, Any]:
        """Grava tom de voz, boas-vindas e link do app, uma linha por evento."""

        row = {
            "event_id": self.event_id(),
            "persona": (persona or "").strip()[:2000] or None,
            "welcome": (welcome or "").strip()[:1500] or None,
            "app_url": (app_url or "").strip()[:300] or None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        response = (
            self._get_client()
            .table("bot_settings")
            .upsert(row, on_conflict="event_id")
            .execute()
        )
        return (response.data or [row])[0]

    # ------------------------------------------------------------------
    # Regras de negócio (rascunho)
    # ------------------------------------------------------------------

    def draft_rules(self) -> list[dict[str, Any]]:
        """Regras como estão no cadastro, ligadas ou não."""

        try:
            response = (
                self._get_client()
                .table("bot_rules")
                .select("id,title,body,priority,active")
                .eq("event_id", self.event_id())
                .order("priority", desc=True)
                .execute()
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Falha ao ler rascunho das regras: %s", type(exc).__name__)
            return []
        return list(response.data or [])

    def save_rule(self, entry: dict[str, Any]) -> dict[str, Any]:
        """Cria ou atualiza uma regra de negócio."""

        row = {
            "event_id": self.event_id(),
            "title": str(entry.get("title") or "").strip()[:120],
            "body": str(entry.get("body") or "").strip()[:1000],
            "priority": max(0, min(100, int(entry.get("priority") or 50))),
            "active": bool(entry.get("active", True)),
        }
        client = self._get_client()
        if entry.get("id"):
            response = (
                client.table("bot_rules")
                .update(row)
                .eq("id", entry["id"])
                .eq("event_id", row["event_id"])
                .execute()
            )
        else:
            response = client.table("bot_rules").insert(row).execute()
        if not response.data:
            raise RuntimeError("Supabase não retornou a regra salva")
        return response.data[0]

    def delete_rule(self, rule_id: str) -> bool:
        """Remove uma regra do cadastro."""

        response = (
            self._get_client()
            .table("bot_rules")
            .delete()
            .eq("id", rule_id)
            .eq("event_id", self.event_id())
            .execute()
        )
        return bool(response.data)

    # ------------------------------------------------------------------
    # Publicação
    # ------------------------------------------------------------------

    def draft_payload(self) -> dict[str, Any]:
        """Monta a fotografia do rascunho, no mesmo formato da versão no ar."""

        return {
            "knowledge": [e for e in self.draft_knowledge() if e.get("active", True)],
            "rules": [r for r in self.draft_rules() if r.get("active", True)],
            "settings": self.draft_settings(),
        }

    @staticmethod
    def _comparable(payload: dict[str, Any]) -> str:
        """Texto estável de um payload, para comparar rascunho com o que está no ar."""

        def limpa(itens: Any) -> list[dict[str, Any]]:
            saida = []
            for item in itens or []:
                saida.append({k: v for k, v in sorted(item.items()) if k != "id"})
            return sorted(saida, key=lambda d: json.dumps(d, sort_keys=True, ensure_ascii=False))

        settings = payload.get("settings") or {}
        return json.dumps(
            {
                "knowledge": limpa(payload.get("knowledge")),
                "rules": limpa(payload.get("rules")),
                "settings": {
                    "persona": settings.get("persona") or "",
                    "welcome": settings.get("welcome") or "",
                    "appUrl": settings.get("appUrl") or "",
                },
            },
            sort_keys=True,
            ensure_ascii=False,
        )

    def has_unpublished_changes(self) -> bool:
        """Diz se o rascunho difere do que está no ar."""

        try:
            return self._comparable(self.draft_payload()) != self._comparable(self.live_config())
        except Exception as exc:  # noqa: BLE001 - dúvida não trava o painel
            logger.error("Falha ao comparar rascunho: %s", type(exc).__name__)
            return False

    def publish_config(self, author: str | None = None, note: str | None = None) -> dict[str, Any]:
        """Tira a fotografia do rascunho e coloca no ar.

        Desmarca a versão anterior antes de inserir a nova, porque o índice
        único parcial só admite uma linha com is_live por evento.
        """

        payload = self.draft_payload()
        client = self._get_client()
        event_id = self.event_id()

        client.table("bot_config_version").update({"is_live": False}).eq(
            "event_id", event_id
        ).eq("is_live", True).execute()

        response = (
            client.table("bot_config_version")
            .insert({
                "event_id": event_id,
                "payload": payload,
                "author": (author or "").strip()[:80] or None,
                "note": (note or "").strip()[:200] or None,
                "is_live": True,
            })
            .execute()
        )
        self._live_cache = None
        if not response.data:
            raise RuntimeError("Supabase não retornou a versão publicada")
        return response.data[0]

    def config_versions(self, limit: int = 20) -> list[dict[str, Any]]:
        """Histórico de publicações, da mais recente para a mais antiga."""

        try:
            response = (
                self._get_client()
                .table("bot_config_version")
                .select("id,author,note,is_live,created_at,payload")
                .eq("event_id", self.event_id())
                .order("created_at", desc=True)
                .limit(max(1, min(50, int(limit))))
                .execute()
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Falha ao ler histórico: %s", type(exc).__name__)
            return []

        versoes = []
        for row in response.data or []:
            payload = row.get("payload") or {}
            versoes.append({
                "id": row.get("id"),
                "author": row.get("author"),
                "note": row.get("note"),
                "isLive": bool(row.get("is_live")),
                "createdAt": row.get("created_at"),
                "perguntas": len(payload.get("knowledge") or []),
                "regras": len(payload.get("rules") or []),
            })
        return versoes

    def restore_version(self, version_id: str, author: str | None = None) -> dict[str, Any]:
        """Volta uma versão antiga para o ar e devolve o rascunho ao mesmo estado.

        Restaurar sem mexer no rascunho deixaria o painel mostrando uma coisa e
        o participante recebendo outra, que é exatamente a confusão que esse
        fluxo existe para evitar.
        """

        client = self._get_client()
        event_id = self.event_id()

        alvo = (
            client.table("bot_config_version")
            .select("payload")
            .eq("id", version_id)
            .eq("event_id", event_id)
            .limit(1)
            .execute()
        )
        if not alvo.data:
            raise LookupError("versão não encontrada")
        payload = dict(alvo.data[0].get("payload") or {})

        # Rascunho volta a espelhar a versão restaurada.
        client.table("bot_knowledge").delete().eq("event_id", event_id).execute()
        perguntas = [
            {
                "event_id": event_id,
                "question": e.get("question"),
                "answer": e.get("answer"),
                "keywords": e.get("keywords") or [],
                "priority": e.get("priority") or 0,
                "active": e.get("active", True),
                "kind": e.get("kind") if e.get("kind") in KNOWLEDGE_KINDS else "faq",
                "scope": e.get("scope") or None,
                "image_url": e.get("image_url") or None,
            }
            for e in (payload.get("knowledge") or [])
            if e.get("question") and e.get("answer")
        ]
        if perguntas:
            client.table("bot_knowledge").insert(perguntas).execute()

        client.table("bot_rules").delete().eq("event_id", event_id).execute()
        regras = [
            {
                "event_id": event_id,
                "title": r.get("title"),
                "body": r.get("body"),
                "priority": r.get("priority") or 50,
                "active": r.get("active", True),
            }
            for r in (payload.get("rules") or [])
            if r.get("title") and r.get("body")
        ]
        if regras:
            client.table("bot_rules").insert(regras).execute()

        settings = payload.get("settings") or {}
        self.save_bot_settings(
            settings.get("persona"),
            settings.get("welcome"),
            settings.get("appUrl"),
        )

        return self.publish_config(author=author, note="Versão restaurada do histórico")

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
            "last_error": _linha_de_erro(error)[:2000],
            "failed_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", message["id"]).execute()
