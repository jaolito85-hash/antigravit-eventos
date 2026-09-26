"""O "quero" chega de todo jeito (26/09): digitado com erro ou falado em áudio."""

import unittest
from unittest import mock

import tuca_aceite
from tuca_aceite import aceite_por_regra, aceitou

CONVITE = "Quer que eu te mande a arte com os valores? Responde *QUERO* 😉"


class RegraTests(unittest.TestCase):
    def test_sim_de_todo_jeito(self):
        for texto in [
            "quero", "Quero!", "querooo", "quer", "qro", "kero", "qero", "qeuro",
            "sim", "Simmm", "s", "ss", "S!", "manda", "mand", "mamda", "mnada",
            "manda aí", "pode", "pod", "pode mandar", "pode mandar sim", "aham",
            "uhum", "claro", "bora", "isso", "vai", "ok", "blz", "pfv",
            "sim por favor", "manda o cardápio", "quero o line up", "manda tudo",
            "Pode mandar aí, por favor", "com certeza", "dale", "manda a arte",
            "o cardápio", "o line-up", "a arte",
        ]:
            with self.subTest(texto=texto):
                self.assertTrue(aceite_por_regra(texto))

    def test_negacao_nunca_e_sim(self):
        for texto in ["não", "nao quero", "n", "agora não", "depois", "deixa", "não precisa", "nem"]:
            with self.subTest(texto=texto):
                self.assertFalse(aceite_por_regra(texto))

    def test_outra_pergunta_nao_e_sim(self):
        for texto in [
            "quanto custa a cerveja?", "onde fica o bar do hype?",
            "tem cerveja gelada no bar perto do palco?", "ta caro",
        ]:
            with self.subTest(texto=texto):
                self.assertFalse(aceitou(texto, CONVITE, usar_ia=False))

    def test_so_enchimento_nao_e_sim(self):
        self.assertIsNone(aceite_por_regra("por favor aí"))

    def test_resposta_curta_diferente_vai_para_a_ia(self):
        self.assertIsNone(aceite_por_regra("bora ver isso"))
        with mock.patch.object(tuca_aceite, "aceite_por_ia", return_value=True) as ia:
            self.assertTrue(aceitou("bora ver isso", CONVITE))
        ia.assert_called_once()

    def test_regra_decidida_nao_gasta_ia(self):
        with mock.patch.object(tuca_aceite, "aceite_por_ia") as ia:
            self.assertTrue(aceitou("manda", CONVITE))
            self.assertFalse(aceitou("não", CONVITE))
        ia.assert_not_called()

    def test_ia_fora_do_ar_vira_nao(self):
        with mock.patch.object(tuca_aceite, "aceite_por_ia", return_value=None):
            self.assertFalse(aceitou("bora ver isso", CONVITE))


if __name__ == "__main__":
    unittest.main()
