"""Proteções do Tuca contra abuso vindo do WhatsApp.

Tudo que decide se uma mensagem do público entra, é respondida ou é
bloqueada mora aqui: moderação de conteúdo, degraus de limite por número,
limite de áudio, filtro do que a IA pode responder e detecção de
alucinação do Whisper. O worker e o simulador usam as mesmas funções, para
a produção ver no painel exatamente o que o participante receberia.
"""

from __future__ import annotations

import logging
import os
import re
import struct
from typing import Any

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Limites por número de telefone
# ----------------------------------------------------------------------
# Janela em minutos em que as mensagens de um número são contadas.
JANELA_MINUTOS = 10
# Até aqui tudo é normal: registra e responde.
LIMITE_RESPONDER = 10
# Acima de LIMITE_RESPONDER o chamado ainda entra, mas o bot avisa uma vez e
# cala. Acima deste teto a mensagem é descartada: é robô ou vandalismo.
LIMITE_REGISTRAR = 30

# Áudio: cada um de até 1 minuto, e no máximo 3 por hora por número.
AUDIO_MAX_SEGUNDOS = 60
AUDIO_MAX_POR_JANELA = 3
AUDIO_JANELA_MINUTOS = 60
# 1 minuto de nota de voz do WhatsApp tem uns 120 KB. O teto de download
# fica bem acima disso para não cortar áudio legítimo de outro formato, e bem
# abaixo dos 25 MB de antes, que davam horas de Opus para o Whisper cobrar.
AUDIO_MAX_BYTES = 1536 * 1024

# Inundação geral: acima disso por minuto, somando todos os números, a IA é
# desligada e o bot cai no caminho determinístico. O chamado continua entrando.
FLOOD_GLOBAL_POR_MINUTO = int(os.getenv("FLOOD_GLOBAL_POR_MINUTO", "60"))

# Mensagens ofensivas seguidas na janela até o número ser silenciado.
STRIKES_PARA_SILENCIAR = 3


# ----------------------------------------------------------------------
# Textos de aviso: sempre explicam o porquê, como a produção pediu
# ----------------------------------------------------------------------
AVISO_MUITAS_MENSAGENS = (
    "⚠️ Você mandou muitas mensagens em pouco tempo. Vou continuar registrando "
    "o que você enviar, mas só volto a responder daqui a alguns minutos.\n\n"
    "Se for emergência, procure agora a segurança ou a equipe médica mais próxima."
)
AVISO_LIMITE_ATINGIDO = (
    "🚫 Limite de mensagens atingido. Suas próximas mensagens não serão "
    "registradas por alguns minutos.\n\n"
    "Em caso de emergência, procure a equipe do festival no local."
)
AVISO_AUDIO_LONGO = (
    "🎤 Seu áudio passou de 1 minuto e eu não consigo ouvir áudios tão longos. "
    "Manda de novo em até 1 minuto, ou escreve em texto que eu leio na hora."
)
AVISO_AUDIO_GRANDE = (
    "🎤 Esse arquivo de áudio é grande demais para eu ouvir. "
    "Manda uma nota de voz de até 1 minuto, ou escreve em texto."
)
AVISO_COTA_AUDIO = (
    "🎤 Você já mandou 3 áudios na última hora, que é o meu limite. "
    "Pode continuar me escrevendo em texto que eu leio na hora."
)
AVISO_SEM_FALA = (
    "🎤 Não consegui entender seu áudio: só ouvi barulho ou música. "
    "Pode tentar de novo mais perto do celular, ou escrever em texto?"
)
AVISO_CONTEUDO_BLOQUEADO = (
    "Esse conteúdo não tem a ver com o festival e não vai para a equipe. "
    "Se você tiver um problema, elogio ou dúvida sobre o evento, me conta que eu levo."
)
AVISO_SILENCIADO = (
    "🚫 Suas mensagens foram bloqueadas por conteúdo ofensivo repetido. "
    "O Tuca é o canal de atendimento do festival."
)
# Não diz "xingamento" porque o mesmo aviso atende investida sexual sobre
# alguém do evento, que não é palavrão: dizer "xingamento" para quem escreveu
# "quero transar com a atendente do bar" soa desajeitado e erra o motivo.
AVISO_OFENSA = (
    "Isso eu não levo para a equipe. Se você tiver um problema, elogio "
    "ou dúvida sobre o festival, me conta que eu levo na hora."
)


# Xingamento puro, dirigido ao bot ou a ninguém, sem nada sobre o evento. É a
# reserva da triagem por IA: a pontuação da moderação não separa "vai tomar no
# cu" (0,74) de "filha da puta do segurança me empurrou" (0,80), que é relato
# de agressão. O que separa é o sentido, e sem IA a lista curta cobre o óbvio.
_XINGAMENTO_PURO = re.compile(
    r"^[\W_]*(?:"
    r"(?:vai|va|vah)\s+(?:tomar\s+no\s+cu|se\s+f[ou]der|te\s+f[ou]der|pro\s+inferno|a\s+merda|se\s+lascar)"
    r"|foda-?\s?se|vsf|vtnc|fdp|pqp"
    r"|cal[ae]\s+a\s+boca(?:\s+(?:tucano|bot|robo|seu\s+\w+))?"
    r"|(?:seu|sua|esse|essa)\s+(?:bot|robo|tucano|bicho|passaro|merda|lixo|bosta|idiota|burro|otario|imbecil|animal)"
    r"(?:\s+(?:de\s+)?(?:merda|bosta|lixo|idiota|burro|inutil|imprestavel))?"
    r"|filh[oa]\s+da\s+puta|desgraca(?:do|da)?|arrombad[oa]|idiota|imbecil|otari[oa]|babaca|burro|lixo|merda|bosta"
    r")[\W_]*$",
    flags=re.IGNORECASE,
)


def e_xingamento_puro(texto: str) -> bool:
    """Diz se a mensagem é só xingamento, sem informação sobre o evento."""

    limpo = (texto or "").strip()
    if not limpo or len(limpo) > 60:
        return False
    import unicodedata

    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", limpo.lower())
        if unicodedata.category(c) != "Mn"
    )
    return bool(_XINGAMENTO_PURO.match(sem_acento))


# ----------------------------------------------------------------------
# Degraus de limite
# ----------------------------------------------------------------------
def degrau_do_remetente(mensagens_na_janela: int) -> dict[str, Any]:
    """Diz o que fazer com a N-ésima mensagem de um número na janela.

    O contador inclui a mensagem atual. O aviso sai uma única vez em cada
    degrau, na primeira mensagem que o cruza: responder a cada excedente era
    o que transformava um spammer em centenas de envios pela Meta.
    """

    if mensagens_na_janela > LIMITE_REGISTRAR:
        return {
            "registrar": False,
            "responder": False,
            "aviso": AVISO_LIMITE_ATINGIDO if mensagens_na_janela == LIMITE_REGISTRAR + 1 else None,
        }
    if mensagens_na_janela > LIMITE_RESPONDER:
        return {
            "registrar": True,
            "responder": False,
            "aviso": AVISO_MUITAS_MENSAGENS if mensagens_na_janela == LIMITE_RESPONDER + 1 else None,
        }
    return {"registrar": True, "responder": True, "aviso": None}


# ----------------------------------------------------------------------
# Moderação de conteúdo
# ----------------------------------------------------------------------
# O que bloqueia. Violência, drogas e automutilação ficam de fora de
# propósito: "tem briga com faca", "estão vendendo droga" e "quero me matar"
# são exatamente os relatos que a segurança e a equipe médica precisam ver.
CATEGORIAS_BLOQUEADAS = (
    "sexual",
    "sexual/minors",
    "hate",
    "hate/threatening",
    "harassment/threatening",
)
# Xingar o segurança é reclamação, não assédio. Só bloqueia assédio quando o
# modelo tem muita certeza.
HARASSMENT_MINIMO = float(os.getenv("MODERATION_HARASSMENT_MIN", "0.85"))

# Reserva para quando a moderação da OpenAI estiver fora: só o que é
# inequivocamente sexual explícito. Lista curta de propósito, o julgamento
# fino é da IA.
_EXPLICITO = re.compile(
    r"\b(porn[oô]|pornografia|x?videos?\s*porn|nudes?|buceta|xoxota|pinto\s+duro|"
    r"caralho\s+na|chupa\s+meu|rola\s+dura|gozar\s+na|sexo\s+oral|mete[r]?\s+na)\b",
    flags=re.IGNORECASE,
)


def _moderacao_por_palavras(texto: str) -> dict[str, Any]:
    """Caminho determinístico quando a OpenAI está fora do ar."""

    if _EXPLICITO.search(texto or ""):
        return {"bloquear": True, "motivo": "sexual", "origem": "palavras"}
    return {"bloquear": False, "motivo": None, "origem": "palavras"}


def moderar_texto(texto: str, client: Any = None) -> dict[str, Any]:
    """Decide se um texto do público pode virar chamado e resposta.

    Usa o omni-moderation-latest, que é gratuito. Se ele falhar, a lista de
    palavras assume, porque bot mudo por causa de moderação fora é pior que
    moderação grosseira.
    """

    texto = (texto or "").strip()
    if not texto:
        return {"bloquear": False, "motivo": None, "origem": "vazio"}

    if client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return _moderacao_por_palavras(texto)
        try:
            from openai import OpenAI

            client = OpenAI(api_key=api_key, timeout=10)
        except Exception as exc:  # noqa: BLE001 - cliente indisponível cai na lista
            logger.error("Cliente de moderação indisponível | erro=%s", type(exc).__name__)
            return _moderacao_por_palavras(texto)

    try:
        resposta = client.moderations.create(
            model="omni-moderation-latest",
            input=texto[:4000],
        )
        resultado = resposta.results[0]
        categorias = _como_dict(resultado.categories)
        pontuacoes = _como_dict(resultado.category_scores)
    except Exception as exc:  # noqa: BLE001 - moderação fora não cala o bot
        logger.error("Moderação indisponível, usando palavras | erro=%s", type(exc).__name__)
        return _moderacao_por_palavras(texto)

    for categoria in CATEGORIAS_BLOQUEADAS:
        if categorias.get(categoria):
            return {"bloquear": True, "motivo": categoria, "origem": "ia"}
    if float(pontuacoes.get("harassment") or 0) >= HARASSMENT_MINIMO:
        return {"bloquear": True, "motivo": "harassment", "origem": "ia"}
    return {"bloquear": False, "motivo": None, "origem": "ia"}


def _como_dict(objeto: Any) -> dict[str, Any]:
    """O SDK devolve um modelo pydantic; os testes devolvem dict. Aceita os dois."""

    if isinstance(objeto, dict):
        return objeto
    for nome in ("model_dump", "to_dict"):
        metodo = getattr(objeto, nome, None)
        if callable(metodo):
            try:
                dados = metodo(by_alias=True) if nome == "model_dump" else metodo()
                if isinstance(dados, dict):
                    return dados
            except TypeError:
                dados = metodo()
                if isinstance(dados, dict):
                    return dados
    return dict(getattr(objeto, "__dict__", {}) or {})


# ----------------------------------------------------------------------
# Filtro de saída: o que a IA não pode dizer em nome do festival
# ----------------------------------------------------------------------
_URL = re.compile(r"(?:https?://|www\.)\S+|\b[\w-]+\.(?:com|br|net|org|app|io|me|link|ly)\b\S*", re.IGNORECASE)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_DIGITOS_LONGOS = re.compile(r"\d[\d .()-]{6,}\d")
_CHAVE_ALEATORIA = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE)
_PAGAMENTO = re.compile(r"\b(chave\s+pix|pix\s*:|transfer(?:ir|ência)|dep[oó]sit[oa]|pagu?e\s+r?\$|r\$\s*\d)", re.IGNORECASE)


def _so_digitos(valor: str) -> str:
    return re.sub(r"\D", "", valor)


def resposta_segura(reply: str, permitido: str = "") -> bool:
    """Diz se a resposta da IA pode ir para o participante.

    Link, e-mail, telefone, chave Pix ou instrução de pagamento só passam se
    já estiverem no material oficial da produção (resposta cadastrada, link
    do app, regras). É o que impede uma injeção de prompt de fazer o Tuca
    "confirmar" um golpe em nome do festival.
    """

    texto = reply or ""
    permitido = permitido or ""
    permitido_lower = permitido.lower()

    for url in _URL.findall(texto):
        if url.lower().rstrip(".,;:!?)") not in permitido_lower:
            return False
    for email in _EMAIL.findall(texto):
        if email.lower() not in permitido_lower:
            return False
    if _CHAVE_ALEATORIA.search(texto):
        return False
    digitos_permitidos = _so_digitos(permitido)
    for trecho in _DIGITOS_LONGOS.findall(texto):
        digitos = _so_digitos(trecho)
        if len(digitos) >= 7 and digitos not in digitos_permitidos:
            return False
    if _PAGAMENTO.search(texto) and not _PAGAMENTO.search(permitido):
        return False
    return True


# ----------------------------------------------------------------------
# Áudio: duração sem pagar transcrição, e transcrição sem alucinação
# ----------------------------------------------------------------------
def duracao_ogg_opus(dados: bytes) -> float | None:
    """Duração em segundos de um Ogg Opus, lendo só os cabeçalhos.

    Nota de voz do WhatsApp é sempre Ogg Opus. A última página traz a posição
    do último sample em 48 kHz, e o OpusHead traz quantos samples são
    descartados no início. Sem decodificar nada, então é grátis e instantâneo.
    """

    if not dados or dados[:4] != b"OggS":
        return None
    cabecalho = dados.find(b"OpusHead", 0, 512)
    pre_skip = 0
    if cabecalho != -1 and cabecalho + 12 <= len(dados):
        pre_skip = struct.unpack_from("<H", dados, cabecalho + 10)[0]

    posicao = len(dados)
    for _ in range(8):
        posicao = dados.rfind(b"OggS", 0, posicao)
        if posicao == -1 or posicao + 14 > len(dados):
            return None
        versao = dados[posicao + 4]
        granule = struct.unpack_from("<q", dados, posicao + 6)[0]
        if versao == 0 and granule >= 0:
            return max(0.0, (granule - pre_skip) / 48000.0)
    return None


# Frases que o Whisper inventa em silêncio ou música, em qualquer idioma que
# ele "ouviu" na internet. Bastam para descartar a transcrição inteira.
_ALUCINACOES = (
    "legendas pela comunidade",
    "amara.org",
    "obrigado por assistir",
    "inscreva-se no canal",
    "subtitles by",
    "thanks for watching",
    "thank you for watching",
    "sous-titres",
    "untertitel",
)
NO_SPEECH_MAXIMO = 0.6
LOGPROB_MINIMO = -1.0


def filtrar_transcricao(resultado: Any) -> str:
    """Devolve só a fala real de um resultado verbose do Whisper.

    Num festival o áudio vem com show ao fundo, e o Whisper responde a
    música com letra ou com frase de encerramento de vídeo. Segmento com
    probabilidade alta de não ser fala, ou com confiança muito baixa, sai.
    """

    if resultado is None:
        return ""
    segmentos = getattr(resultado, "segments", None)
    if segmentos is None and isinstance(resultado, dict):
        segmentos = resultado.get("segments")
    texto_bruto = getattr(resultado, "text", None)
    if texto_bruto is None and isinstance(resultado, dict):
        texto_bruto = resultado.get("text")

    if not segmentos:
        texto = (texto_bruto or "").strip()
    else:
        partes = []
        for seg in segmentos:
            dados = seg if isinstance(seg, dict) else getattr(seg, "__dict__", {})
            no_speech = float(dados.get("no_speech_prob") or 0)
            logprob = float(dados.get("avg_logprob") or 0)
            if no_speech > NO_SPEECH_MAXIMO or logprob < LOGPROB_MINIMO:
                continue
            partes.append(str(dados.get("text") or "").strip())
        texto = " ".join(p for p in partes if p).strip()

    baixo = texto.lower()
    if any(marca in baixo for marca in _ALUCINACOES):
        return ""
    return texto
