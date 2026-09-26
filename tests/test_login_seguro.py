"""Login do painel: uma conta por pessoa, limite de tentativas e cookie seguro.

Auditoria de 26/09/2026, dia do festival: a conta era uma só (sem saber quem
publicou o quê), não havia limite de tentativas de senha, o cookie só era
seguro se alguém lembrasse de FLASK_ENV no Coolify, e o proxy não mandava
HSTS.
"""

import os
import unittest
from unittest import mock

import server

CONTAS = {"ADMIN_USER": "producao", "ADMIN_PASS": "senha-forte-1", "ADMIN_USERS": "lucas:outra-senha-2, joana : terceira-3"}


class ContasTests(unittest.TestCase):
    def test_admin_users_soma_contas_a_conta_principal(self):
        with mock.patch.dict(os.environ, CONTAS):
            self.assertEqual(
                server.contas_do_painel(),
                [("producao", "senha-forte-1"), ("lucas", "outra-senha-2"), ("joana", "terceira-3")],
            )

    def test_par_mal_formado_e_ignorado(self):
        with mock.patch.dict(os.environ, {**CONTAS, "ADMIN_USERS": "semsenha, :semnome,ok:1"}):
            self.assertEqual(server.contas_do_painel()[1:], [("ok", "1")])

    def test_credencial_confere_por_conta_e_devolve_o_nome(self):
        with mock.patch.dict(os.environ, CONTAS):
            self.assertEqual(server.credenciais_conferem("lucas", "outra-senha-2"), "lucas")
            self.assertEqual(server.credenciais_conferem("producao", "senha-forte-1"), "producao")
            self.assertIsNone(server.credenciais_conferem("lucas", "senha-forte-1"))
            self.assertIsNone(server.credenciais_conferem("ninguem", "outra-senha-2"))


class LoginRotaTests(unittest.TestCase):
    def setUp(self):
        server._falhas_de_login.clear()
        self.cliente = server.app.test_client()

    def test_segunda_conta_entra_e_a_sessao_guarda_quem_e(self):
        with mock.patch.dict(os.environ, CONTAS):
            r = self.cliente.post("/login", data={"username": "lucas", "password": "outra-senha-2"})
        self.assertEqual(r.status_code, 302)
        with self.cliente.session_transaction() as sessao:
            self.assertTrue(sessao["logged_in"])
            self.assertEqual(sessao["user"], "lucas")

    def test_senha_errada_nao_entra(self):
        with mock.patch.dict(os.environ, CONTAS):
            r = self.cliente.post("/login", data={"username": "producao", "password": "errada"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("incorretos", r.get_data(as_text=True))
        with self.cliente.session_transaction() as sessao:
            self.assertFalse(sessao.get("logged_in"))

    def test_vinte_erros_bloqueiam_o_endereco_ate_a_senha_certa(self):
        with mock.patch.dict(os.environ, CONTAS):
            for _ in range(server.LOGIN_MAX_FALHAS):
                self.cliente.post("/login", data={"username": "producao", "password": "errada"})
            r = self.cliente.post("/login", data={"username": "producao", "password": "senha-forte-1"})
        self.assertEqual(r.status_code, 429)
        self.assertIn("Muitas tentativas", r.get_data(as_text=True))
        with self.cliente.session_transaction() as sessao:
            self.assertFalse(sessao.get("logged_in"))

    def test_bloqueio_e_por_endereco_e_expira(self):
        agora = 1_000_000.0
        for _ in range(server.LOGIN_MAX_FALHAS):
            server.registrar_falha_de_login("1.1.1.1", agora)
        self.assertTrue(server.login_bloqueado("1.1.1.1", agora))
        self.assertFalse(server.login_bloqueado("2.2.2.2", agora), "outro endereço segue livre")
        self.assertFalse(server.login_bloqueado("1.1.1.1", agora + server.LOGIN_JANELA_SEGUNDOS + 1))

    def test_endereco_vem_do_cloudflare_ou_do_proxy(self):
        with server.app.test_request_context("/login", headers={"X-Forwarded-For": "9.9.9.9, 10.0.0.1"}):
            self.assertEqual(server._endereco_do_cliente(), "9.9.9.9")
        with server.app.test_request_context("/login", headers={"CF-Connecting-IP": "8.8.8.8", "X-Forwarded-For": "9.9.9.9"}):
            self.assertEqual(server._endereco_do_cliente(), "8.8.8.8")


class CabecalhosTests(unittest.TestCase):
    def test_hsts_e_cookie_seguro_fora_do_desenvolvimento(self):
        with mock.patch.object(server, "AMBIENTE_LOCAL", False):
            r = server.app.test_client().get("/login")
        self.assertIn("max-age=31536000", r.headers.get("Strict-Transport-Security", ""))

    def test_desenvolvimento_fica_sem_hsts(self):
        with mock.patch.object(server, "AMBIENTE_LOCAL", True):
            r = server.app.test_client().get("/login")
        self.assertNotIn("Strict-Transport-Security", r.headers)


if __name__ == "__main__":
    unittest.main()
