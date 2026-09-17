"""Classificação de urgência: IA no worker Meta, keywords só como fallback."""

import unittest
from unittest.mock import MagicMock, patch

from server import classificar_categoria, classificar_sentimento, classificar_urgencia


class ClassificarUrgenciaTests(unittest.TestCase):
    @patch("server.classificar_sentimento_ia", return_value="Urgente")
    def test_usa_ia_mesmo_sem_palavra_conhecida(self, mock_ia):
        """Frase que não está em nenhuma lista ainda assim vai para a IA."""

        texto = "no camarote ninguem consegue mais beber o que pediu"
        self.assertEqual(classificar_urgencia(texto), "Urgente")
        mock_ia.assert_called_once_with(texto)

    @patch("server.classificar_sentimento_ia", return_value=None)
    def test_cai_no_fallback_se_openai_falhar(self, _mock_ia):
        self.assertEqual(classificar_urgencia("banheiro sujo"), "Urgente")

    @patch("server.classificar_sentimento_ia", return_value="Positivo")
    def test_respeita_elogio_da_ia(self, _mock_ia):
        self.assertEqual(classificar_urgencia("que noite incrível"), "Positivo")


class ClassificarSentimentoIaTests(unittest.TestCase):
    def test_prompt_pede_sentido_e_nao_lista_de_frases(self):
        fake_message = MagicMock()
        fake_message.content = "Urgente"
        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value.choices = [
            MagicMock(message=fake_message)
        ]

        with patch.dict(
            "os.environ",
            {"OPENAI_API_KEY": "sk-test", "OPENAI_MODEL": "gpt-4o"},
            clear=False,
        ):
            with patch("server._openai_chat_client", return_value=fake_client):
                from server import classificar_sentimento_ia

                result = classificar_sentimento_ia(
                    "Falta cerveja no bar do camarote"
                )

        self.assertEqual(result, "Urgente")
        kwargs = fake_client.chat.completions.create.call_args.kwargs
        self.assertEqual(kwargs["model"], "gpt-4o")
        system = kwargs["messages"][0]["content"]
        self.assertIn("SENTIDO", system)
        self.assertIn("NUNCA é Neutro", system)
        self.assertEqual(kwargs["messages"][1]["content"], "Falta cerveja no bar do camarote")


class FallbackKeywordsTests(unittest.TestCase):
    def test_falta_cerveja_no_camarote_e_urgente(self):
        self.assertEqual(
            classificar_sentimento("Falta cerveja no bar do camarote"),
            "Urgente",
        )
        self.assertEqual(
            classificar_categoria("Falta cerveja no bar do camarote"),
            "Alimentação & Bebidas",
        )

    def test_pergunta_continua_neutra(self):
        self.assertEqual(classificar_sentimento("que horas começa?"), "Neutro")

    def test_elogio_continua_positivo(self):
        self.assertEqual(classificar_sentimento("show incrível, adorei"), "Positivo")


if __name__ == "__main__":
    unittest.main()
