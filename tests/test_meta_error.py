"""Garante que a falha de envio chega ao painel sem vazar dado pessoal."""

import unittest
from unittest import mock

from event_store import _linha_de_erro
from meta_whatsapp import (
    DEFAULT_GRAPH_API_VERSION,
    MetaAPIError,
    describe_api_error,
    graph_api_version,
)


class RespostaFalsa:
    """Resposta da Graph API o suficiente para o resumo de erro."""

    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("corpo não é JSON")
        return self._payload


class DescreveErroTest(unittest.TestCase):
    def test_token_vencido_mostra_codigo_e_motivo(self):
        resposta = RespostaFalsa(401, {"error": {
            "message": "Error validating access token: Session has expired",
            "code": 190,
            "error_subcode": 463,
        }})
        linha = describe_api_error(resposta)
        self.assertIn("HTTP 401", linha)
        self.assertIn("code 190.463", linha)
        self.assertIn("Session has expired", linha)

    def test_numero_fora_da_lista_de_teste_mostra_codigo(self):
        resposta = RespostaFalsa(400, {"error": {
            "message": "Recipient phone number not in allowed list",
            "code": 131030,
        }})
        linha = describe_api_error(resposta)
        self.assertIn("HTTP 400", linha)
        self.assertIn("code 131030", linha)

    def test_telefone_no_texto_da_meta_e_mascarado(self):
        resposta = RespostaFalsa(400, {"error": {
            "message": "Recipient 554499998888 is not in the allowed list",
            "code": 131030,
        }})
        linha = describe_api_error(resposta)
        self.assertNotIn("554499998888", linha)
        self.assertIn("[numero]", linha)
        # O código da Meta tem 6 dígitos e precisa sobreviver à máscara.
        self.assertIn("code 131030", linha)

    def test_corpo_sem_json_ainda_informa_o_status(self):
        self.assertEqual("HTTP 502", describe_api_error(RespostaFalsa(502, None)))


class LinhaDeErroTest(unittest.TestCase):
    def test_erro_da_meta_vai_detalhado_para_o_banco(self):
        linha = _linha_de_erro(MetaAPIError("HTTP 401 | code 190 | token expirado"))
        self.assertEqual("MetaAPIError: HTTP 401 | code 190 | token expirado", linha)

    def test_erro_de_terceiro_guarda_so_o_tipo(self):
        # Texto de biblioteca externa pode carregar telefone, então não é persistido.
        linha = _linha_de_erro(RuntimeError("falhou ao falar com 554499998888"))
        self.assertEqual("RuntimeError: envio falhou", linha)
        self.assertNotIn("554499998888", linha)


class VersaoDaGraphApiTest(unittest.TestCase):
    def _com(self, valor):
        return mock.patch.dict("os.environ", {"META_GRAPH_API_VERSION": valor})

    def test_versao_vencida_e_trocada_pela_padrao(self):
        # A v20.0 expira em 24/09/2026, dois dias antes do Tropicadelia.
        with self._com("v20.0"):
            self.assertEqual(DEFAULT_GRAPH_API_VERSION, graph_api_version())

    def test_versao_atual_e_respeitada(self):
        with self._com("v26.0"):
            self.assertEqual("v26.0", graph_api_version())

    def test_versao_no_piso_e_respeitada(self):
        with self._com("v21.0"):
            self.assertEqual("v21.0", graph_api_version())

    def test_variavel_vazia_cai_na_padrao(self):
        with self._com(""):
            self.assertEqual(DEFAULT_GRAPH_API_VERSION, graph_api_version())

    def test_variavel_ilegivel_cai_na_padrao(self):
        with self._com("versao-errada"):
            self.assertEqual(DEFAULT_GRAPH_API_VERSION, graph_api_version())


if __name__ == "__main__":
    unittest.main()
