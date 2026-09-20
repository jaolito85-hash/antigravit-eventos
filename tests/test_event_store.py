"""Regressões da camada de persistência do evento."""

from __future__ import annotations

import threading
import unittest
from unittest.mock import patch

from event_store import EventStore


class _Query:
    """Consulta mínima compatível com o encadeamento do cliente Supabase."""

    data = [{"id": "event-id"}]

    def select(self, _columns: str) -> "_Query":
        return self

    def eq(self, _column: str, _value: str) -> "_Query":
        return self

    def limit(self, _value: int) -> "_Query":
        return self

    def execute(self) -> "_Query":
        return self


class _Client:
    def table(self, _name: str) -> _Query:
        return _Query()


class EventStoreTests(unittest.TestCase):
    """Regressões da sincronização usada pelo cliente Supabase."""

    def test_event_id_can_initialize_client_inside_lock(self) -> None:
        """A primeira resolução não pode bloquear o processo indefinidamente."""

        store = EventStore()
        result: list[str] = []
        with patch.object(store, "_get_client", return_value=_Client()):
            thread = threading.Thread(
                target=lambda: result.append(store.event_id()),
                daemon=True,
            )
            thread.start()
            thread.join(timeout=1)

        self.assertFalse(thread.is_alive())
        self.assertEqual(result, ["event-id"])


class _UpdateQuery:
    """Captura o update enviado ao Supabase, sem tocar na rede."""

    def __init__(self, registro: list[dict]) -> None:
        self._registro = registro

    def update(self, valores: dict) -> "_UpdateQuery":
        self._registro.append(valores)
        return self

    def eq(self, _column: str, _value: str) -> "_UpdateQuery":
        return self

    def execute(self) -> "_UpdateQuery":
        return self


class _UpdateClient:
    def __init__(self) -> None:
        self.updates: list[dict] = []

    def table(self, _name: str) -> _UpdateQuery:
        return _UpdateQuery(self.updates)


class DeliveryStatusTests(unittest.TestCase):
    """Regressões do estado de entrega vindo do webhook da Meta."""

    def _aplicar(self, status: str, erro: str | None = None) -> dict:
        from meta_whatsapp import MessageStatus

        store = EventStore()
        client = _UpdateClient()
        with patch.object(store, "_get_client", return_value=client):
            store.apply_message_statuses([
                MessageStatus(
                    provider_message_id="wamid.X",
                    status=status,
                    occurred_at="2026-09-20T00:03:55+00:00",
                    error=erro,
                )
            ])
        return client.updates[0]

    def test_falha_da_meta_nao_volta_para_a_fila(self) -> None:
        """Reenviar o que a Meta ja aceitou duplicaria a resposta no WhatsApp."""

        update = self._aplicar("failed", erro="131047")

        # pending_outbox busca queued e failed: "failed" aqui virava laco.
        self.assertEqual(update["delivery_status"], "cancelled")
        self.assertEqual(update["failed_at"], "2026-09-20T00:03:55+00:00")
        self.assertEqual(update["last_error"], "131047")

    def test_estados_de_sucesso_seguem_iguais(self) -> None:
        """So a falha muda de nome; o resto do ciclo continua como era."""

        for estado in ("sent", "delivered", "read"):
            update = self._aplicar(estado)
            self.assertEqual(update["delivery_status"], estado)
            self.assertIn(f"{estado}_at", update)
