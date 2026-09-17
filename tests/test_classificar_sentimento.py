"""Regressões do classificador determinístico usado no worker."""

import unittest

from server import classificar_categoria, classificar_sentimento


class ClassificarSentimentoTests(unittest.TestCase):
    def test_falta_cerveja_no_camarote_e_urgente(self):
        """Presente do verbo 'faltar' não pode cair no padrão Neutro."""

        self.assertEqual(
            classificar_sentimento("Falta cerveja no bar do camarote"),
            "Urgente",
        )
        self.assertEqual(
            classificar_categoria("Falta cerveja no bar do camarote"),
            "Alimentação & Bebidas",
        )

    def test_variantes_de_escassez_sao_urgente(self):
        casos = [
            "faltam copos no bar",
            "faltou cerveja",
            "acabou a cerveja",
            "ta sem cerveja",
            "tá sem chopp no camarote",
            "está sem água",
            "não tem mais gelo",
            "sem cerveja no bar",
        ]
        for texto in casos:
            with self.subTest(texto=texto):
                self.assertEqual(classificar_sentimento(texto), "Urgente")

    def test_nao_confunde_asfaltado_com_falta(self):
        self.assertEqual(classificar_sentimento("asfaltado na entrada"), "Neutro")

    def test_pergunta_continua_neutra(self):
        self.assertEqual(classificar_sentimento("que horas começa?"), "Neutro")

    def test_elogio_continua_positivo(self):
        self.assertEqual(classificar_sentimento("show incrível, adorei"), "Positivo")


if __name__ == "__main__":
    unittest.main()
