"""Ficha que responde com foto: a imagem é a resposta, o texto é cabeçalho.

Pedido do João em 23/09/2026. A produção sobe a foto do line-up do Palco Hype;
quando alguém pergunta pelo line-up, o Tuca manda a foto. Se quiser uma linha
antes dela, escreve, e essa linha sai em negrito, literal, sem a IA reescrever.
"""

import unittest
from unittest import mock

import server
import worker
from worker import _cabecalho_do_banner, _so_imagem, process_inbox

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
        p = mock.patch.object(worker, "compose_smalltalk", lambda _c: "OI")
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

    def test_cabecalho_sai_em_negrito_e_literal(self):
        """O texto da produção não passa pela IA: sai como ela escreveu."""

        store = self._rodar(FICHA_COM_CABECALHO, "tem cardápio?")
        self.assertEqual(store.textos, ["*Cardápio de hoje no Open Food 🍔*"])
        self.assertEqual(len(store.imagens), 1)

    def test_ficha_sem_foto_segue_como_sempre(self):
        """Quem não tem imagem continua no caminho antigo, com resposta em texto."""

        store = self._rodar(FICHA_SEM_FOTO, "que horas abre?")
        self.assertEqual(len(store.textos), 1)
        self.assertEqual(store.imagens, [])


class CabecalhoTests(unittest.TestCase):
    def test_negrito_aplicado_para_quem_nao_sabe_a_sintaxe(self):
        self.assertEqual(
            _cabecalho_do_banner({"answer": "Line-up do Palco Hype"}),
            "*Line-up do Palco Hype*",
        )

    def test_quem_ja_formatou_fica_como_esta(self):
        """Asterisco cadastrado é escolha de quem escreveu, não erro a corrigir."""

        self.assertEqual(
            _cabecalho_do_banner({"answer": "*Line-up* do Palco Hype"}),
            "*Line-up* do Palco Hype",
        )

    def test_texto_longo_nao_vira_um_negrito_gigante(self):
        longo = "x" * 250
        self.assertEqual(_cabecalho_do_banner({"answer": longo}), longo)

    def test_sem_texto_nao_ha_cabecalho(self):
        self.assertEqual(_cabecalho_do_banner({"answer": ""}), "")
        self.assertTrue(_so_imagem({"answer": ""}))
        self.assertFalse(_so_imagem({"answer": "algo"}))


if __name__ == "__main__":
    unittest.main()
