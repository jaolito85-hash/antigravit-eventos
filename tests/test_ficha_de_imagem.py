"""Ficha que responde com foto: a imagem é a resposta, o texto é cabeçalho.

Pedido do João em 23/09/2026. A produção sobe a foto do line-up do Palco Hype;
quando alguém pergunta pelo line-up, o Tuca manda a foto. Se quiser uma linha
antes dela, escreve, e essa linha sai em negrito, literal, sem a IA reescrever.
"""

import unittest
from unittest import mock

import server
import worker
from worker import process_inbox

LIBERADO = {"bloquear": False, "motivo": None, "origem": "teste"}

FICHA_SO_FOTO = {
    "id": "f1",
    "question": "Line-up do Palco Hype",
    "answer": "",
    "image_url": "https://bucket/lineup-hype.png",
    "kind": "lineup",
}
FICHA_COM_CABECALHO = {
    "id": "f2",
    "question": "Cardápio do Open Food",
    "answer": "Cardápio de hoje no Open Food 🍔",
    "image_url": "https://bucket/cardapio.png",
    "kind": "food",
}
FICHA_GERAL = {
    "id": "f4",
    "question": "Cardápio geral de bebidas",
    "answer": "Água R$ 8, Budweiser R$ 15...",
    "image_url": "https://bucket/cardapio-geral.jpg",
    "kind": "bar",
    "scope": "cardapio-geral",
}
FICHA_SEM_FOTO = {
    "id": "f3",
    "question": "Que horas abre o portão?",
    "answer": "Os portões abrem às 14h.",
    "image_url": None,
    "kind": "faq",
}


class FakeStore:
    def __init__(self):
        self.textos = []
        self.imagens = []

    def claim_inbox(self, _m):
        return True

    def conversation_mode(self, _s):
        return "bot"

    def recent_sender_count(self, _s, minutes=10):
        return 1

    def recent_sender_audio_count(self, _s, minutes=60):
        return 0

    def recent_blocked_count(self, _s, minutes=10):
        return 0

    def recent_event_count(self, minutes=1):
        return 0

    def sector_by_code(self, _c):
        return None

    def marcar_setor_do_inbox(self, *a):
        pass

    def ultimo_setor_escaneado(self, *a, **k):
        return None

    def create_feedback(self, **kwargs):
        return 7

    def enqueue_text(self, _message, content, feedback_id=None):
        self.textos.append(content)

    def enqueue_image(self, _message, media_url, caption, feedback_id=None):
        self.imagens.append({"url": media_url, "caption": caption})

    def finish_inbox(self, _id, status="processed"):
        pass

    def block_inbox(self, _id, motivo):
        pass

    def fail_inbox(self, _m, erro):
        raise AssertionError(f"worker falhou: {erro}")


def _mensagem(texto):
    return {
        "id": "inbox-1", "sender": "5543999999999", "sender_hash": "hash",
        "channel_account_id": "phone", "message_type": "text",
        "content": texto, "media_id": None, "attempts": 0,
    }


class FormatoDaRespostaTests(unittest.TestCase):
    def setUp(self):
        for alvo in ("generate_ai_response", "classificar_com_ia"):
            p = mock.patch.object(server, alvo, lambda *a, **k: None)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(
            worker, "compose_smalltalk",
            lambda _c, ja_falou=False, usar_ia=True, historico="": "OI",
        )
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(worker, "moderar_texto", return_value=LIBERADO)
        p.start()
        self.addCleanup(p.stop)

    def _rodar(self, ficha, texto="qual é o line up do hype?"):
        store = FakeStore()
        with mock.patch.object(
            server, "triar_mensagem_ia",
            return_value={"tipo": "relato", "urgencia": "Neutro", "ficha": ficha},
        ):
            process_inbox(store, _mensagem(texto))
        return store

    def test_ficha_so_com_foto_manda_so_a_foto(self):
        """Sem texto cadastrado, a pessoa recebe a imagem e nada mais."""

        store = self._rodar(FICHA_SO_FOTO)
        self.assertEqual(store.textos, [], "não pode sair texto nenhum antes da foto")
        self.assertEqual(len(store.imagens), 1)
        self.assertEqual(store.imagens[0]["url"], FICHA_SO_FOTO["image_url"])

    def test_ficha_com_texto_e_foto_tambem_manda_so_a_foto(self):
        """Desde 25/09 o texto cadastrado não vai antes da foto: a arte é a resposta."""

        store = self._rodar(FICHA_COM_CABECALHO, "tem cardápio?")
        self.assertEqual(store.textos, [], "não pode sair texto nenhum antes da foto")
        self.assertEqual(len(store.imagens), 1)

    def test_relato_urgente_nunca_recebe_a_arte_do_guia(self):
        """"Falta cerveja no bar" casou com o cardápio de cervejas: vai o registro, não o cardápio."""

        store = FakeStore()
        cardapio = {**FICHA_COM_CABECALHO, "kind": "bar", "question": "Cervejas: cardápio e preços"}
        with mock.patch.object(
            server, "triar_mensagem_ia",
            return_value={"tipo": "relato", "urgencia": "Urgente", "ficha": cardapio},
        ):
            process_inbox(store, _mensagem("falta cerveja no bar"))
        self.assertEqual(store.imagens, [])
        self.assertEqual(len(store.textos), 1)
        self.assertNotIn("Cardápio", store.textos[0])
        self.assertIn("destacamos", store.textos[0])

    def test_arte_de_bebida_vem_com_convite_para_o_cardapio_completo_na_legenda(self):
        """Cervejas, Red Bull ou drinks: a arte sai com "quer o cardápio completo?" de legenda.

        Numa mensagem só a ordem é garantida. Em duas (foto e depois texto),
        a Meta entregou o texto antes da foto em 25/09.
        """

        cervejas = {"id": "f5", "question": "Cervejas: preços", "answer": "Budweiser R$ 15",
                    "image_url": "https://bucket/cervejas.jpg", "kind": "bar", "scope": None}
        with mock.patch.object(worker, "ficha_cardapio_geral", return_value=FICHA_GERAL):
            store = self._rodar(cervejas, "quanto custa a budweiser?")
        self.assertEqual(store.imagens, [{"url": "https://bucket/cervejas.jpg", "caption": worker.PERGUNTA_CARDAPIO_COMPLETO}])
        self.assertEqual(store.textos, [])

    def test_cardapio_geral_nao_se_oferece(self):
        with mock.patch.object(worker, "ficha_cardapio_geral", return_value=FICHA_GERAL):
            store = self._rodar(FICHA_GERAL, "qual o cardápio de bebidas?")
        self.assertEqual(store.imagens, [{"url": FICHA_GERAL["image_url"], "caption": ""}])
        self.assertEqual(store.textos, [])

    def test_sem_cardapio_geral_publicado_nao_ha_convite(self):
        cervejas = {"id": "f5", "question": "Cervejas: preços", "answer": "Budweiser R$ 15",
                    "image_url": "https://bucket/cervejas.jpg", "kind": "bar", "scope": None}
        with mock.patch.object(worker, "ficha_cardapio_geral", return_value=None):
            store = self._rodar(cervejas, "quanto custa a budweiser?")
        self.assertEqual(store.imagens, [{"url": "https://bucket/cervejas.jpg", "caption": ""}])
        self.assertEqual(store.textos, [])

    def test_ficha_sem_foto_segue_como_sempre(self):
        """Quem não tem imagem continua no caminho antigo, com resposta em texto."""

        store = self._rodar(FICHA_SEM_FOTO, "que horas abre?")
        self.assertEqual(len(store.textos), 1)
        self.assertEqual(store.imagens, [])




if __name__ == "__main__":
    unittest.main()


class CardapioCompletoTests(unittest.TestCase):
    """"Quero" logo depois da pergunta manda o cardápio geral; sem a pergunta, segue normal."""

    def setUp(self):
        for alvo in ("generate_ai_response", "classificar_com_ia"):
            p = mock.patch.object(server, alvo, lambda *a, **k: None)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(worker, "moderar_texto", return_value=LIBERADO)
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(worker, "ficha_cardapio_geral", return_value=FICHA_GERAL)
        p.start()
        self.addCleanup(p.stop)

    def _store(self, ultima_fala_do_tuca):
        store = FakeStore()
        store.conversation_thread = lambda _h, limit=6: {"messages": [
            {"direction": "in", "content": "quanto custa a budweiser?"},
            {"direction": "out", "content": ultima_fala_do_tuca},
            {"direction": "in", "content": "quero"},
        ]}
        return store

    def test_quero_depois_da_pergunta_manda_o_geral(self):
        store = self._store(worker.PERGUNTA_CARDAPIO_COMPLETO)
        with mock.patch.object(server, "triar_mensagem_ia") as triagem:
            for resposta in ("quero", "Sim!", "manda", "pode mandar", "o cardápio"):
                store.imagens.clear()
                process_inbox(store, _mensagem(resposta))
                self.assertEqual([i["url"] for i in store.imagens], [FICHA_GERAL["image_url"]], resposta)
        triagem.assert_not_called()
        self.assertEqual(store.textos, [])

    def test_quero_vale_mesmo_com_a_foto_chegando_depois_da_pergunta(self):
        """A foto e o texto saem separados e a hora de envio pode inverter a ordem (25/09)."""

        store = FakeStore()
        store.conversation_thread = lambda _h, limit=6: {"messages": [
            {"direction": "in", "content": "tem agua de coco pra vender?"},
            {"direction": "out", "content": worker.PERGUNTA_CARDAPIO_COMPLETO},
            {"direction": "out", "content": "[imagem]", "media_url": "https://bucket/coco.jpg"},
            {"direction": "in", "content": "quero"},
        ]}
        with mock.patch.object(server, "triar_mensagem_ia") as triagem:
            process_inbox(store, _mensagem("quero"))
        self.assertEqual([i["url"] for i in store.imagens], [FICHA_GERAL["image_url"]])
        triagem.assert_not_called()

    def test_quero_depois_da_arte_com_a_pergunta_de_legenda(self):
        store = FakeStore()
        store.conversation_thread = lambda _h, limit=6: {"messages": [
            {"direction": "in", "content": "tem agua de coco pra vender?"},
            {"direction": "out", "content": worker.PERGUNTA_CARDAPIO_COMPLETO, "media_url": "https://bucket/coco.jpg"},
            {"direction": "in", "content": "quero"},
        ]}
        with mock.patch.object(server, "triar_mensagem_ia") as triagem:
            process_inbox(store, _mensagem("quero"))
        self.assertEqual([i["url"] for i in store.imagens], [FICHA_GERAL["image_url"]])
        triagem.assert_not_called()

    def test_quero_sem_a_pergunta_antes_segue_o_fluxo_normal(self):
        store = self._store("Tô por aqui, pode contar o que quiser sobre o evento")
        with mock.patch.object(
            server, "triar_mensagem_ia",
            return_value={"tipo": "conversa", "urgencia": "Neutro", "ficha": None},
        ), mock.patch.object(worker, "compose_smalltalk", lambda *a, **k: "OI"):
            process_inbox(store, _mensagem("quero"))
        self.assertEqual(store.imagens, [])

    def test_nao_depois_da_pergunta_nao_manda_nada_de_cardapio(self):
        store = self._store(worker.PERGUNTA_CARDAPIO_COMPLETO)
        with mock.patch.object(
            server, "triar_mensagem_ia",
            return_value={"tipo": "conversa", "urgencia": "Neutro", "ficha": None},
        ), mock.patch.object(worker, "compose_smalltalk", lambda *a, **k: "OI"):
            process_inbox(store, _mensagem("não, valeu"))
        self.assertEqual(store.imagens, [])
