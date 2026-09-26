"""Laboratório isolado: o worker atual escreve somente neste store em memória."""

from __future__ import annotations
import contextvars
import copy
import hashlib
import json
import time
import uuid
from contextlib import contextmanager
from typing import Any

SNAPSHOT = contextvars.ContextVar("tuca_lab_snapshot", default=None)
VERSION = "experimental-1"
MAX_TURNS = 60


def fingerprint(snapshot):
    return hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:12]


@contextmanager
def frozen(snapshot):
    import server

    a = SNAPSHOT.set(snapshot)
    b = server._CONFIG_PREVIEW.set(snapshot["config"])
    try:
        yield
    finally:
        server._CONFIG_PREVIEW.reset(b)
        SNAPSHOT.reset(a)


class MemoryStore:
    """Implementa o contrato do worker sem herdar EventStore ou cliente de rede."""

    def __init__(self, state, snapshot):
        self.state = state
        self.snapshot = snapshot
        self.responses = []
        self.error = None
        self.status = None
        self.card_id = None
        self.notes = []
        for key in ("history", "inbox", "cards"):
            state.setdefault(key, [])

    def claim_inbox(self, message):
        self.message = message
        self.state["inbox"].append(
            {
                "id": message["id"],
                "at": time.time(),
                "blocked": False,
                "sector_id": None,
            }
        )
        self.state["history"].append({"direction": "in", "content": message["content"]})
        return True

    def conversation_mode(self, *a):
        return "bot"

    def recent_sender_count(self, sender, minutes=10):
        return sum(x["at"] >= time.time() - 60 * minutes for x in self.state["inbox"])

    def recent_blocked_count(self, sender, minutes=10):
        return sum(
            x["blocked"] and x["at"] >= time.time() - 60 * minutes
            for x in self.state["inbox"]
        )

    def recent_sender_audio_count(self, *a):
        return 0

    def recent_event_count(self, *a):
        return 0

    def sector_by_code(self, code):
        return next(
            (x for x in self.snapshot["sectors"] if x.get("code") == code), None
        )

    def marcar_setor_do_inbox(self, mid, sid):
        self.state["inbox"][-1]["sector_id"] = sid

    def ultimo_setor_escaneado(self, sender, minutes=5):
        for row in reversed(self.state["inbox"]):
            if row.get("sector_id") and row["at"] >= time.time() - 60 * minutes:
                return next(
                    (
                        s
                        for s in self.snapshot["sectors"]
                        if str(s["id"]) == row["sector_id"]
                    ),
                    None,
                )
        return None

    def conversation_thread(self, sender, limit=8):
        return {"messages": self.state["history"][-limit:]}

    def create_feedback(self, **kw):
        self.card_id = len(self.state["cards"]) + 1
        card = {k: v for k, v in kw.items() if k != "message"}
        card.update(id=self.card_id, at=time.time(), status="aberto")
        self.state["cards"].append(card)
        return self.card_id

    def attach_location(self, sender, lat, lon, janela_minutos=60):
        cards = [
            c
            for c in self.state["cards"]
            if c["at"] >= time.time() - janela_minutos * 60
            and c["status"] != "resolvido"
        ]
        if not cards:
            return None
        card = cards[-1]
        card["coords"] = [lat, lon]
        self.card_id = card["id"]
        return card

    def enqueue_text(self, message, content, feedback_id=None):
        # A outbox real tem uma chave por mensagem. Preserve essa semântica.
        if any(x["type"] == "text" for x in self.responses):
            return
        self.responses.append({"type": "text", "content": content[:4096]})
        self.state["history"].append({"direction": "out", "content": content[:4096]})

    def enqueue_image(self, message, media_url, caption="", feedback_id=None, chave="banner"):
        self.responses.append({"type": "image", "url": media_url, "content": caption})
        # A arte entra no histórico com o endereço, como na conversa real:
        # é por ele que o "quero" do line-up sabe que palco já foi.
        self.state["history"].append(
            {"direction": "out", "content": caption or "[Imagem oficial]", "media_url": media_url}
        )

    def finish_inbox(self, mid, status="processed"):
        self.status = status

    def block_inbox(self, mid, reason):
        self.state["inbox"][-1]["blocked"] = True
        self.status = "blocked"
        self.notes.append(reason)

    def fail_inbox(self, message, error):
        self.error = type(error).__name__
        self.status = "failed"


def run_current(state, snapshot, content, kind):
    import worker

    store = MemoryStore(state, snapshot)
    message = {
        "id": str(uuid.uuid4()),
        "sender": "laboratorio",
        "sender_hash": "laboratorio",
        "channel_account_id": "laboratorio",
        "message_type": kind,
        "content": content,
        "attempts": 0,
    }
    with frozen(snapshot):
        worker.process_inbox(store, message)
    if store.error:
        raise RuntimeError("O motor atual falhou ao processar este teste.")
    card = next((x for x in state["cards"] if x["id"] == store.card_id), None)
    return {
        "messages": store.responses,
        "status": store.status,
        "urgency": (card or {}).get("urgency"),
        "sector": (
            "GPS recebido"
            if (card or {}).get("coords")
            else (
                (card or {}).get("region")
                if (card or {}).get("region") != "N/A"
                else None
            )
        ),
        "action": "Chamado simulado" if card else "Sem chamado",
        "cards": len(state["cards"]),
        "sources": [],
        "notes": store.notes,
        "method": "Worker atual deste código, com persistência simulada",
    }


def run_turn(engine, state, snapshot, content, kind):
    start = time.monotonic()
    if engine == "current":
        result = run_current(state, snapshot, content, kind)
    elif engine == "jev":
        from tuca_jev import respond

        with frozen(snapshot):
            result = respond(state, snapshot, content, kind)
    elif engine == "experimental":
        from tuca_experimental import respond

        with frozen(snapshot):
            result = respond(state, snapshot, content, kind)
    elif engine == "enxuto":
        from tuca_enxuto import respond

        with frozen(snapshot):
            result = respond(state, snapshot, content, kind)
    else:
        raise ValueError("Motor de teste inválido.")
    state["history"] = state.get("history", [])[-24:]
    state["turns"] = state.get("turns", 0) + 1
    result["elapsed_ms"] = round((time.monotonic() - start) * 1000)
    result["engine"] = engine
    result["simulated"] = True
    return result
