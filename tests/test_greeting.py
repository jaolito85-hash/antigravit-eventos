"""Testes da detecção de saudação.

Saudação e agradecimento não podem abrir chamado, senão a fila de trabalho do
festival enche de conversa. Qualquer relato dentro da mensagem, por outro
lado, precisa abrir chamado mesmo vindo depois de um "bom dia".
"""

import unittest

from server import _is_greeting

SAUDACOES = [
    "oi",
    "Oi!",
    "oiii",
    "Salve",
    "Salve!",
    "salve, tudo bem?",
    "opa, beleza?",
    "e ai galera",
    "e ai, beleza?",
    "bom dia",
    "boa tarde",
    "boa noite pessoal",
    "oie tudo bom",
    "tudo bem?",
    "Oi ChatBob, tudo bem?",
    "menu",
    "ajuda",
    "help",
]

AGRADECIMENTOS = [
    "obrigado!",
    "obrigada",
    "valeu galera",
    "vlw",
    "tchau",
]

RELATOS = [
    "oi, o banheiro esta sujo",
    "salve, perdi minha carteira",
    "bom dia, que horas abre?",
    "e ai, tem fila no bar?",
    "boa noite, alguem viu meu celular?",
    "obrigado pela ajuda, resolveram rapido",
    "acabou o papel",
    "o show esta incrivel",
    "tudo bem no palco mas o som esta baixo",
    "bom dia, faltou cerveja no bar",
    "oi oi oi tem briga aqui",
]


class GreetingTests(unittest.TestCase):
    def test_saudacoes_nao_abrem_chamado(self):
        for texto in SAUDACOES:
            with self.subTest(texto=texto):
                self.assertTrue(_is_greeting(texto))

    def test_agradecimento_tambem_e_conversa(self):
        for texto in AGRADECIMENTOS:
            with self.subTest(texto=texto):
                self.assertTrue(_is_greeting(texto))

    def test_relato_abre_chamado_mesmo_com_cumprimento_antes(self):
        """Uma palavra fora do vocabulário de cortesia faz virar chamado."""

        for texto in RELATOS:
            with self.subTest(texto=texto):
                self.assertFalse(_is_greeting(texto))

    def test_mensagem_longa_nunca_e_saudacao(self):
        longa = "oi " * 40
        self.assertFalse(_is_greeting(longa))

    def test_vazio_e_pontuacao(self):
        self.assertFalse(_is_greeting(""))
        self.assertFalse(_is_greeting("..."))
        self.assertFalse(_is_greeting(None))

    def test_so_cortesia_sem_cumprimento_nao_basta(self):
        """"pessoal" ou "por favor" sozinhos não são saudação."""

        self.assertFalse(_is_greeting("pessoal"))
        self.assertFalse(_is_greeting("por favor"))


if __name__ == "__main__":
    unittest.main()
