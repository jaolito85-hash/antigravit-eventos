"""O setor sobrevive à mensagem seguinte, que é onde o relato de verdade chega.

Medido em produção em 23/09/2026: o João escaneou a placa do Ambulatório,
o Tuca cumprimentou, ele escreveu "Achei uma carteira aqui. Onde eu levo ela?"
e o chamado entrou com `region = N/A`. A etiqueta `#SETOR:` tinha vindo na
mensagem anterior, que era só a etiqueta e não virou chamado nenhum.

Isso é o caminho normal, não a exceção: quase ninguém escreve o problema na
mesma mensagem da etiqueta. Naquele momento, 10 dos 24 chamados sem setor da
base eram Urgente ou Crítico, ou seja, dez pinos que o telão não acenderia.
"""

import unittest
from unittest import mock

import server
import worker
from worker import process_inbox

SETOR_AMBULATORIO = {
    "id": "setor-amb",
    "code": "AMB-CENTRAL-PISTA",
    "name": "Ambulatório Central • Pista",
    "metadata": {"cta": "Emergência de saúde? Fale agora."},
}
SETOR_BAR = {
    "id": "setor-bar",
    "code": "BAR-HYPE-PISTA",
    "name": "Bar Hype • Pista",
    "metadata": {},
}
LIBERADO = {"bloquear": False, "motivo": None, "origem": "teste"}


class FakeStore:
    """Só o que o worker consome, com o histórico de chamadas que o teste lê."""

    def __init__(self, setor_recente=None):
        self.setor_recente = setor_recente
        self.feedback = None
        self.inbox_marcado = None
        self.janela_consultada = None
        self.finished = None

    def claim_inbox(self, _message):
        return True

    def conversation_mode(self, _sender_hash):
        return "bot"

    def recent_sender_count(self, _sender_hash, minutes=10):
        return 1

    def recent_sender_audio_count(self, _sender_hash, minutes=60):
        return 0

    def recent_blocked_count(self, _sender_hash, minutes=10):
        return 0

    def recent_event_count(self, minutes=1):
        return 0

    def sector_by_code(self, code):
        return SETOR_AMBULATORIO if code == "AMB-CENTRAL-PISTA" else None

    def marcar_setor_do_inbox(self, message_id, sector_id):
        self.inbox_marcado = (message_id, sector_id)

    def ultimo_setor_escaneado(self, _sender_hash, janela_minutos=30):
        self.janela_consultada = janela_minutos
        return self.setor_recente

    def create_feedback(self, **kwargs):
        self.feedback = kwargs
        return 42

    def enqueue_text(self, *args, **kwargs):
        pass

    def enqueue_image(self, *args, **kwargs):
        pass

    def finish_inbox(self, _message_id, status="processed"):
        self.finished = status

    def block_inbox(self, _message_id, reason):
        self.finished = "ignored"

    def fail_inbox(self, message, error):
        raise AssertionError(f"worker falhou: {error}")


def _mensagem(conteudo):
    return {
        "id": "inbox-id",
        "sender": "5543999999999",
        "sender_hash": "hash-do-joao",
        "channel_account_id": "phone-id",
        "message_type": "text",
        "content": conteudo,
        "media_id": None,
        "attempts": 0,
    }


class SetorHerdadoTests(unittest.TestCase):
    def setUp(self):
        for alvo in ("generate_ai_response", "classificar_com_ia"):
            p = mock.patch.object(server, alvo, lambda *a, **k: None)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(
            worker, "compose_smalltalk",
            lambda _c, ja_falou=False, usar_ia=True: "OI DO TUCA",
        )
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(worker, "moderar_texto", return_value=LIBERADO)
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(
            server, "triar_mensagem_ia",
            return_value={"tipo": "relato", "urgencia": "Urgente"},
        )
        p.start()
        self.addCleanup(p.stop)

    def test_etiqueta_fica_guardada_na_mensagem(self):
        """A mensagem que só traz a etiqueta não vira chamado, mas deixa rastro."""

        store = FakeStore()
        process_inbox(store, _mensagem("#SETOR:AMB-CENTRAL-PISTA"))
        self.assertEqual(store.inbox_marcado, ("inbox-id", "setor-amb"))

    def test_mensagem_seguinte_herda_a_placa_escaneada(self):
        store = FakeStore(setor_recente=SETOR_AMBULATORIO)
        process_inbox(store, _mensagem("Achei uma carteira aqui. Onde eu levo ela?"))

        self.assertEqual(store.feedback["sector_id"], "setor-amb")
        self.assertEqual(store.feedback["sector_source"], "qr_recente")
        self.assertEqual(store.janela_consultada, worker.QR_RECENTE_MINUTOS)

    def test_etiqueta_da_propria_mensagem_ganha_da_memoria(self):
        """Quem escaneou agora vale mais que quem escaneou faz vinte minutos."""

        store = FakeStore(setor_recente=SETOR_BAR)
        process_inbox(store, _mensagem("#SETOR:AMB-CENTRAL-PISTA\nCaiu uma pessoa aqui"))

        self.assertEqual(store.feedback["sector_id"], "setor-amb")
        self.assertEqual(store.feedback["sector_source"], "qr")

    def test_sem_placa_recente_o_chamado_segue_sem_lugar(self):
        """Sem nada na janela, chamado sem lugar. Melhor que lugar errado."""

        store = FakeStore(setor_recente=None)
        process_inbox(store, _mensagem("Achei uma carteira aqui"))

        self.assertIsNone(store.feedback["sector_id"])
        self.assertIsNone(store.feedback["sector_source"])

    def test_lugar_citado_no_texto_ganha_da_memoria(self):
        """O que a pessoa escreveu agora vale mais que onde ela passou antes."""

        store = FakeStore(setor_recente=SETOR_BAR)
        with mock.patch.object(
            server, "triar_mensagem_ia",
            return_value={
                "tipo": "relato", "urgencia": "Urgente",
                "setor": SETOR_AMBULATORIO, "setor_por": "ia",
            },
        ):
            process_inbox(store, _mensagem("O ambulatório da pista está sem ninguém"))

        self.assertEqual(store.feedback["sector_id"], "setor-amb")
        self.assertEqual(store.feedback["sector_source"], "ia")


if __name__ == "__main__":
    unittest.main()
