"""Limpeza das respostas da IA antes de irem ao WhatsApp.

Em 20/09/2026 o modelo fechou uma resposta em português com "unerquicklich".
A limpeza pega esse caso, tira o travessão que a produção não usa, e não pode
estragar uma resposta boa.
"""

import unittest

from server import _limpar_resposta


class PalavraSoltaTests(unittest.TestCase):
    def test_palavra_solta_depois_de_emoji_cai(self):
        texto = "Aí sim!! 🔥 Daqui a pouco você tá curtindo tudo 😭🎶 unerquicklich"
        self.assertEqual(_limpar_resposta(texto), "Aí sim!! 🔥 Daqui a pouco você tá curtindo tudo 😭🎶")

    def test_palavra_solta_depois_de_pontuacao_cai(self):
        self.assertEqual(_limpar_resposta("Aproveita por mim! Fenster"), "Aproveita por mim!")

    def test_frase_que_termina_em_palavra_normal_fica(self):
        # Várias palavras depois do emoji são frase, não lixo.
        texto = "Sábado promete demais!! 🔥 chama a galera e aproveita por mim!"
        self.assertEqual(_limpar_resposta(texto), texto)
        texto = "Eu tô aqui nos bastidores contando as horas"
        self.assertEqual(_limpar_resposta(texto), texto)

    def test_uma_palavra_depois_do_emoji_no_meio_fica(self):
        texto = "Show 🔥 demais, aproveita muito! 🎶"
        self.assertEqual(_limpar_resposta(texto), texto)


class TravessaoTests(unittest.TestCase):
    def test_travessao_vira_virgula(self):
        texto = "Eu tô contando os segundos — preso nos bastidores 😭 Aproveita!"
        self.assertEqual(_limpar_resposta(texto), "Eu tô contando os segundos, preso nos bastidores 😭 Aproveita!")

    def test_travessao_depois_de_pontuacao_nao_vira_virgula_dupla(self):
        self.assertEqual(_limpar_resposta("Que energia! — aproveita muito"), "Que energia! aproveita muito")
        self.assertEqual(_limpar_resposta("Bora, — aproveita muito"), "Bora, aproveita muito")

    def test_meia_risca_tambem(self):
        self.assertEqual(_limpar_resposta("Sábado – domingo"), "Sábado, domingo")


class MarcacaoTests(unittest.TestCase):
    def test_aspas_e_negrito_duplo(self):
        self.assertEqual(_limpar_resposta('"**Uhu** demais!"'), "*Uhu* demais!")

    def test_enfase_vazia_some(self):
        self.assertEqual(_limpar_resposta("Bora ** curtir"), "Bora curtir")

    def test_vazio_devolve_vazio(self):
        self.assertEqual(_limpar_resposta(""), "")
        self.assertEqual(_limpar_resposta(None), "")


if __name__ == "__main__":
    unittest.main()
