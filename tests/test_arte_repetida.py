"""Arte que a pessoa acabou de receber não vai de novo: a resposta vai em texto.

Produção, 25/09 20:17: "tem seda ?" recebeu a arte da loja, e "qto custa ?"
e "quanto custa ?" receberam a MESMA arte, três vezes seguidas. A memória
achou a ficha certa; a regra "ficha com imagem manda só a imagem" repetiu a
imagem. Agora a imagem mandada nos últimos 30 minutos é lembrada, a
pergunta seguinte é respondida em texto a partir da ficha, e o histórico
diz à IA qual arte já foi.
"""

import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import server
import worker
from event_store import SEM_LEGENDA

try:
    from test_worker import LIBERADO, FakeStore, _message
except ImportError:  # rodado como tests.test_arte_repetida
    from tests.test_worker import LIBERADO, FakeStore, _message

ARTE = "https://cdn.exemplo/loja.jpg"
SEDA = {
    "id": "seda", "question": "Loja oficial: copos, tirantes, camisetas, moletom e seda: preços",
    "answer": "Na Loja Oficial, na pista, perto da feirinha. Seda Papelito R$ 5 a unidade ou 3 por R$ 10.",
    "kind": "activation", "image_url": ARTE, "keywords": [], "priority": 50, "active": True,
}


def _agora(minutos_atras=0):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutos_atras)).isoformat()


class HistoricoComNomeDaArteTests(unittest.TestCase):
    def test_a_arte_enviada_aparece_com_o_titulo_da_ficha(self):
        falas = [
            {"direction": "in", "content": "tem seda?"},
            {"direction": "out", "content": SEM_LEGENDA, "media_url": ARTE},
        ]
        texto = server.historico_em_texto(falas, artes={ARTE: SEDA["question"]})
        self.assertEqual(texto, f"Pessoa: tem seda?\nTuca: [mandou a arte: {SEDA['question']}]")

    def test_arte_com_legenda_mostra_a_arte_e_a_legenda(self):
        falas = [{"direction": "out", "content": "Quer o cardápio completo? Responde QUERO", "media_url": ARTE}]
        texto = server.historico_em_texto(falas, artes={ARTE: "Coco Leve: preços"})
        self.assertEqual(texto, "Tuca: [mandou a arte: Coco Leve: preços] Quer o cardápio completo? Responde QUERO")

    def test_foto_da_pessoa_nao_vira_arte_do_tuca(self):
        falas = [{"direction": "in", "content": "olha isso", "media_url": "https://cdn/foto.jpg"}]
        self.assertEqual(server.historico_em_texto(falas, artes={}), "Pessoa: olha isso")

    def test_arte_desconhecida_continua_com_a_descricao_generica(self):
        falas = [{"direction": "out", "content": SEM_LEGENDA, "media_url": "https://outra"}]
        self.assertEqual(server.historico_em_texto(falas, artes={ARTE: "x"}), f"Tuca: {server.IMAGEM_NO_HISTORICO}")


class ArtesJaEnviadasTests(unittest.TestCase):
    def test_so_a_imagem_recente_do_tuca_conta(self):
        falas = [
            {"direction": "out", "content": SEM_LEGENDA, "media_url": ARTE, "at": _agora(2)},
            {"direction": "out", "content": SEM_LEGENDA, "media_url": "https://cdn.exemplo/velha.jpg", "at": _agora(90)},
            {"direction": "in", "content": "foto", "media_url": "https://cdn.exemplo/da-pessoa.jpg", "at": _agora(1)},
            {"direction": "out", "content": "texto sem imagem", "at": _agora(1)},
        ]
        self.assertEqual(worker._artes_ja_enviadas(falas), {ARTE})

    def test_data_ilegivel_conta_como_recente(self):
        falas = [{"direction": "out", "content": SEM_LEGENDA, "media_url": ARTE, "at": "ontem"}]
        self.assertEqual(worker._artes_ja_enviadas(falas), {ARTE})

    def test_janela_de_trinta_minutos(self):
        falas = [{"direction": "out", "content": SEM_LEGENDA, "media_url": ARTE, "at": _agora(29)}]
        self.assertEqual(worker._artes_ja_enviadas(falas), {ARTE})
        falas[0]["at"] = _agora(31)
        self.assertEqual(worker._artes_ja_enviadas(falas), set())


class StoreComArte(FakeStore):
    def __init__(self, minutos_atras, **kw):
        super().__init__(**kw)
        self.imagens = []
        self.thread = {"messages": [
            {"direction": "in", "content": "tem seda?", "at": _agora(minutos_atras + 1)},
            {"direction": "out", "content": SEM_LEGENDA, "media_url": ARTE, "at": _agora(minutos_atras)},
            {"direction": "in", "content": "quanto custa?", "at": _agora(0)},
        ]}

    def conversation_thread(self, _h, limit=8):
        return self.thread

    def enqueue_image(self, message, media_url, caption, feedback_id=None):
        self.imagens.append(media_url)


class WorkerNaoRepeteArteTests(unittest.TestCase):
    def setUp(self):
        for alvo, valor in (
            ("moderar_texto", LIBERADO),
            ("_atendimento_aprovado", False),
            ("_classify", ("Neutro", "Experiência Geral", "N/A")),
            ("_fichas_ativas", [SEDA]),
        ):
            p = mock.patch.object(worker, alvo, return_value=valor)
            p.start()
            self.addCleanup(p.stop)
        self.triagem = {"tipo": "relato", "urgencia": "Neutro", "ficha": SEDA, "setor": None, "lugar": None, "continuacao": True}

    def test_pergunta_completa_recebe_a_arte_mesmo_recente(self):
        """"Sabe se tem água de coco?" 20 min depois da arte recebeu texto (25/09): a arte vai."""

        store = StoreComArte(minutos_atras=20, count=2)
        with mock.patch.object(worker, "triar_mensagem", return_value={**self.triagem, "continuacao": False}), \
                mock.patch.object(worker, "_compose_reply", return_value="nunca usado") as compor:
            worker.process_inbox(store, _message(content="sabe se tem seda?"))
        self.assertEqual(store.imagens, [ARTE])
        self.assertEqual(store.responses, [])
        compor.assert_not_called()

    def test_arte_recente_vira_resposta_em_texto_a_partir_da_ficha(self):
        store = StoreComArte(minutos_atras=1, count=2)
        with mock.patch.object(worker, "triar_mensagem", return_value=self.triagem), \
                mock.patch.object(worker, "_compose_reply", return_value="R$ 5 a unidade ou 3 por R$ 10 🦜") as compor:
            worker.process_inbox(store, _message(content="quanto custa?"))
        self.assertEqual(store.imagens, [])
        self.assertEqual(store.responses, ["R$ 5 a unidade ou 3 por R$ 10 🦜"])
        self.assertEqual(compor.call_args.kwargs["known"], SEDA)
        # A IA fica sabendo qual arte já foi, pelo histórico.
        self.assertIn(f"[mandou a arte: {SEDA['question']}]", compor.call_args.kwargs["historico"])

    def test_arte_antiga_vai_de_novo(self):
        store = StoreComArte(minutos_atras=45, count=2)
        with mock.patch.object(worker, "triar_mensagem", return_value=self.triagem), \
                mock.patch.object(worker, "_compose_reply", return_value="nunca usado") as compor:
            worker.process_inbox(store, _message(content="quanto custa?"))
        self.assertEqual(store.imagens, [ARTE])
        self.assertEqual(store.responses, [])
        compor.assert_not_called()


if __name__ == "__main__":
    unittest.main()
