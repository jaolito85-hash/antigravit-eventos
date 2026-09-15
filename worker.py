"""Worker único para processar a caixa de entrada e enviar respostas."""

from __future__ import annotations

import logging
import os
import re
import signal
import time
from typing import Any

from event_store import EventStore
from meta_whatsapp import MetaWhatsAppClient
from server import (
    classificar_categoria,
    classificar_regiao,
    classificar_sentimento,
    is_emoji_only,
)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
# O polling é frequente; registrar cada requisição HTTP duplicaria centenas de
# milhares de linhas por dia sem acrescentar informação operacional útil.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("worker")

SECTOR_PATTERN = re.compile(
    r"^\s*#SETOR:([A-Z0-9][A-Z0-9_-]{0,49})\s*(?:\r?\n|\|)?\s*",
    flags=re.IGNORECASE,
)
_running = True


def _stop(_signum: int, _frame: Any) -> None:
    """Solicita encerramento limpo ao receber SIGTERM do Coolify."""

    global _running
    _running = False


def _extract_sector(content: str) -> tuple[str | None, str]:
    """Extrai o código do QR e devolve somente a mensagem do participante."""

    match = SECTOR_PATTERN.match(content)
    if not match:
        return None, content.strip()
    return match.group(1).upper(), content[match.end():].strip()


def _topic(content: str, category: str, urgency: str) -> str:
    """Gera um rótulo curto e determinístico para o dashboard."""

    lowered = content.lower()
    if "banheiro" in lowered:
        return "Banheiro Sujo" if urgency == "Urgente" else "Banheiro"
    if "fila" in lowered:
        return "Fila"
    if "show" in lowered or "palco" in lowered:
        return "Show"
    if "comida" in lowered or "bebida" in lowered:
        return "Alimentação"
    return category if category != "Experiência Geral" else content[:80]


def _reply(urgency: str) -> str:
    """Responde sem prometer uma ação humana que ainda não foi confirmada."""

    if urgency == "Critico":
        return (
            "🚨 Recebemos seu alerta e ele foi marcado como prioridade máxima. "
            "Se houver risco imediato, procure agora a segurança ou equipe médica mais próxima."
        )
    if urgency == "Urgente":
        return "⚠️ Recebemos e destacamos sua mensagem para a equipe do evento. Obrigado por avisar!"
    if urgency == "Positivo":
        return "🎉 Que bom receber isso! Obrigado pelo feedback e aproveite o evento!"
    return "✅ Mensagem recebida! Obrigado por ajudar a melhorar sua experiência no evento."


def process_inbox(store: EventStore, message: dict[str, Any]) -> None:
    """Transforma uma mensagem persistida em feedback e resposta enfileirada."""

    if not store.claim_inbox(message):
        return
    try:
        if store.recent_sender_count(str(message.get("sender_hash") or "")) > 3:
            store.enqueue_text(
                message,
                "Você já enviou várias mensagens recentes. Aguarde alguns minutos antes de tentar novamente.",
            )
            store.finish_inbox(str(message["id"]), "ignored")
            return

        if message.get("message_type") != "text":
            store.enqueue_text(
                message,
                "Por enquanto, envie sua mensagem em texto para conseguirmos encaminhá-la corretamente.",
            )
            store.finish_inbox(str(message["id"]), "ignored")
            return

        raw_content = str(message.get("content") or "")
        sector_code, content = _extract_sector(raw_content)
        if len(content) < 3 or is_emoji_only(content):
            store.enqueue_text(
                message,
                "Conte em poucas palavras o que aconteceu ou o que podemos melhorar.",
            )
            store.finish_inbox(str(message["id"]), "ignored")
            return

        sector = store.sector_by_code(sector_code)
        urgency = classificar_sentimento(content)
        category = classificar_categoria(content)
        region = str(sector["name"]) if sector else classificar_regiao(content)
        feedback_id = store.create_feedback(
            message=message,
            content=content,
            category=category,
            region=region,
            urgency=urgency,
            topic=_topic(content, category, urgency),
            sector_id=str(sector["id"]) if sector else None,
        )
        store.enqueue_text(message, _reply(urgency), feedback_id)
        store.finish_inbox(str(message["id"]))
        logger.info("Mensagem processada com sucesso | prioridade=%s", urgency)
    except Exception as exc:  # noqa: BLE001 - failed jobs must be persisted for retry
        logger.error("Falha ao processar mensagem | erro=%s", type(exc).__name__)
        store.fail_inbox(message, exc)


def process_outbox(
    store: EventStore,
    client: MetaWhatsAppClient,
    message: dict[str, Any],
) -> None:
    """Envia uma resposta reivindicada e registra aceite ou nova tentativa."""

    if not store.claim_outbox(message):
        return
    try:
        provider_message_id = client.send_text(
            str(message["recipient"]),
            str(message["content"]),
        )
        store.mark_outbox_sent(str(message["id"]), provider_message_id)
        logger.info("Resposta aceita pela Meta")
    except Exception as exc:  # noqa: BLE001 - provider failures must enter the outbox retry
        logger.error("Falha ao enviar resposta | erro=%s", type(exc).__name__)
        store.fail_outbox(message, exc)


def run() -> None:
    """Executa o ciclo do worker até receber sinal de encerramento."""

    store = EventStore()
    client = MetaWhatsAppClient(
        access_token=os.getenv("META_ACCESS_TOKEN", ""),
        phone_number_id=os.getenv("META_PHONE_NUMBER_ID", ""),
        graph_api_version=os.getenv("META_GRAPH_API_VERSION", ""),
    )
    poll_interval = max(0.5, float(os.getenv("WORKER_POLL_INTERVAL", "1")))
    if not store.healthcheck():
        raise RuntimeError("Worker não conseguiu acessar o evento no Supabase")

    logger.info("Worker iniciado")
    while _running:
        worked = False
        try:
            for inbox_message in store.pending_inbox():
                worked = True
                process_inbox(store, inbox_message)
            for outbound_message in store.pending_outbox():
                worked = True
                process_outbox(store, client, outbound_message)
        except Exception as exc:  # noqa: BLE001 - worker loop must survive external outages
            logger.error("Falha no ciclo do worker | erro=%s", type(exc).__name__)
            time.sleep(min(10, poll_interval * 4))
            continue
        if not worked:
            time.sleep(poll_interval)

    logger.info("Worker encerrado")


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    run()
