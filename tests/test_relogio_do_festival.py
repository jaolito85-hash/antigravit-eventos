"""A IA só usa o relógio para "quem toca agora" durante o festival.

Medido em 22/09/2026: com a hora atual no prompt e sem a data do evento, a
IA olhava o relógio de terça e dizia "esse já passou" sobre um show de sábado.
"""

import unittest
from datetime import datetime
from unittest import mock

import server

INICIO = "2026-09-26T18:30:00+00:00"  # 15:30 em Londrina
FIM = "2026-09-27T07:00:00+00:00"     # 04:00 em Londrina


def _linha(agora):
    with mock.patch.object(server.EVENT_STORE, "event_window", return_value=(INICIO, FIM)):
        return server._linha_do_relogio(datetime.fromisoformat(agora).astimezone(server._FUSO_SAO_PAULO))


class RelogioDoFestivalTests(unittest.TestCase):
    def test_antes_do_festival_nada_passou(self):
        linha = _linha("2026-09-22T20:16:00-03:00")
        self.assertIn("NOT started yet", linha)
        self.assertIn("never say an act already played", linha)
        self.assertIn("26/09/2026 15:30", linha)

    def test_durante_o_festival_o_relogio_vale(self):
        linha = _linha("2026-09-26T22:10:00-03:00")
        self.assertIn("happening right now", linha)
        self.assertNotIn("NOT started", linha)

    def test_depois_do_festival_tudo_e_passado(self):
        linha = _linha("2026-09-28T10:00:00-03:00")
        self.assertIn("already over", linha)

    def test_sem_janela_no_banco_sobra_so_o_relogio(self):
        with mock.patch.object(server.EVENT_STORE, "event_window", side_effect=RuntimeError("fora")):
            linha = server._linha_do_relogio(datetime.fromisoformat("2026-09-22T20:16:00-03:00"))
        self.assertIn("Current local time", linha)
        self.assertNotIn("festival runs", linha)

    def test_janela_ilegivel_sobra_so_o_relogio(self):
        with mock.patch.object(server.EVENT_STORE, "event_window", return_value=(None, "x")):
            linha = server._linha_do_relogio(datetime.fromisoformat("2026-09-22T20:16:00-03:00"))
        self.assertNotIn("festival runs", linha)

    def test_juntar_fichas_sem_guia_fica_faq(self):
        ficha = server.juntar_fichas(
            {"id": "a", "question": "A?", "answer": "1", "kind": "faq", "image_url": "x"},
            {"id": "b", "question": "B?", "answer": "2", "kind": "faq"},
        )
        self.assertEqual(ficha["kind"], "faq")
        self.assertEqual(ficha["answer"], "1\n\n2")
        self.assertIsNone(ficha["image_url"])


if __name__ == "__main__":
    unittest.main()
