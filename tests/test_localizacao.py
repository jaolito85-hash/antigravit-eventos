"""Localização recebida pelo WhatsApp completa o chamado em vez de ser recusada.

O Tuca pede localização no protocolo de emergência. Antes, a resposta dela
caía no balde de mídia e voltava "envie sua mensagem em texto ou áudio", ou
seja, ele pedia e recusava. Aconteceu de verdade num teste de briga em
22/09/2026.
"""

import unittest
from unittest import mock

import worker


class FakeStore:
    """Store mínima para o caminho da localização."""

    def __init__(self, alvo=None, mode="bot"):
        self.alvo = alvo
        self.mode = mode
        self.responses = []
        self.finished = None
        self.anexado = None
        self.feedback_id_da_resposta = "nao chamado"

    def claim_inbox(self, _message):
        return True

    def conversation_mode(self, _sender_hash):
        return self.mode

    def recent_sender_count(self, _sender_hash, minutes=10):
        return 1

    def recent_blocked_count(self, _sender_hash, minutes=10):
        return 0

    def attach_location(self, sender_hash, lat, lon, janela_minutos=60):
        self.anexado = (sender_hash, lat, lon, janela_minutos)
        return self.alvo

    def enqueue_text(self, _message, content, feedback_id=None):
        self.responses.append(content)
        self.feedback_id_da_resposta = feedback_id

    def finish_inbox(self, _message_id, status="processed"):
        self.finished = status

    def block_inbox(self, _message_id, reason):
        self.finished = "ignored"

    def fail_inbox(self, message, error):
        raise AssertionError(f"nao deveria falhar: {error}")


def _localizacao(conteudo="-23.3312,-51.1925"):
    return {
        "id": "inbox-id",
        "sender": "5543999999999",
        "sender_hash": "hash",
        "channel_account_id": "phone-id",
        "message_type": "location",
        "content": conteudo,
        "media_id": None,
        "attempts": 0,
    }


class CoordenadasTest(unittest.TestCase):
    def test_le_o_par_que_o_webhook_monta(self):
        self.assertEqual((-23.3312, -51.1925), worker._coordenadas("-23.3312,-51.1925"))

    def test_aceita_espaco_em_volta(self):
        self.assertEqual((1.5, 2.5), worker._coordenadas(" 1.5 , 2.5 "))

    def test_recusa_texto_que_nao_e_coordenada(self):
        for valor in ("", "perto do palco", "1,2,3", "abc,def", "12"):
            self.assertIsNone(worker._coordenadas(valor), valor)

    def test_recusa_fora_da_faixa_do_planeta(self):
        # Pino impossível no painel faz a equipe andar para o nada.
        self.assertIsNone(worker._coordenadas("120,0"))
        self.assertIsNone(worker._coordenadas("0,200"))


class LocalizacaoNoWorkerTest(unittest.TestCase):
    def test_anexa_ao_chamado_aberto_e_confirma(self):
        store = FakeStore(alvo={"id": 42, "urgency": "Critico", "message": "briga"})
        worker.process_inbox(store, _localizacao())

        self.assertEqual(("hash", -23.3312, -51.1925, 60), store.anexado)
        self.assertEqual("processed", store.finished)
        self.assertEqual([worker.AVISO_LOCALIZACAO_RECEBIDA], store.responses)
        # A resposta fica pendurada no chamado, para a tela mostrar a troca toda.
        self.assertEqual(42, store.feedback_id_da_resposta)

    def test_sem_chamado_recente_pede_o_relato(self):
        store = FakeStore(alvo=None)
        worker.process_inbox(store, _localizacao())

        self.assertEqual([worker.AVISO_LOCALIZACAO_SEM_CHAMADO], store.responses)
        self.assertIsNone(store.feedback_id_da_resposta)
        self.assertEqual("processed", store.finished)

    def test_coordenada_ilegivel_nao_vai_para_o_painel(self):
        store = FakeStore(alvo={"id": 42, "urgency": "Critico", "message": "briga"})
        worker.process_inbox(store, _localizacao("sem coordenada"))

        self.assertIsNone(store.anexado)
        self.assertEqual([worker.AVISO_LOCALIZACAO_ILEGIVEL], store.responses)
        self.assertEqual("ignored", store.finished)

    def test_nunca_responde_o_aviso_de_mandar_texto(self):
        # Este era o bug: o Tuca pedia localização e devolvia "mande texto".
        store = FakeStore(alvo={"id": 7, "urgency": "Critico", "message": "briga"})
        worker.process_inbox(store, _localizacao())
        self.assertNotIn(worker.AVISO_SO_TEXTO_OU_AUDIO, store.responses)

    def test_com_operador_no_comando_anexa_mas_fica_calado(self):
        store = FakeStore(alvo={"id": 9, "urgency": "Critico", "message": "briga"}, mode="human")
        worker.process_inbox(store, _localizacao())

        self.assertIsNotNone(store.anexado, "a equipe precisa ver a localização")
        self.assertEqual([], store.responses, "quem fala é o operador")
        self.assertEqual("processed", store.finished)

    def test_localizacao_saiu_do_balde_de_midia(self):
        self.assertNotIn("location", worker.TIPOS_DE_MIDIA)
        self.assertIn("location", worker.TIPOS_COM_RESPOSTA)


if __name__ == "__main__":
    unittest.main()
