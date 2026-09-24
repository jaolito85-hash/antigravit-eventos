"""Fallback determinístico de urgência: o que roda quando a IA está fora.

Os dois casos aqui custaram medição em 23/09/2026 e valem mais desde que o
telão passou a acender pino só em Urgente e Crítico: urgência errada agora
decide se a sala de controle vê ou não vê o chamado na planta.
"""

import unittest

from server import classificar_categoria, classificar_sentimento


class FaltaDeItemEssencialTests(unittest.TestCase):
    """Falta de papel é chamado, não conversa.

    Antes da correção, 5 destas 10 frases caíam em Neutro: a regex exigia
    "tá sem" e a lista de palavras tinha "sem cerveja" e "sem gelo", mas nunca
    "sem papel". A frase do próprio seed de demonstração era uma das que
    falhavam.
    """

    FRASES = (
        "o banheiro tá sem papel",
        "banheiro feminino sem papel higiênico em quase todas as cabines",
        "não tem papel no banheiro",
        "acabou o papel",
        "falta papel higienico aqui",
        "cabine 3 sem papel",
        "o wc do hype não tem papel nem sabonete",
        "sem papel no feminino",
        "papel higiênico acabou",
        "precisa repor papel higienico",
    )

    def test_toda_falta_de_papel_e_urgente(self):
        for frase in self.FRASES:
            with self.subTest(frase=frase):
                self.assertEqual(classificar_sentimento(frase), "Urgente")

    def test_outros_itens_essenciais_tambem(self):
        for frase in ("sem sabonete na pia", "não tem água na torneira",
                      "o bar tá sem gelo", "acabou a cerveja"):
            with self.subTest(frase=frase):
                self.assertEqual(classificar_sentimento(frase), "Urgente")

    def test_sem_seguido_de_nao_item_continua_neutro(self):
        """A lista de itens é fechada para "sem" não virar chamado sozinho."""

        self.assertEqual(classificar_sentimento("entrei sem dificuldade"), "Neutro")


class PalavraInteiraTests(unittest.TestCase):
    """Palavra-chave não pode casar dentro de outra palavra.

    "briga" casa em "o-briga-do": até 23/09/2026 um agradecimento era
    classificado Critico e caía em Segurança, e Critico abre o alerta em tela
    cheia no telão. Ou seja, "obrigado" parava a sala de controle.
    """

    def test_obrigado_nao_e_critico(self):
        for frase in ("obrigado", "muito obrigado equipe", "valeu, obrigado",
                      "obrigada pela ajuda de vocês"):
            with self.subTest(frase=frase):
                self.assertNotEqual(classificar_sentimento(frase), "Critico")

    def test_obrigado_nao_cai_em_seguranca(self):
        self.assertNotEqual(
            classificar_categoria("muito obrigado"), "Segurança & Organização"
        )

    def test_briga_de_verdade_continua_critica(self):
        """A correção não pode esconder a ocorrência que a palavra existe para pegar."""

        for frase in ("tem uma briga aqui na pista", "começou uma briga no bar"):
            with self.subTest(frase=frase):
                self.assertEqual(classificar_sentimento(frase), "Critico")


class ElogioNaoEscondeEmergenciaTests(unittest.TestCase):
    """Palavra de elogio não pode ganhar de briga, fogo ou mal-estar.

    "show" e "bom" estavam no começo da lista. Com a IA fora, "o show pegou
    fogo" e "bom dia, tem briga" viravam Positivo: o telão comemorava em vez
    de alarmar.
    """

    def test_emergencia_com_elogio_na_frase_e_critica(self):
        for frase in (
            "o show pegou fogo",
            "bom dia, tem briga aqui",
            "amei o palco mas uma menina desmaiou",
            "tô surtando",
            "não consigo respirar",
        ):
            with self.subTest(frase=frase):
                self.assertEqual(classificar_sentimento(frase), "Critico")

    def test_problema_com_elogio_na_frase_e_urgente(self):
        for frase in (
            "o show tá incrível mas a fila tá enorme",
            "que bom, acabou a cerveja",
            "não tô bem",
            "tô com medo",
        ):
            with self.subTest(frase=frase):
                self.assertEqual(classificar_sentimento(frase), "Urgente")

    def test_elogio_puro_continua_positivo(self):
        for frase in ("show incrível", "que bom o som", "amei demais"):
            with self.subTest(frase=frase):
                self.assertEqual(classificar_sentimento(frase), "Positivo")


if __name__ == "__main__":
    unittest.main()
