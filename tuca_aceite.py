"""A pessoa aceitou o convite do Tuca? ("Responde QUERO que eu te mando")

Pedido de 26/09: o "quero" chega de todo jeito, digitado com erro ou falado
em áudio: "quer", "s", "aham", "mand", "pode mandar aí", "simmm". Primeiro
vale uma regra tolerante, que resolve quase tudo sem custo. Quando a
resposta é curta e a regra não decide, a IA julga se foi um sim.
"""

from __future__ import annotations

import difflib
import logging
import re
import unicodedata

logger = logging.getLogger(__name__)

# Até quantas palavras uma resposta ainda pode ser só um "sim".
PALAVRAS_MAXIMAS = 6
# Abaixo disso, a regra que não decidiu pergunta à IA.
PALAVRAS_PARA_IA = 4

_NEGA = {"n", "nao", "nem", "nunca", "depois", "dps", "deixa", "esquece", "nada", "nope"}
_SIM_EXATO = {"s", "sm", "si", "sin", "vai", "pf", "pfv", "opa", "yes", "yep", "ok", "okay", "oky", "okey", "dale", "fechou"}
# Raízes depois de juntar letras repetidas: "querooo" vira "quero", "isso" vira "iso".
_RAIZES = (
    "quer", "qer", "ker", "qro", "kro", "mand", "mnd", "mamd", "envi", "mostr",
    "pod", "sim", "clar", "bor", "aham", "ahan", "anham", "uhum", "umhum",
    "blz", "belez", "posit", "vamo", "iso", "certez", "logic",
)
# Palavras que acompanham o sim sem mudar o sentido: "manda aí o cardápio".
_ENCHIMENTO = {
    "o", "a", "os", "as", "me", "mim", "pra", "pro", "para", "ai", "ae", "la", "aqui",
    "ele", "ela", "esa", "ese", "tb", "tbm", "tambem", "eu", "ja", "agora", "agr",
    "entao", "ah", "e", "ta", "to", "por", "favor", "q", "que", "da", "de", "do",
    "com", "tudo", "td", "bem", "po", "mano", "vei", "cara",
    "please", "pls", "plis", "ne", "uai", "tche", "bah", "so",
}
# Nomear o que foi oferecido também aceita: "o cardápio", "o line-up".
_OFERECIDO = {
    "cardapio", "line", "up", "lineup", "completo", "completa", "arte", "artes",
    "foto", "fotos", "imagem", "valores", "valor", "preco", "precos", "tabela",
    "banner", "banners",
}
# Parecidas com estas também valem ("qeuro", "mnada"). "claro" fica fora:
# "caro" (reclamação de preço) passaria por parecido.
_PARECIDAS = ("quero", "manda", "mande", "pode", "aham")


def _normalizar(texto: str) -> str:
    minusculo = unicodedata.normalize("NFD", str(texto or "").lower())
    sem_acento = "".join(c for c in minusculo if unicodedata.category(c) != "Mn")
    so_letras = re.sub(r"[^a-z ]+", " ", sem_acento)
    return " ".join(re.sub(r"(.)\1+", r"\1", so_letras).split())


def _afirma(palavra: str) -> bool:
    if palavra in _SIM_EXATO or palavra.startswith(_RAIZES):
        return True
    return len(palavra) >= 4 and bool(difflib.get_close_matches(palavra, _PARECIDAS, n=1, cutoff=0.75))


def aceite_por_regra(texto: str) -> bool | None:
    """True é sim, False é não (ou mensagem longa), None é dúvida."""

    palavras = _normalizar(texto).split()
    if not palavras or len(palavras) > PALAVRAS_MAXIMAS:
        return False
    if any(p in _NEGA for p in palavras):
        return False
    afirmam = [p for p in palavras if _afirma(p) or p in _OFERECIDO]
    sobram = [p for p in palavras if p not in afirmam and p not in _ENCHIMENTO]
    if afirmam and not sobram:
        return True
    return None if len(palavras) <= PALAVRAS_PARA_IA else False


def aceite_por_ia(texto: str, convite: str) -> bool | None:
    """Pergunta à IA se a resposta curta aceitou o convite. None se ela falhar."""

    try:
        import server

        client = server._openai_chat_client()
        if not client:
            return None
        pedido = (
            "Um assistente de festival perguntou no WhatsApp:\n"
            f"\"{str(convite)[:300]}\"\n"
            "A pessoa respondeu (pode ter erro de digitação ou ser transcrição de áudio):\n"
            f"\"{str(texto)[:120]}\"\n"
            "A pessoa aceitou receber o que foi oferecido? Responda só SIM ou NAO."
        )
        resposta = client.chat.completions.create(
            **server._chat_completion_kwargs([{"role": "user", "content": pedido}], max_output_tokens=5)
        )
        veredito = _normalizar(resposta.choices[0].message.content or "")
    except Exception as exc:  # noqa: BLE001 - sem IA, a dúvida vira não
        logger.warning("Aceite por IA indisponível | erro=%s", type(exc).__name__)
        return None
    if veredito.startswith("sim"):
        return True
    if veredito.startswith("nao"):
        return False
    return None


def aceitou(texto: str, convite: str, usar_ia: bool = True) -> bool:
    """A resposta aceitou o convite? Regra primeiro; IA só na dúvida."""

    decisao = aceite_por_regra(texto)
    if decisao is None and usar_ia:
        decisao = aceite_por_ia(texto, convite)
    return bool(decisao)
