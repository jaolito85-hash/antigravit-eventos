"""Line-up com as artes oficiais dos três palcos (pedido de 26/09).

Pergunta geral ("qual o line-up?") recebe as três artes, com a chamada fixa
na legenda da primeira. Pergunta de um palco recebe só aquele palco e o
convite; "quero" em seguida manda os palcos que faltaram.
"""

import unittest
from datetime import datetime, timezone
from unittest import mock

import worker

try:
    from test_worker import LIBERADO, FakeStore, _message
except ImportError:  # rodado como tests.test_lineup_banners
    from tests.test_worker import LIBERADO, FakeStore, _message

TROPICAL = "https://cdn.exemplo/tropical.png"
HYPE = "https://cdn.exemplo/hype.png"
LAB = "https://cdn.exemplo/lab.png"


def _palco(nome, arte):
    return {
        "id": nome, "question": f"Line-up do Palco {nome}", "answer": f"PALCO {nome.upper()}",
        "kind": "lineup", "scope": "Todos os ingressos", "image_url": arte,
        "keywords": [], "priority": 50, "active": True,
    }


# Fora de ordem de propósito: a resposta põe o Tropical primeiro.
LAB_F, HYPE_F, TROPICAL_F = _palco("Lab", LAB), _palco("Hype", HYPE), _palco("Tropical", TROPICAL)
GERAL = {
    "id": "geral", "question": "Qual é o line-up completo do festival?", "answer": "grade",
    "kind": "lineup", "scope": "lineup-geral", "image_url": None,
    "keywords": [], "priority": 40, "active": True,
}
FICHAS = [LAB_F, GERAL, HYPE_F, TROPICAL_F]


def _agora():
    return datetime.now(timezone.utc).isoformat()


class StoreDoLineup(FakeStore):
    def __init__(self, thread=None, **kw):
        super().__init__(**kw)
        self.imagens = []
        self.thread = {"messages": thread or []}

    def conversation_thread(self, _h, limit=8):
        return self.thread

    def enqueue_image(self, message, media_url, caption, feedback_id=None, chave="banner",
                      atraso_segundos=0):
        self.imagens.append((media_url, caption, chave))
        self.atrasos = getattr(self, "atrasos", []) + [atraso_segundos]


class ArtesDoLineupTests(unittest.TestCase):
    def test_ordem_tropical_hype_lab_e_sem_a_ficha_geral(self):
        with mock.patch.object(worker, "_fichas_ativas", return_value=FICHAS):
            self.assertEqual(worker.artes_do_lineup(), [TROPICAL, HYPE, LAB])

    def test_palco_sem_arte_fica_de_fora(self):
        sem_arte = {**LAB_F, "image_url": ""}
        with mock.patch.object(worker, "_fichas_ativas", return_value=[sem_arte, HYPE_F]):
            self.assertEqual(worker.artes_do_lineup(), [HYPE])


class RespostaDoLineupTests(unittest.TestCase):
    def setUp(self):
        for alvo, valor in (
            ("moderar_texto", LIBERADO),
            ("_atendimento_aprovado", False),
            ("_classify", ("Neutro", "Experiência Geral", "N/A")),
            ("_fichas_ativas", FICHAS),
        ):
            p = mock.patch.object(worker, alvo, return_value=valor)
            p.start()
            self.addCleanup(p.stop)

    def _triagem(self, ficha):
        return {"tipo": "relato", "urgencia": "Neutro", "ficha": ficha, "setor": None, "lugar": None}

    def test_pergunta_geral_recebe_as_tres_artes_com_a_chamada_na_primeira(self):
        store = StoreDoLineup(count=2)
        with mock.patch.object(worker, "triar_mensagem", return_value=self._triagem(GERAL)), \
                mock.patch.object(worker, "_compose_reply", return_value="nunca usado") as compor:
            worker.process_inbox(store, _message(content="qual o line up?"))
        self.assertEqual([i[0] for i in store.imagens], [TROPICAL, HYPE, LAB])
        self.assertEqual(store.imagens[0][1], worker.CHAMADA_LINEUP)
        self.assertEqual([i[1] for i in store.imagens[1:]], ["", ""])
        # Uma chave por imagem, senão a fila descarta a segunda como repetição.
        self.assertEqual(len({i[2] for i in store.imagens}), 3)
        # Espaçadas, para a Meta entregar na ordem (26/09 chegou Hype primeiro).
        passo = worker.SEGUNDOS_ENTRE_ARTES
        self.assertEqual(store.atrasos, [0, passo, 2 * passo])
        self.assertEqual(store.responses, [])
        compor.assert_not_called()

    def test_chamada_em_negrito_com_musica_e_rock(self):
        self.assertTrue(worker.CHAMADA_LINEUP.startswith("*"))
        self.assertIn("🎶", worker.CHAMADA_LINEUP)
        self.assertIn("🤘", worker.CHAMADA_LINEUP)

    def test_pergunta_de_um_palco_recebe_so_ele_e_o_convite(self):
        store = StoreDoLineup(count=2)
        with mock.patch.object(worker, "triar_mensagem", return_value=self._triagem(HYPE_F)):
            worker.process_inbox(store, _message(content="quem toca no hype?"))
        self.assertEqual(len(store.imagens), 1)
        arte, legenda, _ = store.imagens[0]
        self.assertEqual(arte, HYPE)
        self.assertIn(worker.CHAMADA_PALCO, legenda)
        self.assertIn(worker.PERGUNTA_LINEUP_COMPLETO, legenda)
        self.assertEqual(store.responses, [])

    def test_quero_depois_do_convite_manda_os_outros_dois_palcos(self):
        thread = [
            {"direction": "in", "content": "quem toca no hype?", "at": _agora()},
            {"direction": "out", "content": f"{worker.CHAMADA_PALCO}\n\n{worker.PERGUNTA_LINEUP_COMPLETO}",
             "media_url": HYPE, "at": _agora()},
            {"direction": "in", "content": "quero", "at": _agora()},
        ]
        store = StoreDoLineup(thread=thread, count=2)
        with mock.patch.object(worker, "triar_mensagem") as triar:
            worker.process_inbox(store, _message(content="quero"))
        self.assertEqual([i[0] for i in store.imagens], [TROPICAL, LAB])
        self.assertEqual(len({i[2] for i in store.imagens}), 2)
        self.assertEqual(store.atrasos, [0, worker.SEGUNDOS_ENTRE_ARTES])
        self.assertEqual(store.responses, [])
        self.assertFalse(getattr(store, "feedback", None))  # sem chamado
        triar.assert_not_called()

    def test_quero_responde_o_convite_mais_recente(self):
        """Cardápio antes e line-up depois: o "quero" é do line-up."""

        thread = [
            {"direction": "out", "content": "Quer o cardápio completo de bebidas? Responde *QUERO*", "at": _agora()},
            {"direction": "out", "content": worker.PERGUNTA_LINEUP_COMPLETO, "media_url": LAB, "at": _agora()},
        ]
        store = StoreDoLineup(thread=thread)
        self.assertEqual(worker._oferta_aceita(store, "h", "quero"), "lineup")
        self.assertEqual(worker._oferta_aceita(store, "h", "manda o line-up"), "lineup")

    def test_quero_sem_convite_nao_e_line_up(self):
        store = StoreDoLineup(thread=[{"direction": "out", "content": "Tô aqui!", "at": _agora()}])
        self.assertIsNone(worker._oferta_aceita(store, "h", "quero"))

    def test_relato_urgente_nunca_recebe_line_up(self):
        store = StoreDoLineup(count=2)
        triagem = {**self._triagem(GERAL), "urgencia": "Urgente"}
        with mock.patch.object(worker, "triar_mensagem", return_value=triagem), \
                mock.patch.object(worker, "_classify", return_value=("Urgente", "Segurança & Organização", "N/A")), \
                mock.patch.object(worker, "_compose_reply", return_value="Registrei."):
            worker.process_inbox(store, _message(content="briga perto do palco hype"))
        self.assertEqual(store.imagens, [])


class FilaEspacadaTests(unittest.TestCase):
    def _gravar(self, **kw):
        from event_store import EventStore

        store = EventStore.__new__(EventStore)
        linhas = []
        tabela = mock.MagicMock()
        tabela.upsert.side_effect = lambda row, **_: linhas.append(row) or tabela
        cliente = mock.MagicMock()
        cliente.table.return_value = tabela
        with mock.patch.object(EventStore, "event_id", return_value="ev"), \
                mock.patch.object(EventStore, "_get_client", return_value=cliente):
            store.enqueue_image(
                {"id": "m1", "channel_account_id": "c", "sender": "5543"},
                TROPICAL, "", **kw,
            )
        return linhas[0]

    def test_imagem_com_atraso_so_sai_depois(self):
        antes = datetime.now(timezone.utc)
        linha = self._gravar(chave="lineup1", atraso_segundos=3)
        quando = datetime.fromisoformat(linha["next_attempt_at"])
        self.assertGreaterEqual((quando - antes).total_seconds(), 2.9)
        self.assertEqual(linha["idempotency_key"], "inbox:m1:lineup1")

    def test_sem_atraso_fica_com_o_padrao_do_banco(self):
        self.assertNotIn("next_attempt_at", self._gravar())


if __name__ == "__main__":
    unittest.main()
