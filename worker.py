"""Worker único para processar a caixa de entrada e enviar respostas."""

from __future__ import annotations

import logging
import os
import re
import signal
import time
from datetime import datetime, timezone
from typing import Any

from event_store import SEM_LEGENDA, EventStore
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
    _is_greeting,
    _extract_sector,
    classificar_categoria,
    _sector_prompt,
    _setores_ativos,
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
TIPOS_DE_MIDIA = frozenset({"image", "video", "document", "interactive"})

# Quanto tempo depois do relato uma localização ainda é entendida como parte
# dele. Uma hora cobre a pessoa que demora para achar o botão no WhatsApp.
LOCALIZACAO_JANELA_MINUTOS = 60

# Por quanto tempo a placa escaneada ainda diz onde a pessoa está. Cinco
# minutos cobrem o caminho normal, que é escanear, ser cumprimentado e
# escrever o problema, e não cobrem quem já andou para outro canto: o Lucas
# pediu essa janela em 23/09/2026 porque "a rotatividade é gigante". Passou
# disso, o chamado entra sem lugar e o Tuca pergunta onde a pessoa está.
QR_RECENTE_MINUTOS = 5

# As urgências em que faltar o lugar atrapalha de verdade. São as mesmas que
# acendem pino no telão: sem elas o chamado não vira deslocamento de equipe.
URGENCIAS_QUE_PEDEM_EQUIPE = ("Critico", "Crítico", "Urgente")

AVISO_AUDIO_INDISPONIVEL = (
    "🎤 Não consegui entender seu áudio agora. Pode tentar de novo ou escrever em texto?"
)
AVISO_SO_TEXTO_OU_AUDIO = (
    "Por enquanto, envie sua mensagem em texto ou áudio 🎤 para conseguirmos "
    "encaminhá-la corretamente."
)
AVISO_LOCALIZACAO_RECEBIDA = (
    "📍 Localização recebida, obrigado! Já mandei para a equipe junto com o seu "
    "chamado."
)
AVISO_LOCALIZACAO_SEM_CHAMADO = (
    "📍 Recebi sua localização! Me conta em texto ou áudio 🎤 o que está "
    "acontecendo aí, que eu levo na hora para a equipe."
)
# Quando o chamado pede equipe e ninguém sabe onde é, perguntar é melhor que
# adivinhar. Vai junto da resposta, e só aí: em elogio e dúvida seria mais um
# papel na mão de quem só queria conversar.
PERGUNTA_ONDE_ESTA = (
    "📍 Me diz onde você está (o bar, o banheiro ou o palco mais perto), ou manda "
    "sua localização pelo clipe 📎, que eu já aviso a equipe."
)

# Quando a pessoa disse o tipo de lugar ("aqui na entrada", "o banheiro") mas
# há vários desse tipo na planta, a pergunta é qual deles, não "onde você
# está": perguntar de novo o que ela acabou de dizer soa como se o bot não
# tivesse lido (24/09). A palavra vem do grupo do setor, no singular.
_NOME_DO_LUGAR = {
    "Entradas e Acessos": "entrada",
    "Sanitários": "banheiro",
    "Bares": "bar",
    "Alimentação": "ponto de alimentação",
    "Palcos": "palco",
    "Ativações e Lazer": "ativação",
    "Caixas": "caixa",
    "Telões": "telão",
    "Lojas e Feirinha": "loja",
    # Saúde, Acessibilidade e Atendimento ao Público ficam de fora: quem
    # diz "não tô bem" não está no ambulatório, e "em qual ambulatório?"
    # (25/09) era pergunta sem sentido. Nesses casos vale "onde você está".
}


def pergunta_onde(lugar: str | None) -> str:
    """A pergunta de lugar certa: qual deles, se o tipo já veio; onde, se não."""

    nome = _NOME_DO_LUGAR.get(str(lugar or "").strip())
    if not nome:
        return PERGUNTA_ONDE_ESTA
    return (
        f"📍 Em qual {nome}? Manda sua localização pelo clipe 📎 ou uma referência "
        "perto de você, que eu já aviso a equipe."
    )

AVISO_LOCALIZACAO_ILEGIVEL = (
    "Não consegui ler essa localização. Pode mandar de novo pelo botão de "
    "anexo do WhatsApp, ou me descrever uma referência bem visível?"
)


def _contexto(store: EventStore, sender_hash: str, atual: str) -> str:
    """As últimas falas, para a IA entender continuação e não se apresentar de novo.

    Sem isso cada mensagem nasce do zero: "cadê você?" depois do oi vira
    outra apresentação. A mensagem atual sai da lista, ela já vai no prompt.
    """

    buscar = getattr(store, "conversation_thread", None)
    if not buscar:
        return ""
    try:
        thread = buscar(sender_hash, limit=8)
    except Exception:  # noqa: BLE001 - sem histórico a resposta segue
        return ""
    linhas = []
    for item in (thread or {}).get("messages") or []:
        texto = str(item.get("content") or "").strip()
        if not texto:
            continue
        # O histórico entra no prompt como texto solto, fora da tag que marca
        # a mensagem do participante como dado. Quem fechou a tag na mensagem
        # anterior não pode reabrir o bloco de instruções pela conversa.
        texto = re.sub(r"</?\s*participant\s*>", " ", texto, flags=re.IGNORECASE)
        quem = "Pessoa" if item.get("direction") == "in" else "Tuca"
        linhas.append(f"{quem}: {texto[:400]}")
    if linhas and atual and linhas[-1] == f"Pessoa: {atual.strip()[:400]}":
        linhas.pop()
    return "\n".join(linhas[-6:])


def _processar_enxuto(
    store: EventStore,
    message: dict[str, Any],
    raw_content: str,
    transcribed: bool,
    sender_hash: str,
    pode_responder: bool,
    sector: dict[str, Any] | None,
) -> None:
    """Plano B: o Tuca enxuto responde, com a memória vinda do banco.

    O motor foi escrito para o laboratório, com estado em memória. Aqui o
    estado nasce da conversa gravada e o que ele decide (chamado, resposta,
    bloqueio) é persistido do mesmo jeito que o fluxo de sempre.
    """

    import tuca_enxuto

    message_id = str(message["id"])
    snapshot = {
        "config": store.live_config(),
        "sectors": store.list_sectors(),
        "window": list(store.event_window()),
        "clock": datetime.now(timezone.utc).isoformat(),
    }
    try:
        thread = store.conversation_thread(sender_hash, limit=8)
    except Exception:  # noqa: BLE001 - sem histórico a resposta segue
        thread = {}
    historico = [
        {"direction": m.get("direction"), "content": str(m.get("content") or "")}
        for m in (thread or {}).get("messages") or []
        if m.get("content")
    ]
    # A mensagem atual já está gravada na caixa de entrada e viria repetida.
    _, content = _extract_sector(raw_content)
    if (
        historico
        and historico[-1]["direction"] == "in"
        and historico[-1]["content"].strip() in (raw_content.strip(), content.strip())
    ):
        historico.pop()
    state: dict[str, Any] = {"history": historico, "cards": []}
    recente = sector or store.ultimo_setor_escaneado(sender_hash, QR_RECENTE_MINUTOS)
    if recente:
        state["location"] = {
            "id": recente.get("id"), "code": recente.get("code"),
            "name": recente.get("name"), "at": time.time(),
        }

    resultado = tuca_enxuto.respond(state, snapshot, raw_content, "text")
    texto = "\n".join(str(m.get("content") or "") for m in resultado.get("messages") or []).strip()

    feedback_id = None
    for card in state["cards"]:
        lugar = card.get("location") or {}
        setor_do_card = store.sector_by_code(lugar.get("code")) if lugar.get("code") else None
        if not setor_do_card and lugar.get("id"):
            setor_do_card = {"id": lugar["id"], "name": lugar.get("name") or "N/A"}
        category = classificar_categoria(content)
        feedback_id = store.create_feedback(
            message=message,
            content=content,
            category=category,
            region=str(setor_do_card["name"]) if setor_do_card else "N/A",
            urgency=card["urgency"],
            topic=_topic(content, category, card["urgency"]),
            sector_id=str(setor_do_card["id"]) if setor_do_card else None,
            sector_source=("qr" if sector else "qr_recente") if setor_do_card else None,
            place_group=None,
        )
    if pode_responder and texto:
        prefix = "🎤 *Ouvi seu áudio!*\n\n" if transcribed else ""
        store.enqueue_text(message, prefix + texto, feedback_id)
    if resultado.get("status") == "blocked":
        store.block_inbox(message_id, "conteudo ofensa")
    else:
        store.finish_inbox(message_id, "processed" if state["cards"] else "ignored")
    logger.info(
        "Motor enxuto respondeu | prioridade=%s chamado=%s",
        resultado.get("urgency"), bool(state["cards"]),
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


def _coordenadas(conteudo: str) -> tuple[float, float] | None:
    """Lê o "lat,lon" que o parse do webhook monta, ou devolve None.

    Coordenada fora de faixa é descartada em vez de ir para o painel: pino em
    lugar impossível faz a equipe andar para o nada.
    """

    partes = (conteudo or "").split(",")
    if len(partes) != 2:
        return None
    try:
        lat, lon = float(partes[0].strip()), float(partes[1].strip())
    except ValueError:
        return None
    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        return None
    return lat, lon


def _tratar_localizacao(
    store: EventStore,
    message: dict[str, Any],
    pode_responder: bool,
    sender_hash: str,
) -> None:
    """Prende a localização ao chamado que a pessoa já abriu.

    O Tuca pede localização no protocolo de emergência, então recusar a
    resposta dela era o pior comportamento possível: ele pedia e devolvia
    "envie em texto ou áudio".
    """

    message_id = str(message["id"])
    coords = _coordenadas(str(message.get("content") or ""))
    if not coords:
        if pode_responder:
            store.enqueue_text(message, AVISO_LOCALIZACAO_ILEGIVEL)
        store.finish_inbox(message_id, "ignored")
        logger.warning("Localizacao ilegivel descartada")
        return

    lat, lon = coords
    alvo = store.attach_location(
        sender_hash, lat, lon, janela_minutos=LOCALIZACAO_JANELA_MINUTOS
    )
    if pode_responder:
        store.enqueue_text(
            message,
            AVISO_LOCALIZACAO_RECEBIDA if alvo else AVISO_LOCALIZACAO_SEM_CHAMADO,
            alvo["id"] if alvo else None,
        )
    store.finish_inbox(message_id)
    if alvo:
        logger.info(
            "Localizacao anexada ao chamado | id=%s prioridade=%s",
            alvo["id"], alvo.get("urgency"),
        )
    else:
        logger.info("Localizacao sem chamado recente: pedi o relato")


def _atendimento_aprovado(store, message, content, sector, pode_responder, transcribed):
    from tuca_atendimento import resolve, is_candidate
    if not is_candidate(content):
        return False
    sender = str(message.get("sender_hash") or "")
    try:
        history = (store.conversation_thread(sender, limit=10) or {}).get("messages") or []
        if history and history[-1].get("direction") == "in" and history[-1].get("content") in (content, message.get("content")):
            history = history[:-1]
    except Exception:  # Sem contexto, não presumimos continuação da reclamação.
        history = []
    known = sector or store.ultimo_setor_escaneado(sender, QR_RECENTE_MINUTOS)
    answer = resolve(content, history, known)
    if not answer:
        return False
    feedback_id = None
    if answer["register"]:
        feedback_id = store.create_feedback(
            message=message, content=content, category="Experiência Geral",
            region=known["name"] if known else "N/A", urgency="Neutro",
            topic="Insatisfação com o evento", sector_id=str(known["id"]) if known else None,
            sector_source=("qr" if sector else "qr_recente") if known else None,
            place_group=None,
        )
        if not feedback_id:
            raise RuntimeError("Reclamação não foi registrada")
    if pode_responder:
        prefix = "🎤 *Ouvi seu áudio!*\n\n" if transcribed else ""
        store.enqueue_text(message, prefix + answer["reply"], feedback_id)
    store.finish_inbox(str(message["id"]), "processed" if feedback_id else "ignored")
    return True


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

        # Uma localização completa um chamado existente, mesmo após o limite.
        if message_type == "location":
            responder_localizacao = pode_responder
            if not atendimento_humano:
                responder_localizacao = (
                    degrau_do_remetente(store.recent_sender_count(sender_hash, JANELA_MINUTOS))["responder"]
                    and store.recent_blocked_count(sender_hash, JANELA_MINUTOS) < STRIKES_PARA_SILENCIAR
                )
            _tratar_localizacao(store, message, responder_localizacao, sender_hash)
            return

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

        # 4. Imagem, vídeo e afins nunca são baixados: o bot pede texto ou áudio.
        if message_type in TIPOS_DE_MIDIA:
            if pode_responder:
                store.enqueue_text(message, AVISO_SO_TEXTO_OU_AUDIO)
            store.finish_inbox(message_id, "ignored")
            return

        # 5. Áudio: cota por número, teto de tamanho e de duração, e só fala real.
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
        if sector:
            # A etiqueta fica guardada na mensagem, e não só neste chamado: ela
            # costuma chegar sozinha, numa mensagem que vira cumprimento, e o
            # relato de verdade vem na seguinte, já sem etiqueta nenhuma.
            store.marcar_setor_do_inbox(message_id, str(sector["id"]))
        # QR com codigo que nao existe no banco nao pode passar silencioso: a
        # regiao cairia na adivinhacao da IA em vez do setor do cartaz.
        if sector_code and not sector:
            logger.warning(
                "QR com setor desconhecido | code=%s (cartaz com codigo errado?)",
                sector_code,
            )

        # Plano B: o motor enxuto responde no lugar do fluxo de sempre. A chave
        # fica no evento e a produção troca pelo painel, sem publicar nem
        # subir deploy. As barreiras de cima (limite, mídia, áudio) valem
        # para os dois; daqui para baixo cada motor faz o seu.
        if getattr(store, "motor_ativo", lambda: "atual")() == "enxuto":
            _processar_enxuto(
                store, message, raw_content, transcribed, sender_hash, pode_responder, sector,
            )
            return

        # Placa escaneada sem texto nenhum: é o primeiro contato de quem acabou
        # de ler o QR, e não há o que triar. Não se paga IA nem se arrisca
        # resposta a uma mensagem vazia: quem chega recebe as boas-vindas
        # cadastradas no painel e o convite do setor; quem já falou na janela
        # recebe só o convite, para não ouvir o cartaz de novo.
        if not content.strip():
            if pode_responder:
                primeira_vez = store.recent_sender_count(sender_hash, JANELA_MINUTOS) <= 1
                partes = [welcome_text()] if primeira_vez else []
                partes.append(_sector_prompt(sector))
                store.enqueue_text(message, "\n\n".join(partes))
            store.finish_inbox(message_id, "ignored")
            logger.info("Mensagem sem texto: convite enviado sem triagem")
            return

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

        # 6. Moderação: pornografia, ódio e assédio não viram chamado nem
        # resposta criativa. Violência e emergência passam de propósito.
        if content.strip():
            moderacao = moderar_texto(content)
            if moderacao["bloquear"]:
                _bloquear_conteudo(str(moderacao["motivo"]), AVISO_CONTEUDO_BLOQUEADO)
                return

        # Correções de atendimento aprovadas pelo usuário, após a moderação existente.
        if _atendimento_aprovado(store, message, content, sector, pode_responder, transcribed):
            return

        # 7. Inundação geral: a IA é desligada, o chamado continua entrando.
        ia_ligada = store.recent_event_count(1) <= FLOOD_GLOBAL_POR_MINUTO
        if not ia_ligada:
            logger.warning("Inundação em curso: IA desligada neste chamado")

        # A IA decide se isso e conversa ou relato; a lista de palavras do
        # server so entra se ela estiver fora do ar ou desligada.
        #
        # Sem setor do QR, a mesma chamada tambem procura o lugar no texto. O
        # QR so acompanha a primeira mensagem de quem escaneou: audio nunca
        # carrega a tag, e ninguem volta na placa para escanear de novo.
        triagem = (
            triar_mensagem(content, localizar=not sector)
            if ia_ligada
            else triar_mensagem_sem_ia(content, setores=None if sector else _setores_ativos())
        )

        # 8. Xingamento sem conteúdo: a moderação não pega (a pontuação de
        # "vai tomar no cu" é igual à de um relato de agressão com palavrão),
        # mas a triagem entende o sentido. Não ganha banter do Tuca.
        if triagem["tipo"] == "ofensa":
            _bloquear_conteudo("ofensa", AVISO_OFENSA)
            return

        if triagem["tipo"] == "conversa" and not _is_greeting(content):
            # A IA chamou de papo, mas há uma pergunta. O mesmo modelo que
            # responde dúvida atende, com o que já foi dito. O texto de oi
            # não entra aqui.
            resposta = _compose_reply(
                content, "Experiência Geral", triagem.get("urgencia") or "Neutro",
                sector, transcribed, known=triagem.get("ficha"), usar_ia=ia_ligada,
                chamado_registrado=False,
                historico=_contexto(store, sender_hash, content),
            )
            if sector:
                resposta += f"\n\n{_sector_prompt(sector)}"
            if pode_responder:
                store.enqueue_text(message, resposta)
            store.finish_inbox(message_id, "ignored")
            logger.info("Pergunta respondida sem abrir chamado")
            return

        if triagem["tipo"] == "conversa":
            # A contagem inclui a mensagem atual. Mais de uma na janela quer
            # dizer que esta pessoa já ouviu o Tuca: repetir a apresentação
            # inteira a cada oi é o que esgota o limite de mensagens.
            ja_falou = store.recent_sender_count(sender_hash, JANELA_MINUTOS) > 1
            resposta = compose_smalltalk(
                content, ja_falou=ja_falou, usar_ia=ia_ligada,
                historico=_contexto(store, sender_hash, content),
            )
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

        # Setor achado no texto. Vale para o mapa e para o roteamento, mas
        # nao muda o que o participante ouve: afirmar "voce esta no Palco
        # Tropical" com base em deducao seria vender certeza que nao existe.
        do_texto = triagem.get("setor") if not sector else None

        # Terceira chance de saber onde a pessoa está: a placa que ela escaneou
        # há pouco. Vale menos que a etiqueta desta mensagem e menos que o lugar
        # citado no texto, e por isso entra por último. Sem isso, o caso normal
        # (escanear, ser cumprimentado, e só então contar o problema) chegava
        # sem lugar nenhum, e chamado sem lugar não acende pino no telão.
        herdado = None
        if not sector and not do_texto:
            herdado = store.ultimo_setor_escaneado(sender_hash, QR_RECENTE_MINUTOS)

        localizado = sector or do_texto or herdado
        urgency, category, region = _classify(
            content, localizado, urgency=triagem["urgencia"], usar_ia=ia_ligada
        )
        feedback_id = store.create_feedback(
            message=message,
            content=content,
            category=category,
            region=region,
            urgency=urgency,
            topic=_topic(content, category, urgency),
            sector_id=str(localizado["id"]) if localizado else None,
            # A origem nunca mente sobre a certeza: "qr" é a etiqueta desta
            # mensagem, "qr_recente" é a placa que ela escaneou há pouco.
            sector_source=(
                "qr" if sector
                else triagem.get("setor_por") if do_texto
                else "qr_recente" if herdado
                else None
            ),
            # Com setor, o grupo sai dele na hora de somar, para não congelar
            # a conta se a planta mudar. Sem setor, o tipo de lugar é tudo
            # que se sabe e precisa ficar guardado.
            place_group=None if localizado else triagem.get("lugar"),
        )
        ficha = triagem.get("ficha") or {}
        banner = str(ficha.get("image_url") or "").strip()
        # Só dúvida (Neutro) recebe a arte. Elogio não pergunta nada, crítico
        # tem protocolo fixo, e relato de problema ("falta cerveja no bar")
        # não pode voltar com o cardápio de cervejas: visto em 25/09, quando
        # o gatilho "cerveja" da ficha do cardápio pegou um relato de falta.
        manda_banner = bool(banner) and urgency == "Neutro"

        if pode_responder:
            # Ficha com imagem responde SÓ pela imagem: a arte já é a resposta
            # inteira (line-up, cardápio), e o Joao Marcos pediu em 25/09 que
            # nenhum texto fosse antes dela. O texto cadastrado continua
            # existindo para a triagem saber o que a arte contém e escolher a
            # ficha certa; ele só não vai para o WhatsApp.
            if not manda_banner:
                resposta = _compose_reply(
                    content, category, urgency, localizado, transcribed,
                    known=triagem.get("ficha"), usar_ia=ia_ligada,
                    historico=_contexto(store, sender_hash, content),
                )
                # Chamado que pede equipe sem setor cravado: o Tuca pergunta em
                # vez de mandar a equipe procurar o festival inteiro. Se a
                # pessoa já disse o tipo de lugar ("aqui na entrada"), a
                # pergunta é qual deles. No Crítico o protocolo de emergência
                # já pede a localização, pela IA e pelo texto de reserva.
                # Quando a pessoa fala de um lugar de operação (bar, banheiro,
                # caixa, palco), a equipe precisa ir até lá: pergunta qual,
                # mesmo que uma ficha tenha respondido ("acabou a cerveja no
                # bar do hype" tem ficha e há três bares Hype). Fora disso, a
                # ficha oficial já diz para onde ir ("procure o SAC") e
                # perguntar onde a pessoa está era o deslize de "perdi minha
                # pulseira" e "reembolso" (24/09).
                lugar_de_operacao = triagem.get("lugar") in _NOME_DO_LUGAR
                if (
                    not localizado
                    and (lugar_de_operacao or not triagem.get("ficha"))
                    and urgency in URGENCIAS_QUE_PEDEM_EQUIPE
                    and urgency not in ("Critico", "Crítico")
                ):
                    resposta += f"\n\n{pergunta_onde(triagem.get('lugar'))}"
                store.enqueue_text(message, resposta, feedback_id)
            if manda_banner:
                store.enqueue_image(
                    message, banner, caption="", feedback_id=feedback_id,
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
            legenda = str(message.get("content") or "").strip()
            provider_message_id = client.send_image(
                str(message["recipient"]),
                str(message["media_url"]),
                caption="" if legenda == SEM_LEGENDA else legenda,
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
                for ready in store.pending_outbox():
                    process_outbox(store, client, ready)
                if not _running:
                    break
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
