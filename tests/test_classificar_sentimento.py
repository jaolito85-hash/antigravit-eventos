"""Triagem por IA: tipo e urgência na mesma chamada, keywords como fallback."""

import json
import unittest
from unittest.mock import MagicMock, patch

from server import classificar_categoria, classificar_sentimento, classificar_urgencia


class ClassificarUrgenciaTests(unittest.TestCase):
    @patch("server.triar_mensagem_ia", return_value={"tipo": "relato", "urgencia": "Urgente"})
    def test_usa_ia_mesmo_sem_palavra_conhecida(self, mock_ia):
        """Frase que não está em nenhuma lista ainda assim vai para a IA."""

        texto = "no camarote ninguem consegue mais beber o que pediu"
        self.assertEqual(classificar_urgencia(texto), "Urgente")
        mock_ia.assert_called_once_with(texto)

    @patch("server.triar_mensagem_ia", return_value=None)
    def test_cai_no_fallback_se_openai_falhar(self, _mock_ia):
        self.assertEqual(classificar_urgencia("banheiro sujo"), "Urgente")

    @patch("server.triar_mensagem_ia", return_value={"tipo": "relato", "urgencia": "Positivo"})
    def test_respeita_elogio_da_ia(self, _mock_ia):
        self.assertEqual(classificar_urgencia("que noite incrível"), "Positivo")


class TriarMensagemIaTests(unittest.TestCase):
    def _fake_client(self, tipo="relato", urgencia="Urgente", raw=None):
        fake_message = MagicMock()
        fake_message.content = raw if raw is not None else json.dumps(
            {"tipo": tipo, "urgencia": urgencia}
        )
        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value.choices = [
            MagicMock(message=fake_message)
        ]
        return fake_client

    def _triar(self, fake_client, texto, model="gpt-4o-mini"):
        with patch.dict(
            "os.environ",
            {"OPENAI_API_KEY": "sk-test", "OPENAI_MODEL": model},
            clear=False,
        ):
            with patch("server._openai_chat_client", return_value=fake_client):
                from server import triar_mensagem_ia

                return triar_mensagem_ia(texto)

    def test_prompt_pede_sentido_e_nao_lista_de_frases(self):
        fake_client = self._fake_client()
        resultado = self._triar(fake_client, "Falta cerveja no bar do camarote")

        self.assertEqual(
            resultado,
            {"tipo": "relato", "urgencia": "Urgente", "ficha": None, "setor": None, "lugar": None},
        )
        kwargs = fake_client.chat.completions.create.call_args.kwargs
        self.assertEqual(kwargs["model"], "gpt-4o-mini")
        self.assertEqual(kwargs["temperature"], 0)
        self.assertIn("max_tokens", kwargs)
        system = kwargs["messages"][0]["content"]
        self.assertIn("SENTIDO", system)
        self.assertIn("não procure palavras-chave", system)
        self.assertEqual(
            kwargs["messages"][1]["content"],
            "Falta cerveja no bar do camarote",
        )

    def test_modelo_de_raciocinio_usa_reasoning_effort(self):
        """Os GPT-5 recusam temperature; o payload tem que mudar com o modelo."""

        fake_client = self._fake_client()
        self._triar(fake_client, "banheiro sujo", model="gpt-5.4-mini")

        kwargs = fake_client.chat.completions.create.call_args.kwargs
        self.assertEqual(kwargs["model"], "gpt-5.4-mini")
        self.assertNotIn("temperature", kwargs)
        self.assertEqual(kwargs["reasoning_effort"], "none")
        self.assertIn("max_completion_tokens", kwargs)

    def test_separa_conversa_de_relato(self):
        fake_client = self._fake_client(tipo="conversa", urgencia="Neutro")
        self.assertEqual(
            self._triar(fake_client, "oi, tudo bem?"),
            {"tipo": "conversa", "urgencia": "Neutro", "ficha": None, "setor": None, "lugar": None},
        )

    def test_aceita_json_dentro_de_bloco_de_codigo(self):
        """O modelo às vezes devolve o JSON cercado de crases."""

        bruto = '```json\n{"tipo": "relato", "urgencia": "Critico"}\n```'
        resultado = self._triar(self._fake_client(raw=bruto), "tem briga aqui")
        self.assertEqual(resultado["urgencia"], "Critico")

    def test_resposta_ilegivel_cai_no_fallback(self):
        """Sem JSON válido a triagem devolve None e o chamador usa keywords."""

        self.assertIsNone(self._triar(self._fake_client(raw="sei lá"), "banheiro sujo"))

    def test_urgencia_invalida_cai_no_fallback(self):
        fake = self._fake_client(tipo="relato", urgencia="Talvez")
        self.assertIsNone(self._triar(fake, "banheiro sujo"))

    def test_tipo_invalido_assume_relato(self):
        """Na dúvida sobre o tipo, abrir chamado é mais seguro que ignorar."""

        fake = self._fake_client(tipo="qualquer", urgencia="Urgente")
        self.assertEqual(self._triar(fake, "banheiro sujo")["tipo"], "relato")


class ClassificarKeywordsTests(unittest.TestCase):
    """O fallback determinístico, usado quando a OpenAI está fora."""

    def test_falta_no_presente_e_urgente(self):
        self.assertEqual(classificar_sentimento("Falta cerveja no bar"), "Urgente")

    def test_esta_sem_e_urgente(self):
        self.assertEqual(classificar_sentimento("o bar ta sem gelo"), "Urgente")

    def test_categoria_de_bebida(self):
        self.assertEqual(
            classificar_categoria("Falta cerveja no bar do camarote"),
            "Alimentação & Bebidas",
        )


if __name__ == "__main__":
    unittest.main()
