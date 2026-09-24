"""Testes da detecção de saudação.

Saudação e agradecimento não podem abrir chamado, senão a fila de trabalho do
festival enche de conversa. Qualquer relato dentro da mensagem, por outro
lado, precisa abrir chamado mesmo vindo depois de um "bom dia".
"""

import unittest

from server import (
    RESPOSTA_CURTA_CONVERSA,
    _instrucao_conversa,
    _is_greeting,
    _texto_conversa_sem_ia,
    welcome_text,
)

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
    "Oi Tuca, tudo bem?",
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

    def test_pergunta_ao_tuca_nao_e_so_oi(self):
        """O print do ensaio: pergunta simples não pode cair no texto de oi."""

        for texto in (
            "Voce nao gosta de festa? Kd vc?",
            "Cade voce??",
            "cadê você?",
            "você gosta de festa?",
        ):
            with self.subTest(texto=texto):
                self.assertFalse(_is_greeting(texto))


class ConversaTests(unittest.TestCase):
    def test_pergunta_pede_resposta_e_nao_a_apresentacao(self):
        instrucao = _instrucao_conversa("Voce nao gosta de festa? Kd vc?", ja_falou=False)
        self.assertIn("RESPONDA o que ela perguntou", instrucao)
        self.assertNotIn("primeira mensagem", instrucao)

    def test_oi_de_primeira_vez_apresenta_o_canal(self):
        instrucao = _instrucao_conversa("Oi", ja_falou=False)
        self.assertIn("primeira mensagem", instrucao)
        self.assertIn("problema, elogio ou dúvida", instrucao)

    def test_oi_repetido_nao_reapresenta(self):
        instrucao = _instrucao_conversa("Oi", ja_falou=True)
        self.assertIn("Não se apresente de novo", instrucao)
        self.assertNotIn("primeira mensagem", instrucao)

    def test_sem_ia_pergunta_nao_recebe_o_cartaz(self):
        texto = _texto_conversa_sem_ia("Cade voce??", ja_falou=False)
        self.assertEqual(texto, RESPOSTA_CURTA_CONVERSA)
        self.assertNotIn("100% gratuito", texto)

    def test_sem_ia_primeiro_oi_mantem_as_boas_vindas(self):
        self.assertEqual(_texto_conversa_sem_ia("oi", ja_falou=False), welcome_text())

    def test_sem_ia_oi_repetido_fica_curto(self):
        self.assertEqual(
            _texto_conversa_sem_ia("oi", ja_falou=True),
            RESPOSTA_CURTA_CONVERSA,
        )


if __name__ == "__main__":
    unittest.main()
