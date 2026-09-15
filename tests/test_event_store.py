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
