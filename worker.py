"""Worker único para processar a caixa de entrada e enviar respostas."""

from __future__ import annotations

import logging
import os
import signal
import time
from typing import Any

from event_store import EventStore
from meta_whatsapp import MetaWhatsAppClient, download_media, graph_api_version
# O comportamento do bot vive no server para o simulador do painel usar
# exatamente a mesma decisao que o WhatsApp recebe.
from server import (
    _classify,
    _compose_reply,
    _extract_sector,
    _sector_prompt,
    _topic,
    compose_smalltalk,
    is_emoji_only,
    transcribe_audio,
    triar_mensagem,
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

_running = True


def _stop(_signum: int, _frame: Any) -> None:
    """Solicita encerramento limpo ao receber SIGTERM do Coolify."""

    global _running
    _running = False


def _transcribe_inbox_audio(message: dict[str, Any]) -> str | None:
    """Baixa o áudio da Meta e transcreve com Whisper; None se indisponível."""

    media_id = message.get("media_id")
    if not media_id:
        return None
    audio = download_media(
        str(media_id),
        os.getenv("META_ACCESS_TOKEN", ""),
        graph_api_version(),
    )
    if not audio:
        return None
    try:
        return transcribe_audio(audio)
    except Exception as exc:  # noqa: BLE001 - transcrição nunca pode derrubar o worker
        logger.error("Falha na transcrição | erro=%s", type(exc).__name__)
        return None


def process_inbox(store: EventStore, message: dict[str, Any]) -> None:
    """Transforma uma mensagem persistida em feedback e resposta enfileirada."""

    if not store.claim_inbox(message):
        return
    try:
        sender_hash = str(message.get("sender_hash") or "")
        # Operador no comando: o chamado ainda entra no dashboard, mas quem
        # fala com o participante e a pessoa, nao o bot.
        atendimento_humano = store.conversation_mode(sender_hash) == "human"

        if not atendimento_humano and store.recent_sender_count(sender_hash) > 3:
            if not atendimento_humano:
                store.enqueue_text(
                    message,
                    "Você já enviou várias mensagens recentes. Aguarde alguns minutos antes de tentar novamente.",
                )
            store.finish_inbox(str(message["id"]), "ignored")
            return

        message_type = message.get("message_type")
        raw_content = str(message.get("content") or "")
        transcribed = False

        if message_type == "audio":
            transcript = _transcribe_inbox_audio(message)
            if transcript:
                raw_content = transcript
                transcribed = True
            else:
                if not atendimento_humano:
                    store.enqueue_text(
                        message,
                        "🎤 Não consegui entender seu áudio agora. "
                        "Pode tentar de novo ou escrever em texto?",
                    )
                store.finish_inbox(str(message["id"]), "ignored")
                return
        elif message_type != "text":
            if not atendimento_humano:
                store.enqueue_text(
                    message,
                    "Por enquanto, envie sua mensagem em texto ou áudio 🎤 para conseguirmos encaminhá-la corretamente.",
                )
            store.finish_inbox(str(message["id"]), "ignored")
            return

        sector_code, content = _extract_sector(raw_content)
        sector = store.sector_by_code(sector_code)
        # QR com codigo que nao existe no banco nao pode passar silencioso: a
        # regiao cairia na adivinhacao da IA em vez do setor do cartaz.
        if sector_code and not sector:
            logger.warning(
                "QR com setor desconhecido | code=%s (cartaz com codigo errado?)",
                sector_code,
            )

        # A IA decide se isso e conversa ou relato; a lista de palavras do
        # server so entra se ela estiver fora do ar.
        triagem = triar_mensagem(content)

        if triagem["tipo"] == "conversa":
            resposta = compose_smalltalk(content)
            if sector:
                resposta += f"\n\n{_sector_prompt(sector)}"
            if not atendimento_humano:
                store.enqueue_text(message, resposta)
            store.finish_inbox(str(message["id"]), "ignored")
            logger.info("Conversa respondida sem abrir chamado")
            return

        if len(content) < 3 or is_emoji_only(content):
            if not atendimento_humano:
                store.enqueue_text(message, _sector_prompt(sector))
            store.finish_inbox(str(message["id"]), "ignored")
            return

        urgency, category, region = _classify(
            content, sector, urgency=triagem["urgencia"]
        )
        feedback_id = store.create_feedback(
            message=message,
            content=content,
            category=category,
            region=region,
            urgency=urgency,
            topic=_topic(content, category, urgency),
            sector_id=str(sector["id"]) if sector else None,
        )
        if not atendimento_humano:
            store.enqueue_text(
                message,
                _compose_reply(content, category, urgency, sector, transcribed),
                feedback_id,
            )
        store.finish_inbox(str(message["id"]))
        if atendimento_humano:
            logger.info(
                "Chamado registrado sem resposta automatica | prioridade=%s", urgency
            )
        else:
            logger.info(
                "Mensagem processada com sucesso | prioridade=%s", urgency
            )
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
        graph_api_version=graph_api_version(),
    )
    poll_interval = max(0.5, float(os.getenv("WORKER_POLL_INTERVAL", "1")))
    if not store.healthcheck():
        raise RuntimeError("Worker não conseguiu acessar o evento no Supabase")

    # Uma leitura do próprio número na Graph API: revela token vencido ou sem
    # permissão no start, em vez de só na primeira resposta que o público espera.
    logger.info("Credenciais da Meta | %s", client.check_credentials())

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
