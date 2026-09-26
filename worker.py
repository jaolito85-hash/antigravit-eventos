"""Worker único para processar a caixa de entrada e enviar respostas."""

from __future__ import annotations

import logging
import os
import re
import signal
import time
from datetime import datetime, timedelta, timezone
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
    FALAS_NO_HISTORICO,
    _classify,
    _compose_reply,
    _fichas_ativas,
    _is_greeting,
    _extract_sector,
    _normalize,
    classificar_categoria,
    historico_em_texto,
    pergunta_de_lugar,
    pergunta_sobre_app,
    resposta_sobre_app,
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

# Arte (cardápio, line-up, loja) mandada dentro desta janela não vai de novo
# para a mesma pessoa: a pergunta seguinte sobre o mesmo assunto ("quanto
# custa?") é respondida em texto, a partir da ficha.
ARTE_RECENTE_MINUTOS = 30

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


# Depois da arte específica (cervejas, Red Bull, drinks) o Tuca oferece o
# cardápio geral de bebidas. Pedido do Joao Marcos em 25/09: a pessoa pergunta
# o preço da água, recebe a arte certa, e aí pode pedir o completo.
PERGUNTA_CARDAPIO_COMPLETO = (
    "Quer o cardápio completo de bebidas? Responde *QUERO* que eu te mando 🍹"
)
# Pergunta de disponibilidade ("tem cerveja?") recebe texto e este convite,
# quando a ficha tem arte (26/09). O "quero" seguinte manda a arte.
PERGUNTA_ARTE_VALORES = "Quer que eu te mande a arte com os valores? Responde *QUERO* 😉"
# A ficha do cardápio geral é marcada pelo escopo, cadastrado no painel.
ESCOPO_CARDAPIO_GERAL = "cardapio-geral"
_QUER_SIM = re.compile(
    r"^(?:sim|s|ss|quero|quero sim|sim quero|sim por favor|pode|pode mandar|pode ser|"
    r"manda|manda ai|manda sim|me manda|claro|bora|isso|vai|ok|okay|por favor|pfv|pf|"
    r"cardapio|o cardapio|cardapio completo|quero o cardapio|manda o cardapio|"
    r"line ?-?up|o line ?-?up|line ?-?up completo|quero o line ?-?up|manda o line ?-?up|"
    r"quero o completo|o completo)[\s!.]*$"
)

# Line-up, pedido do Joao Marcos em 26/09: pergunta geral recebe as três
# artes de uma vez, com a chamada fixa na legenda da primeira; pergunta de um
# palco recebe só aquele palco e o convite para os outros. A ficha geral é
# marcada pelo escopo no painel e não tem arte própria: as artes são as das
# fichas de cada palco, então trocar um banner no painel vale para os dois
# caminhos.
ESCOPO_LINEUP_GERAL = "lineup-geral"
CHAMADA_LINEUP = "*Segura essas pedradas de line-up!* 🎶🤘"
CHAMADA_PALCO = "*Segura essa pedrada!* 🎶🤘"
PERGUNTA_LINEUP_COMPLETO = (
    "Quer o line-up completo, com os outros palcos? Responde *QUERO* que eu te mando 🤘"
)
# Ordem das artes na resposta geral: o palco principal primeiro.
_ORDEM_DOS_PALCOS = ("tropical", "hype", "lab")
# Espaço entre uma arte e a seguinte, para a Meta entregar na ordem.
SEGUNDOS_ENTRE_ARTES = 3


def _enfileirar_artes(store: EventStore, message: dict[str, Any], artes: list[str],
                      legenda: str = "", feedback_id: int | None = None) -> None:
    """Várias artes para a mesma mensagem, na ordem e espaçadas.

    A legenda vai só na primeira. Cada arte tem a própria chave de
    idempotência e sai SEGUNDOS_ENTRE_ARTES depois da anterior.
    """

    for ordem, arte in enumerate(artes):
        extra = (
            {"chave": f"lineup{ordem}", "atraso_segundos": ordem * SEGUNDOS_ENTRE_ARTES}
            if ordem else {}
        )
        store.enqueue_image(
            message, arte, caption=legenda if ordem == 0 else "",
            feedback_id=feedback_id, **extra,
        )


def artes_do_lineup() -> list[str]:
    """As artes publicadas de cada palco, na ordem Tropical, Hype, Lab."""

    try:
        fichas = _fichas_ativas()
    except Exception:  # noqa: BLE001 - sem base, sem artes
        return []
    palcos = [
        f for f in fichas
        if f.get("kind") == "lineup"
        and str(f.get("image_url") or "").strip()
        and str(f.get("scope") or "").strip().lower() != ESCOPO_LINEUP_GERAL
    ]

    def ordem(ficha: dict[str, Any]) -> tuple[int, str]:
        titulo = _normalize(str(ficha.get("question") or ""))
        posicao = next(
            (i for i, nome in enumerate(_ORDEM_DOS_PALCOS) if nome in titulo),
            len(_ORDEM_DOS_PALCOS),
        )
        return posicao, titulo

    return [str(f["image_url"]).strip() for f in sorted(palcos, key=ordem)]


def _oferta_aceita(store: EventStore, sender_hash: str, content: str) -> str | None:
    """Qual convite a pessoa aceitou: "arte", "cardapio", "lineup" ou nenhum.

    Só vale com o convite entre as três últimas falas do Tuca, e vence o mais
    recente: quem pediu o cardápio e depois o line-up quer o line-up.
    """

    if not _QUER_SIM.match(_normalize(content).strip()):
        return None
    try:
        thread = store.conversation_thread(sender_hash, limit=6)
    except Exception:  # noqa: BLE001 - sem histórico, sem contexto
        return None
    do_tuca = [m for m in (thread or {}).get("messages") or [] if m.get("direction") == "out"]
    for fala in reversed(do_tuca[-3:]):
        texto = _normalize(str(fala.get("content") or ""))
        if "arte com os valores" in texto:
            return "arte"
        if re.search(r"line ?-?up completo", texto):
            return "lineup"
        if "cardapio completo" in texto:
            return "cardapio"
    return None


# A ficha de cada "quer a arte com os valores?", por pessoa. O worker é um
# processo só, então a memória basta; se ele reiniciar no meio, o "quero"
# cai na releitura pela triagem, abaixo. Guardar é o que garante a mesma
# arte: relida, "tem seda?" escolhia às vezes a ficha da tenda de tattoo,
# que também cita seda (26/09).
OFERTA_ARTE_MINUTOS = 30
_ARTES_OFERECIDAS: dict[str, tuple[float, dict[str, Any]]] = {}


def _lembrar_oferta(sender_hash: str, ficha: dict[str, Any]) -> None:
    agora = time.monotonic()
    for chave, (quando, _f) in list(_ARTES_OFERECIDAS.items()):
        if agora - quando > OFERTA_ARTE_MINUTOS * 60:
            _ARTES_OFERECIDAS.pop(chave, None)
    _ARTES_OFERECIDAS[str(sender_hash)] = (agora, dict(ficha))


def _oferta_lembrada(sender_hash: str) -> dict[str, Any] | None:
    registro = _ARTES_OFERECIDAS.get(str(sender_hash))
    if not registro or time.monotonic() - registro[0] > OFERTA_ARTE_MINUTOS * 60:
        return None
    return registro[1]


def _ficha_da_oferta(store: EventStore, sender_hash: str) -> dict[str, Any] | None:
    """A ficha da arte oferecida em "quer a arte com os valores?".

    A oferta não guarda a ficha: ela é a resposta à pergunta que veio logo
    antes ("tem cerveja?"). Essa pergunta passa de novo pela triagem junto
    com a resposta que o Tuca deu, que nomeia o lugar: sem ela, "tem seda?"
    escolhia a ficha da tenda de tattoo em vez da Loja Oficial (26/09).
    """

    lembrada = _oferta_lembrada(sender_hash)
    if lembrada and str(lembrada.get("image_url") or "").strip():
        return lembrada
    mensagens = _conversa(store, sender_hash)
    oferta = next(
        (i for i in range(len(mensagens) - 1, -1, -1)
         if mensagens[i].get("direction") == "out"
         and "arte com os valores" in _normalize(str(mensagens[i].get("content") or ""))),
        None,
    )
    if oferta is None:
        return None
    pergunta = next(
        (str(m.get("content") or "") for m in reversed(mensagens[:oferta])
         if m.get("direction") == "in" and str(m.get("content") or "").strip()),
        "",
    )
    if not pergunta:
        return None
    _codigo, pergunta = _extract_sector(pergunta)
    historico = historico_em_texto(mensagens[: oferta + 1], artes=_artes_cadastradas())
    try:
        ficha = (triar_mensagem(pergunta, historico=historico) or {}).get("ficha") or {}
    except Exception:  # noqa: BLE001 - sem triagem, sem arte
        return None
    return ficha if str(ficha.get("image_url") or "").strip() else None


def ficha_cardapio_geral() -> dict[str, Any] | None:
    """A ficha publicada com escopo cardapio-geral e arte, ou None."""

    try:
        fichas = _fichas_ativas()
    except Exception:  # noqa: BLE001 - sem base, sem oferta
        return None
    for ficha in fichas:
        if (
            str(ficha.get("scope") or "").strip().lower() == ESCOPO_CARDAPIO_GERAL
            and str(ficha.get("image_url") or "").strip()
        ):
            return ficha
    return None


def _quer_cardapio_completo(store: EventStore, sender_hash: str, content: str) -> bool:
    """A pessoa acabou de ouvir "quer o cardápio completo?" e disse que sim.

    Só vale com a pergunta entre as últimas falas do Tuca: "sim" solto
    continua sendo conversa, e "quero" sem contexto vai para a triagem.
    Olha as três últimas, não só a última, porque a foto e o texto saem em
    mensagens separadas e a hora de envio pode inverter a ordem (25/09).
    """

    return _oferta_aceita(store, sender_hash, content) == "cardapio"


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


def _conversa(store: EventStore, sender_hash: str) -> list[dict[str, Any]]:
    """As últimas mensagens desta pessoa, nos dois sentidos, lidas uma vez."""

    buscar = getattr(store, "conversation_thread", None)
    if not buscar:
        return []
    try:
        thread = buscar(sender_hash, limit=FALAS_NO_HISTORICO + 2)
    except Exception:  # noqa: BLE001 - sem histórico a resposta segue
        return []
    return list((thread or {}).get("messages") or [])


def _artes_cadastradas() -> dict[str, str]:
    """Endereço da imagem -> título da ficha, para nomear a arte no histórico."""

    try:
        return {
            str(f.get("image_url") or "").strip(): str(f.get("question") or "").strip()
            for f in _fichas_ativas()
            if str(f.get("image_url") or "").strip()
        }
    except Exception:  # noqa: BLE001 - sem a lista, a arte fica sem nome
        return {}


def _contexto(
    store: EventStore, sender_hash: str, atual: str, bruto: str = "",
    mensagens: list[dict[str, Any]] | None = None,
) -> str:
    """As últimas falas, para a IA entender continuação e não se apresentar de novo.

    Sem isso cada mensagem nasce do zero: "cadê você?" depois do oi vira
    outra apresentação, e "onde eu compro?" depois de "tem seda?" vira uma
    pergunta sem assunto. É montado uma vez por mensagem e vai para a
    triagem e para a resposta: toda decisão vê a mesma conversa. A mensagem
    atual sai da lista, ela já vai no prompt. `mensagens` é a conversa já
    lida por `_conversa`; sem ela, lê aqui.
    """

    if mensagens is None:
        mensagens = _conversa(store, sender_hash)
    return historico_em_texto(
        mensagens, atual=atual, bruto=bruto, artes=_artes_cadastradas(),
    )


def _artes_ja_enviadas(mensagens: list[dict[str, Any]], minutos: int = ARTE_RECENTE_MINUTOS) -> set[str]:
    """Imagens que o Tuca mandou a esta pessoa há pouco.

    Em 25/09 "tem seda?", "qto custa?" e "quanto custa?" receberam a mesma
    arte três vezes seguidas: a memória achou a ficha certa, e a regra da
    imagem repetiu a imagem. Quem já tem a arte na tela quer a resposta em
    texto. Data ilegível conta como recente: repetir é pior que escrever.
    """

    limite = datetime.now(timezone.utc) - timedelta(minutes=minutos)
    recentes: set[str] = set()
    for item in mensagens or []:
        url = str(item.get("media_url") or "").strip()
        if item.get("direction") != "out" or not url:
            continue
        quando = str(item.get("at") or "").strip()
        try:
            momento = datetime.fromisoformat(quando.replace("Z", "+00:00"))
            if momento.tzinfo is None:
                momento = momento.replace(tzinfo=timezone.utc)
        except ValueError:
            momento = None
        if momento is None or momento >= limite:
            recentes.add(url)
    return recentes


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


def _localizacao_anterior(store, message, feedback_id):
    reader = getattr(store, "preceding_location", None)
    if not callable(reader):
        return False
    coords = _coordenadas(reader(message.get("sender_hash"), str(message["id"]), before=message.get("created_at")) or "")
    if not coords:
        return False
    return bool(store.attach_location(message.get("sender_hash"), *coords, feedback_id=feedback_id))


def _prioridade_imediata(store, message, content, pode_responder):
    """Risco explícito antecede limites, atalhos, moderação e motores de IA."""
    from tuca_risco import risco_explicito, problema_acesso, normal
    critical = risco_explicito(content)
    access = problema_acesso(content)
    if not critical and not access:
        return False
    sender = str(message.get("sender_hash") or "")
    # Uma repetição idêntica recente não produz tempestade de chamados.
    reader = getattr(store, "recent_incident", None)
    previous = reader(sender, minutes=2) if callable(reader) else None
    if previous and normal(previous.get("message") or previous.get("content")) == normal(content):
        if str(previous.get("inbox_message_id")) != str(message["id"]):
            store.finish_inbox(str(message["id"]), "ignored")
            return True
    code, content = _extract_sector(content)
    sector = store.sector_by_code(code) if code else None
    from_qr = bool(sector)
    if sector:
        store.marcar_setor_do_inbox(str(message["id"]), str(sector["id"]))
    sector = sector or store.ultimo_setor_escaneado(sender, QR_RECENTE_MINUTOS)
    urgency = "Critico" if critical else "Urgente"
    category = "Segurança & Organização" if critical else "Estrutura & Espaço"
    fid = store.create_feedback(
        message=message, content=content, category=category,
        region=sector["name"] if sector else "N/A", urgency=urgency,
        topic=_topic(content, category, urgency), sector_id=str(sector["id"]) if sector else None,
        sector_source=("qr" if from_qr else "qr_recente") if sector else None,
    )
    if not fid:
        raise RuntimeError("Alerta não foi registrado")
    located = _localizacao_anterior(store, message, fid)
    if pode_responder:
        if located:
            reply = "Recebi seu alerta. O chamado está com a equipe e a localização que você enviou foi anexada."
        elif critical:
            reply = _compose_reply(content, category, urgency, sector, False, known=None, usar_ia=False)
        else:
            reply = "Registrei o bloqueio de acesso com prioridade para a equipe. Em qual rampa você está? Manda uma referência ou sua localização pelo clipe do WhatsApp."
        store.enqueue_text(message, reply, fid)
    store.finish_inbox(str(message["id"]))
    return True


def _complementar_incidente(store, message, content, pode_responder):
    from tuca_risco import complemento_incidente, risco_explicito
    if not complemento_incidente(content):
        return False
    from tuca_risco import normal
    pronoun = bool(re.match(r"^(?:ele|ela|a pessoa)\b", normal(content)))
    if risco_explicito(content) and not pronoun:
        return False
    reader = getattr(store, "recent_incident", None)
    if not callable(reader):
        return False
    sender = str(message.get("sender_hash") or "")
    previous = reader(sender)
    if not previous:
        return False
    history = _conversa(store, sender)
    last_out = next((str(m.get("content") or "").lower() for m in reversed(history) if m.get("direction") == "out"), "")
    if not any(word in last_out for word in ("localização", "referência", "qual banheiro", "qual bar", "qual rampa")):
        return False
    from tuca_risco import normal
    reference = not bool(re.match(r"^(?:ele|ela|a pessoa)\b", normal(content)))
    if not reference and previous.get("urgency") not in ("Critico", "Crítico"):
        return False
    fid = store.update_incident(sender, previous, message, reference=reference)
    if pode_responder and store.recent_sender_count(sender, JANELA_MINUTOS) <= 10:
        store.enqueue_text(message, ("Referência recebida e adicionada ao seu chamado para a equipe." if reference else "Atualizei seu chamado, que continua com prioridade máxima.") + " Se puder, envie também a localização pelo clipe do WhatsApp.", fid)
    store.finish_inbox(str(message["id"]))
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

        # O texto da legenda já é fornecido pela Meta; não exige baixar mídia.
        initial_content = str(message.get("content") or "")
        if message_type == "text" and _complementar_incidente(store, message, initial_content, pode_responder):
            return
        if message_type != "audio" and _prioridade_imediata(store, message, initial_content, pode_responder):
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

        if transcribed and _prioridade_imediata(store, message, raw_content, pode_responder):
            return

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

        if re.search(r"(?:telefones|dados pessoais|contatos).*(?:pessoas|participantes|usuarios)", _normalize(content)):
            if pode_responder:
                store.enqueue_text(message, "Não compartilho telefones nem dados pessoais de outros participantes. Se você precisa de ajuda no evento, me conta o que aconteceu.")
            store.finish_inbox(message_id, "ignored")
            return

        if re.search(r"celiac|alergi|contaminacao cruzada|sem gluten", _normalize(content)) and not re.search(r"passando mal|reacao|inchad|respir", _normalize(content)):
            if pode_responder:
                store.enqueue_text(message, "Não tenho confirmação sobre ingredientes e contaminação cruzada para garantir que essa comida atende à sua restrição. Confirme diretamente com a equipe do ponto de alimentação antes de pedir.")
            store.finish_inbox(message_id, "ignored")
            return

        if re.search(r"(?:falar|conversar) com (?:uma pessoa|um humano|um atendente|a equipe)", _normalize(content)):
            fid = store.create_feedback(message=message, content=content, category="Experiência Geral",
                region=sector["name"] if sector else "N/A", urgency="Neutro",
                topic="Pedido de atendimento humano", sector_id=str(sector["id"]) if sector else None)
            if not fid:
                raise RuntimeError("Pedido de atendimento não registrado")
            if pode_responder:
                store.enqueue_text(message, "Registrei seu pedido de atendimento humano. Para falar com alguém agora, procure a equipe do festival no local ou o SAC. Não consigo garantir um retorno por este WhatsApp.", fid)
            store.finish_inbox(message_id)
            return

        # "Qual o app de vocês?": o link está cadastrado no painel e a resposta
        # é fixa. A IA respondia "não tenho essa informação" e colava o link
        # em seguida (25/09).
        if pergunta_sobre_app(content):
            if pode_responder:
                store.enqueue_text(message, resposta_sobre_app())
            store.finish_inbox(message_id, "ignored")
            logger.info("Pergunta sobre o app respondida com o link cadastrado")
            return

        # "Quero" logo depois de um convite: vai a arte pedida, sem triagem e
        # sem chamado. No cardápio, a arte geral; no line-up, os palcos que a
        # pessoa ainda não recebeu.
        oferta = _oferta_aceita(store, sender_hash, content)
        if oferta == "arte":
            ofertada = _ficha_da_oferta(store, sender_hash)
            if ofertada:
                if pode_responder:
                    # A arte específica de bebida segue com o convite para o
                    # cardápio completo, como no pedido direto de preço.
                    geral = ficha_cardapio_geral() if ofertada.get("kind") == "bar" else None
                    oferece = bool(geral) and str(ofertada.get("scope") or "").strip().lower() != ESCOPO_CARDAPIO_GERAL
                    store.enqueue_image(
                        message, str(ofertada["image_url"]).strip(),
                        caption=PERGUNTA_CARDAPIO_COMPLETO if oferece else "",
                        feedback_id=None,
                    )
                store.finish_inbox(message_id, "ignored")
                logger.info("Arte com os valores enviada a pedido")
                return
        if oferta == "cardapio":
            geral = ficha_cardapio_geral()
            if geral:
                if pode_responder:
                    store.enqueue_image(
                        message, str(geral["image_url"]), caption="", feedback_id=None,
                    )
                store.finish_inbox(message_id, "ignored")
                logger.info("Cardápio completo enviado a pedido")
                return
        if oferta == "lineup":
            artes = artes_do_lineup()
            ja_tem = _artes_ja_enviadas(_conversa(store, sender_hash))
            faltam = [a for a in artes if a not in ja_tem] or artes
            if faltam:
                if pode_responder:
                    _enfileirar_artes(store, message, faltam)
                store.finish_inbox(message_id, "ignored")
                logger.info("Line-up completo enviado a pedido | artes=%s", len(faltam))
                return

        if _normalize(content).strip(" ?!.") in ("quero", "manda", "sim quero"):
            if pode_responder:
                store.enqueue_text(message, "O que você quer saber ou receber? Me diz o assunto para eu te ajudar.")
            store.finish_inbox(message_id, "ignored")
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

        # O relógio e a grade são dados: não delegar comparação de horários à IA.
        from tuca_programacao import answer as resposta_programacao
        if re.search(r"quem.*toca|tocando|depois|proximo", _normalize(content)):
            schedule = resposta_programacao(content, _conversa(store, sender_hash), _fichas_ativas())
            if schedule:
                if pode_responder:
                    store.enqueue_text(message, schedule)
                store.finish_inbox(message_id, "ignored")
                return

        # 7. Inundação geral: a IA é desligada, o chamado continua entrando.
        ia_ligada = store.recent_event_count(1) <= FLOOD_GLOBAL_POR_MINUTO
        if not ia_ligada:
            logger.warning("Inundação em curso: IA desligada neste chamado")

        # As últimas falas desta pessoa, lidas uma vez: a triagem e a
        # resposta leem a mesma conversa. Antes só a resposta tinha memória,
        # e a triagem decidia no escuro: "onde eu compro?" depois de "tem
        # seda?" abria chamado genérico com o link do app (25/09). A mesma
        # leitura diz que artes já foram mandadas, para não repetir.
        conversa = _conversa(store, sender_hash)
        historico = _contexto(store, sender_hash, content, raw_content, mensagens=conversa)
        artes_recentes = _artes_ja_enviadas(conversa)

        from tuca_intencao import agua_gratis
        agua = agua_gratis(content, conversa)
        if agua:
            if pode_responder:
                store.enqueue_text(message, agua)
            store.finish_inbox(message_id, "ignored")
            return


        # A IA decide se isso e conversa ou relato; a lista de palavras do
        # server so entra se ela estiver fora do ar ou desligada.
        #
        # Sem setor do QR, a mesma chamada tambem procura o lugar no texto. O
        # QR so acompanha a primeira mensagem de quem escaneou: audio nunca
        # carrega a tag, e ninguem volta na placa para escanear de novo.
        triagem = (
            triar_mensagem(content, localizar=not sector, historico=historico)
            if ia_ligada
            else triar_mensagem_sem_ia(content, setores=None if sector else _setores_ativos(), historico=historico)
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
                historico=historico,
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
                content, ja_falou=ja_falou, usar_ia=ia_ligada, historico=historico,
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
        gps_anterior = _localizacao_anterior(store, message, feedback_id) if urgency in URGENCIAS_QUE_PEDEM_EQUIPE else False
        ficha = triagem.get("ficha") or {}
        banner = str(ficha.get("image_url") or "").strip()
        # A ficha geral do line-up não tem arte própria: responde com as artes
        # dos três palcos, e a primeira decide se a resposta é repetida.
        lineup_geral = (
            ficha.get("kind") == "lineup"
            and str(ficha.get("scope") or "").strip().lower() == ESCOPO_LINEUP_GERAL
        )
        artes_lineup = artes_do_lineup() if lineup_geral else []
        if artes_lineup:
            banner = artes_lineup[0]
        # Só dúvida (Neutro) recebe a arte. Elogio não pergunta nada, crítico
        # tem protocolo fixo, e relato de problema ("falta cerveja no bar")
        # não pode voltar com o cardápio de cervejas: visto em 25/09, quando
        # o gatilho "cerveja" da ficha do cardápio pegou um relato de falta.
        # Pergunta de lugar ("onde tem seda?") quer o lugar, não a arte com
        # preço: vai texto, montado da ficha, que diz onde se vende. Arte
        # que a pessoa acabou de receber não vai de novo quando a mensagem
        # é só continuação ("qto custa?" depois da arte da seda): vai texto.
        # Pergunta completa ("sabe se tem água de coco?") recebe a arte de
        # novo, mesmo que ela tenha ido há pouco: em 25/09 a regra só por
        # tempo negou a arte a quem perguntou de novo 20 minutos depois.
        arte_repetida = bool(banner) and banner in artes_recentes and bool(triagem.get("continuacao"))
        continua_preco = bool(artes_recentes) and bool(re.fullmatch(r"(?:quanto custa|qto custa|qual (?:o )?preco)[?!. ]*", _normalize(content)))
        from tuca_intencao import permite_arte
        manda_banner = (
            bool(banner)
            and permite_arte(content, ficha)
            and not continua_preco
            and urgency == "Neutro"
            and not pergunta_de_lugar(content)
            and not arte_repetida
        )
        if arte_repetida and urgency == "Neutro":
            logger.info("Continuação com a arte já enviada: resposta em texto a partir da ficha")
        # "Tem cerveja?" recebe texto e a pergunta se quer a arte com os
        # valores (pedido de 26/09). Só quando a pessoa ainda não tem essa
        # arte na tela; pergunta de lugar, pagamento e água ficam só no texto.
        from tuca_intencao import intencao
        oferece_arte = (
            bool(banner)
            and not manda_banner
            and urgency == "Neutro"
            and ficha.get("kind") != "lineup"
            and intencao(content) in ("disponibilidade", "informacao")
            and not pergunta_de_lugar(content)
            and banner not in artes_recentes
        )

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
                    historico=historico,
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
                    and not gps_anterior
                    and (lugar_de_operacao or not triagem.get("ficha"))
                    and urgency in URGENCIAS_QUE_PEDEM_EQUIPE
                    and urgency not in ("Critico", "Crítico")
                ):
                    resposta += f"\n\n{pergunta_onde(triagem.get('lugar'))}"
                elif oferece_arte:
                    resposta += f"\n\n{PERGUNTA_ARTE_VALORES}"
                    _lembrar_oferta(sender_hash, ficha)
                store.enqueue_text(message, resposta, feedback_id)
            if manda_banner:
                # A arte específica de bebida vem com o convite para o
                # cardápio completo, como LEGENDA da própria imagem: numa
                # mensagem só a ordem é garantida. Em duas, a Meta entregava
                # o texto antes da foto (25/09, água de coco), e o "quero"
                # seguinte não achava a pergunta como última fala. O próprio
                # geral não se oferece.
                if artes_lineup:
                    # A chamada vai na legenda da primeira arte pelo mesmo
                    # motivo do convite do cardápio: texto solto chegava
                    # depois da foto.
                    _enfileirar_artes(
                        store, message, artes_lineup,
                        legenda=CHAMADA_LINEUP, feedback_id=feedback_id,
                    )
                elif ficha.get("kind") == "lineup":
                    outros = [a for a in artes_do_lineup() if a != banner]
                    legenda = CHAMADA_PALCO
                    if outros:
                        legenda += f"\n\n{PERGUNTA_LINEUP_COMPLETO}"
                    store.enqueue_image(
                        message, banner, caption=legenda, feedback_id=feedback_id,
                    )
                else:
                    geral = ficha_cardapio_geral() if ficha.get("kind") == "bar" else None
                    oferece = bool(geral) and str(ficha.get("scope") or "").strip().lower() != ESCOPO_CARDAPIO_GERAL
                    store.enqueue_image(
                        message, banner,
                        caption=PERGUNTA_CARDAPIO_COMPLETO if oferece else "",
                        feedback_id=feedback_id,
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
