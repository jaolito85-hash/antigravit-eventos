"""A IA soltou "海南天天中彩票 üpj" no meio de uma resposta (26/09): nunca mais sai."""

import unittest
from unittest import mock

from event_store import SEM_TEXTO_APROVEITAVEL, EventStore, sem_escrita_estrangeira

REAL = (
    "Tem sim! 🍻 Nos bares você encontra Budweiser, Budweiser Zero, Flying Fish e Corona. "
    "A venda é proibida para menores de 18 anos. 海南天天中彩票 üpj\n\n"
    "Quer que eu te mande a arte com os valores? Responde *QUERO* 😉"
)


class EscritaEstrangeiraTests(unittest.TestCase):
    def test_o_caso_real_sai_limpo(self):
        limpo = sem_escrita_estrangeira(REAL)
        self.assertNotIn("彩", limpo)
        self.assertNotIn("üpj", limpo)
        self.assertIn("A venda é proibida para menores de 18 anos.", limpo)
        self.assertIn("Responde *QUERO* 😉", limpo)

    def test_texto_normal_nao_muda(self):
        for texto in [
            "Tem sim! 🦜✨ Fica na Loja Oficial, na pista, perto da feirinha.",
            "Yes! Beer is sold at the bars. ¿Dónde estás? Ação, coração, pão.",
            "*Segura essas pedradas de line-up!* 🎶🤘",
        ]:
            self.assertEqual(sem_escrita_estrangeira(texto), texto)

    def test_outras_escritas_tambem_saem(self):
        for lixo in ["Привет мир", "مرحبا", "こんにちは", "안녕하세요", "สวัสดี"]:
            self.assertEqual(sem_escrita_estrangeira(f"Tudo certo. {lixo} ok."), "Tudo certo.")

    def test_sem_nada_aproveitavel_vai_frase_neutra(self):
        self.assertEqual(sem_escrita_estrangeira("海南天天中彩票"), SEM_TEXTO_APROVEITAVEL)

    def test_a_fila_de_saida_grava_o_texto_limpo(self):
        store = EventStore.__new__(EventStore)
        linhas = []
        tabela = mock.MagicMock()
        tabela.upsert.side_effect = lambda row, **_: linhas.append(row) or tabela
        cliente = mock.MagicMock()
        cliente.table.return_value = tabela
        with mock.patch.object(EventStore, "event_id", return_value="ev"), \
                mock.patch.object(EventStore, "_get_client", return_value=cliente):
            store.enqueue_text({"id": "m1", "channel_account_id": "c", "sender": "5543"}, REAL)
        self.assertNotIn("彩", linhas[0]["content"])


if __name__ == "__main__":
    unittest.main()
