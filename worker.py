"""Worker único para processar a caixa de entrada e enviar respostas."""

from __future__ import annotations

import logging
import os
import signal
import time
from typing import Any

from event_store import EventStore
from meta_whatsapp import MetaWhatsAppClient, fetch_media, graph_api_version
from protecao import (
    AUDIO_JANELA_MINUTOS,
    AUDIO_MAX_BYTES,
    AUDIO_MAX_POR_JANELA,
    AUDIO_MAX_SEGUNDOS,
    AVISO_AUDIO_GRANDE,
    AVISO_AUDIO_LONGO,
    AVISO_CONTEUDO_BLOQUEADO,
    AVISO_COTA_AUDIO,
    AVISO_OFENSA,
    AVISO_SEM_FALA,
    AVISO_SILENCIADO,
    FLOOD_GLOBAL_POR_MINUTO,
    JANELA_MINUTOS,
    STRIKES_PARA_SILENCIAR,
    degrau_do_remetente,
    duracao_ogg_opus,
    moderar_texto,
)
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
    triar_mensagem_sem_ia,
    welcome_text,
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

# Tipos que o bot sabe o que fazer. Reação, figurinha e o que a Meta chama de
# "unsupported" ficam de fora: responder "mande texto ou áudio" a quem só
# reagiu com um joinha era bronca sem motivo e mais um envio por mensagem.
TIPOS_COM_RESPOSTA = frozenset({
    "text", "audio", "image", "video", "document", "location", "interactive",
})
TIPOS_DE_MIDIA = frozenset({"image", "video", "document", "location", "interactive"})

AVISO_AUDIO_INDISPONIVEL = (
    "🎤 Não consegui entender seu áudio agora. Pode tentar de novo ou escrever em texto?"
)
AVISO_SO_TEXTO_OU_AUDIO = (
    "Por enquanto, envie sua mensagem em texto ou áudio 🎤 para conseguirmos "
    "encaminhá-la corretamente."
)


def _stop(_signum: int, _frame: Any) -> None:
    """Solicita encerramento limpo ao receber SIGTERM do Coolify."""

    global _running
    _running = False


def _transcribe_inbox_audio(message: dict[str, Any]) -> dict[str, Any]:
    """Baixa o áudio da Meta e transcreve com Whisper.

    Devolve {"texto": str | None, "motivo": str | None}. O motivo, quando
    existe, é o que o participante precisa ouvir: "muito_grande",
    "muito_longo", "sem_fala" ou "indisponivel". A duração é medida no
    próprio arquivo antes de pagar a transcrição; o Whisper só confirma.
    """

    media_id = message.get("media_id")
    if not media_id:
        return {"texto": None, "motivo": "indisponivel"}
    media = fetch_media(
        str(media_id),
        os.getenv("META_ACCESS_TOKEN", ""),
        graph_api_version(),
        max_bytes=AUDIO_MAX_BYTES,
    )
    if media.status == "muito_grande":
        return {"texto": None, "motivo": "muito_grande"}
    if not media.content:
        return {"texto": None, "motivo": "indisponivel"}

    duracao = duracao_ogg_opus(media.content)
    if duracao is not None and duracao > AUDIO_MAX_SEGUNDOS:
        return {"texto": None, "motivo": "muito_longo"}

    try:
        resultado = transcribe_audio(media.content, media.mime_type)
    except Exception as exc:  # noqa: BLE001 - transcrição nunca pode derrubar o worker
        logger.error("Falha na transcrição | erro=%s", type(exc).__name__)
        return {"texto": None, "motivo": "indisponivel"}
    if not resultado:
        return {"texto": None, "motivo": "indisponivel"}
    # Formato que não é Ogg não tem a duração medida antes; o Whisper informa
    # e o limite vale do mesmo jeito, com 1s de folga para arredondamento.
    if (resultado.get("duracao") or 0) > AUDIO_MAX_SEGUNDOS + 1:
        return {"texto": None, "motivo": "muito_longo"}
    texto = (resultado.get("texto") or "").strip()
    if not texto:
        return {"texto": None, "motivo": "sem_fala"}
    return {"texto": texto, "motivo": None}


_AVISO_POR_MOTIVO = {
    "muito_grande": AVISO_AUDIO_GRANDE,
    "muito_longo": AVISO_AUDIO_LONGO,
    "sem_fala": AVISO_SEM_FALA,
    "indisponivel": AVISO_AUDIO_INDISPONIVEL,
}


def process_inbox(store: EventStore, message: dict[str, Any]) -> None:
    """Transforma uma mensagem persistida em feedback e resposta enfileirada.

    A ordem das barreiras importa e é a mesma do simulador: tipo, limite por
    número, cota de áudio, moderação, inundação geral e só então a triagem.
    Cada bloqueio explica o motivo ao participante uma única vez.
    """

    if not store.claim_inbox(message):
        return
    try:
        message_id = str(message["id"])
        sender_hash = str(message.get("sender_hash") or "")
        message_type = message.get("message_type")

        # 1. Reação, figurinha e tipo desconhecido: nada a fazer, nada a dizer.
        if message_type not in TIPOS_COM_RESPOSTA:
            store.finish_inbox(message_id, "ignored")
            return

        # Operador no comando: o chamado ainda entra no dashboard, mas quem
        # fala com o participante e a pessoa, nao o bot.
        atendimento_humano = store.conversation_mode(sender_hash) == "human"
        pode_responder = not atendimento_humano

        # 2. Degraus por número. Quem está falando com a equipe escreve à
        # vontade; para os outros, o aviso sai uma vez em cada degrau.
        if not atendimento_humano:
            degrau = degrau_do_remetente(
                store.recent_sender_count(sender_hash, JANELA_MINUTOS)
            )
            if degrau["aviso"]:
                store.enqueue_text(message, degrau["aviso"])
            pode_responder = degrau["responder"]
            if not degrau["registrar"]:
                store.block_inbox(message_id, "limite de mensagens")
                logger.warning("Mensagem descartada por excesso do remetente")
                return
            # Quem já foi bloqueado por conteúdo várias vezes na janela está
            # silenciado: nem chamado, nem resposta.
            if store.recent_blocked_count(sender_hash, JANELA_MINUTOS) >= STRIKES_PARA_SILENCIAR:
                store.block_inbox(message_id, "silenciado por strikes")
                logger.warning("Mensagem descartada de remetente silenciado")
                return

        raw_content = str(message.get("content") or "")
        transcribed = False

        # 3. Imagem, vídeo e afins nunca são baixados: o bot pede texto ou áudio.
        if message_type in TIPOS_DE_MIDIA:
            if pode_responder:
                store.enqueue_text(message, AVISO_SO_TEXTO_OU_AUDIO)
            store.finish_inbox(message_id, "ignored")
            return

        # 4. Áudio: cota por número, teto de tamanho e de duração, e só fala real.
        if message_type == "audio":
            if store.recent_sender_audio_count(sender_hash, AUDIO_JANELA_MINUTOS) > AUDIO_MAX_POR_JANELA:
                if pode_responder:
                    store.enqueue_text(message, AVISO_COTA_AUDIO)
                store.block_inbox(message_id, "cota de audio")
                return
            resultado = _transcribe_inbox_audio(message)
            motivo = resultado.get("motivo")
            if motivo:
                if pode_responder:
                    store.enqueue_text(message, _AVISO_POR_MOTIVO[motivo])
                if motivo in ("muito_grande", "muito_longo"):
                    store.block_inbox(message_id, f"audio {motivo}")
                else:
                    store.finish_inbox(message_id, "ignored")
                return
            raw_content = str(resultado["texto"])
            transcribed = True

        sector_code, content = _extract_sector(raw_content)
        sector = store.sector_by_code(sector_code)
        # QR com codigo que nao existe no banco nao pode passar silencioso: a
        # regiao cairia na adivinhacao da IA em vez do setor do cartaz.
        if sector_code and not sector:
            logger.warning(
                "QR com setor desconhecido | code=%s (cartaz com codigo errado?)",
                sector_code,
            )

        def _bloquear_conteudo(motivo: str, aviso: str) -> None:
            """Registra o strike, avisa uma vez e encerra a mensagem."""

            strikes = store.recent_blocked_count(sender_hash, JANELA_MINUTOS) + 1
            store.block_inbox(message_id, f"conteudo {motivo}")
            if pode_responder:
                store.enqueue_text(
                    message,
                    AVISO_SILENCIADO if strikes >= STRIKES_PARA_SILENCIAR else aviso,
                )
            logger.warning(
                "Mensagem bloqueada por conteúdo | motivo=%s strikes=%d", motivo, strikes
            )

        # 5. Moderação: pornografia, ódio e assédio não viram chamado nem
        # resposta criativa. Violência e emergência passam de propósito.
        if content.strip():
            moderacao = moderar_texto(content)
            if moderacao["bloquear"]:
                _bloquear_conteudo(str(moderacao["motivo"]), AVISO_CONTEUDO_BLOQUEADO)
                return

        # 6. Inundação geral: a IA é desligada, o chamado continua entrando.
        ia_ligada = store.recent_event_count(1) <= FLOOD_GLOBAL_POR_MINUTO
        if not ia_ligada:
            logger.warning("Inundação em curso: IA desligada neste chamado")

        # A IA decide se isso e conversa ou relato; a lista de palavras do
        # server so entra se ela estiver fora do ar ou desligada.
        triagem = triar_mensagem(content) if ia_ligada else triar_mensagem_sem_ia(content)

        # 7. Xingamento sem conteúdo: a moderação não pega (a pontuação de
        # "vai tomar no cu" é igual à de um relato de agressão com palavrão),
        # mas a triagem entende o sentido. Não ganha banter do Tuca.
        if triagem["tipo"] == "ofensa":
            _bloquear_conteudo("ofensa", AVISO_OFENSA)
            return

        if triagem["tipo"] == "conversa":
            resposta = compose_smalltalk(content) if ia_ligada else welcome_text()
            if sector:
                resposta += f"\n\n{_sector_prompt(sector)}"
            if pode_responder:
                store.enqueue_text(message, resposta)
            store.finish_inbox(message_id, "ignored")
            logger.info("Conversa respondida sem abrir chamado")
            return

        if len(content) < 3 or is_emoji_only(content):
            if pode_responder:
                store.enqueue_text(message, _sector_prompt(sector))
            store.finish_inbox(message_id, "ignored")
            return

        urgency, category, region = _classify(
            content, sector, urgency=triagem["urgencia"], usar_ia=ia_ligada
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
        if pode_responder:
            store.enqueue_text(
                message,
                _compose_reply(
                    content, category, urgency, sector, transcribed,
                    known=triagem.get("ficha"), usar_ia=ia_ligada,
                ),
                feedback_id,
            )
            # Ficha do guia com banner (line-up, cardápio): a imagem vai logo
            # depois do texto. Elogio e crítico não usam ficha, então não têm banner.
            ficha = triagem.get("ficha") or {}
            if ficha.get("image_url") and urgency not in ("Positivo", "Critico"):
                store.enqueue_image(
                    message, str(ficha["image_url"]),
                    caption=str(ficha.get("question") or ""), feedback_id=feedback_id,
                )
        store.finish_inbox(message_id)
        if not pode_responder:
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
        if message.get("message_type") == "image" and message.get("media_url"):
            provider_message_id = client.send_image(
                str(message["recipient"]),
                str(message["media_url"]),
                caption=str(message.get("content") or ""),
            )
        else:
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
