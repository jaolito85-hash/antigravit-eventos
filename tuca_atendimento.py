"""Casos de atendimento aprovados pela organização nas imagens de 24/09/2026.

Respostas de conteúdo ficam no JSON versionado. Reconhecimento conservador evita
que uma dúvida simples abra chamado ou uma reclamação legítima vire strike.
"""

import json
import re
import unicodedata
from pathlib import Path

TEXTS = json.loads(
    (Path(__file__).parent / "data" / "tuca_atendimento_aprovado.json").read_text(
        encoding="utf-8"
    )
)


def normal(text):
    text = "".join(
        c
        for c in unicodedata.normalize("NFD", (text or "").lower())
        if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", text)).strip()


FOOD = re.compile(
    r"(?:(?:eu )?(?:to|tou|estou|estamos|tamo) com (?:muita )?fome|(?:onde|aonde) (?:eu )?(?:posso |tem (?:algo |alguma coisa )?(?:pra |para )?)?comer|quero comer(?: alguma coisa)?)(?: (?:aqui )?(?:na|no) (?:pista|lounge|backstage))?"
)
BATH = re.compile(
    r"(?:onde|aonde) (?:fica|ficam|tem|e|sao) (?:o |os |um |uma )?(?:banheiro|banheiros|sanitario|sanitarios)(?: mais proximos?| (?:da|do|na|no) (?:pista|lounge|backstage))?"
)
REPLAY = re.compile(
    r"(?:vou conseguir ver (?:o )?show depois|(?:vai ter|tem|tera) (?:transmissao|retransmissao|gravacao|reprise)(?: (?:do|dos) shows?)? depois|perdi (?:o )?show(?: (?:do|da|de) [a-z0-9 ]{1,45})? (?:vai ter|tem|tera) (?:transmissao|retransmissao|reprise|gravacao) depois|(?:onde|quando) (?:posso |vou poder )?(?:ver|assistir)(?: (?:o|ao))? show (?:depois|gravado))"
)
COMPLAINT = re.compile(
    r"(?:(?:esse|este|o) (?:evento|festival|show) (?:ta|esta|e) (?:uma? )?(?:merda|lixo|porcaria|horrivel|pessimo|ruim)|(?:vcs|voces) (?:sao|estao) (?:pessimos|horriveis|ruins)|(?:que |uma? )?(?:porcaria|merda)|(?:nao gostei|odiei)(?: d(?:o|esse) (?:evento|festival|show))?)"
)


def is_candidate(text):
    value = normal(text)
    return bool(
        FOOD.fullmatch(value)
        or BATH.fullmatch(value)
        or REPLAY.fullmatch(value)
        or COMPLAINT.fullmatch(value)
        or value == "lixo"
        or re.fullmatch(
            r"(?:(?:eu )?(?:estou|to|tou) )?(?:na |no )?(?:pista|lounge|backstage)",
            value,
        )
    )


def area(location):
    label = normal(location.get("name", "") if isinstance(location, dict) else location)
    # A área vem após o separador nos nomes de setores da planta.
    for word in ("backstage", "lounge", "pista"):
        if re.search(r"\b" + word + r"\b", label):
            return word
    return None


def resolve(text, history=None, location=None):
    value = normal(text)
    history = history or []
    # O worker fornece só mensagens anteriores; os motores locais retiram a atual.
    recent = history[-8:]
    last_out = next(
        (
            normal(m.get("content"))
            for m in reversed(recent)
            if m.get("direction") == "out"
        ),
        "",
    )
    prior_complaint = any(
        COMPLAINT.fullmatch(normal(m.get("content")))
        for m in recent
        if m.get("direction") == "in"
    )
    context_food = any(
        normal(TEXTS[key]) in last_out
        for key in ("food_unknown", "food_pista", "food_lounge", "food_backstage")
    )
    food_follow = context_food and re.fullmatch(
        r"(?:(?:eu )?(?:estou|to|tou) )?(?:na |no )?(pista|lounge|backstage)", value
    )
    kind = None
    reply = None
    register = False
    known_area = area(location)
    if FOOD.fullmatch(value) or food_follow:
        kind = "alimentacao"
        explicit = re.search(r"\b(?:na|no) (pista|lounge|backstage)$", value)
        target = (
            food_follow.group(1)
            if food_follow
            else explicit.group(1) if explicit else known_area
        )
        reply = TEXTS["food_" + target] if target else TEXTS["food_unknown"]
    elif BATH.fullmatch(value):
        kind = "banheiro"
        reply = TEXTS["bathroom"]
    elif REPLAY.fullmatch(value):
        kind = "gravacao"
        reply = TEXTS["replay"]
    elif COMPLAINT.fullmatch(value) or (value == "lixo" and prior_complaint):
        kind = "reclamacao"
        register = True
        reply = (
            TEXTS["complaint_followup"] if prior_complaint else TEXTS["complaint_first"]
        )
    elif value == "lixo":
        kind = "esclarecimento"
        reply = TEXTS["trash_ambiguous"]
    if not kind:
        return None
    return {
        "kind": kind,
        "reply": reply,
        "register": register,
        "urgency": "Neutro",
        "source": "Orientação aprovada pela organização em 24/09/2026",
    }


def respond_lab(state, snapshot, content, kind):
    """Mesmo contrato dos motores; só registra no armazenamento simulado."""
    if kind != "text":
        return None
    import time
    import server

    code, text = server._extract_sector(content)
    location = next((s for s in snapshot["sectors"] if s["code"] == code), None)
    remembered = state.get("location")
    if not location and remembered and time.time() - remembered.get("at", 0) < 300:
        location = remembered
    result = resolve(text, state.get("history"), location)
    if not result:
        return None
    state.setdefault("history", []).append({"direction": "in", "content": content})
    state.setdefault("cards", [])
    if location:
        state["location"] = {**location, "at": time.time()}
    if result["register"]:
        state["cards"].append(
            {
                "id": len(state["cards"]) + 1,
                "content": text,
                "urgency": "Neutro",
                "at": time.time(),
                "location": location,
            }
        )
    state["history"].append({"direction": "out", "content": result["reply"]})
    return {
        "messages": [{"type": "text", "content": result["reply"]}],
        "status": "processed",
        "urgency": "Neutro",
        "sector": (location or {}).get("name"),
        "action": (
            "Reclamação registrada (simulação)"
            if result["register"]
            else "Orientação sem chamado"
        ),
        "cards": len(state["cards"]),
        "sources": [
            {
                "id": "aprovado-" + result["kind"],
                "title": result["source"],
                "quote": result["reply"],
            }
        ],
        "notes": [
            "Resposta aprovada aplicada em código; nenhum modelo de IA decidiu esta resposta."
        ],
        "method": "Atendimento aprovado pela organização",
    }
