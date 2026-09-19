"""Worker único para processar a caixa de entrada e enviar respostas."""

from __future__ import annotations

import logging
import os
import re
import signal
import time
from typing import Any

from event_store import EventStore
from meta_whatsapp import MetaWhatsAppClient, download_media
from server import (
    classificar_categoria,
    classificar_com_ia,
    classificar_regiao,
    classificar_urgencia,
    generate_ai_response,
    is_emoji_only,
    transcribe_audio,
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

# Saudações puras não viram card no dashboard: recebem as boas-vindas do bot.
GREETING_PATTERN = re.compile(
    r"^\s*(?:oi+e?|ol[aá]+|opa+|eae+|e\s*a[ií]|salve|fala+|hey+|hi+|hello+|hola+|"
    r"bom\s*dia|boa\s*tarde|boa\s*noite|good\s*(?:morning|evening|night)|"
    r"come[çc]ar|start|menu|ajuda|help)"
    r"[\s!.,?~^0-9]*$",
    flags=re.IGNORECASE,
)

WELCOME_MESSAGE = (
    "🌴🔥 Bem-vindo(a) ao *ChatBob*, o canal oficial da *Tropicadelia 2026*!\n\n"
    "Eu levo sua voz direto para a sala de controle do festival. "
    "Me manda *texto ou áudio* contando:\n"
    "🚻 um problema (fila, banheiro, som, limpeza...)\n"
    "🎶 um elogio para o show ou para a estrutura\n"
    "🎒 algo que você perdeu ou encontrou\n\n"
    "⚡ Sua mensagem chega *na hora* para a equipe certa.\n\n"
    "🔒 *Dica de ouro:* o ChatBob é 100% gratuito e *NUNCA* pede Pix, "
    "senha ou pagamento."
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


def _is_greeting(content: str) -> bool:
    """Detecta um cumprimento sem relato para responder com as boas-vindas."""

    return len(content) <= 40 and bool(GREETING_PATTERN.match(content))


def _sector_prompt(sector: dict[str, Any] | None) -> str:
    """Convida a pessoa a relatar algo usando o CTA cadastrado do setor."""

    if not sector:
        return "Conte em poucas palavras (ou num áudio 🎤) o que aconteceu ou o que podemos melhorar."
    metadata = sector.get("metadata") or {}
    cta = metadata.get("cta") or "Conte o que está acontecendo por aí."
    return f"📍 Você está em *{sector['name']}*!\n{cta}\nPode mandar texto ou áudio 🎤"


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


def _transcribe_inbox_audio(message: dict[str, Any]) -> str | None:
    """Baixa o áudio da Meta e transcreve com Whisper; None se indisponível."""

    media_id = message.get("media_id")
    if not media_id:
        return None
    audio = download_media(
        str(media_id),
        os.getenv("META_ACCESS_TOKEN", ""),
        os.getenv("META_GRAPH_API_VERSION", ""),
    )
    if not audio:
        return None
    try:
        return transcribe_audio(audio)
    except Exception as exc:  # noqa: BLE001 - transcrição nunca pode derrubar o worker
        logger.error("Falha na transcrição | erro=%s", type(exc).__name__)
        return None


def _classify(content: str, sector: dict[str, Any] | None) -> tuple[str, str, str]:
    """Classifica urgência, categoria e região com IA e fallback determinístico."""

    # classificar_urgencia ja tenta a IA e cai em palavras-chave se ela falhar.
    urgency = classificar_urgencia(content)

    category = classificar_categoria(content)
    region = str(sector["name"]) if sector else classificar_regiao(content)

    # Categoria ambígua: a IA tenta enriquecer sem substituir o setor do QR.
    if category == "Experiência Geral":
        try:
            enriched = classificar_com_ia(content)
        except Exception:  # noqa: BLE001
            enriched = None
        if enriched:
            category = enriched.get("categoria") or category
            if not sector and enriched.get("regiao") not in (None, "N/A"):
                region = enriched["regiao"]

    return urgency, category, region


def _compose_reply(
    content: str,
    category: str,
    urgency: str,
    sector: dict[str, Any] | None,
    transcribed: bool,
) -> str:
    """Monta a resposta: crítico é sempre o protocolo fixo, o resto ganha IA."""

    prefix = "🎤 *Ouvi seu áudio!*\n\n" if transcribed else ""
    if urgency == "Critico":
        return prefix + _reply(urgency)
    try:
        sector_name = str(sector["name"]) if sector else None
        reply = generate_ai_response(content, category, urgency, sector_name)
        if reply:
            return prefix + reply
    except Exception as exc:  # noqa: BLE001 - resposta criativa é opcional
        logger.error("IA de resposta indisponível | erro=%s", type(exc).__name__)
    return prefix + _reply(urgency)


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

        if _is_greeting(content):
            welcome = WELCOME_MESSAGE
            if sector:
                welcome += f"\n\n{_sector_prompt(sector)}"
            if not atendimento_humano:
                store.enqueue_text(message, welcome)
            store.finish_inbox(str(message["id"]), "ignored")
            return

        if len(content) < 3 or is_emoji_only(content):
            if not atendimento_humano:
                store.enqueue_text(message, _sector_prompt(sector))
            store.finish_inbox(str(message["id"]), "ignored")
            return

        urgency, category, region = _classify(content, sector)
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
