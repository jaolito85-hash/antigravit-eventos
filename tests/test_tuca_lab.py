"""Testes do laboratório isolado e do TUCA experimental. Sem API externa."""

import copy
import time
import unittest
from unittest import mock
from concurrent.futures import ThreadPoolExecutor
import server, worker, tuca_lab, tuca_experimental as exp

CONFIG = {
    "settings": {},
    "rules": [],
    "knowledge": [
        {
            "id": "f",
            "question": "Água",
            "answer": "Tem água gratuita na pista.",
            "active": True,
        }
    ],
}
SECTORS = [
    {"id": "s1", "code": "BAR", "name": "Bar Tropical", "metadata": {}},
    {"id": "s2", "code": "PALCO", "name": "Palco Tropical", "metadata": {}},
]
SNAP = {
    "config": CONFIG,
    "sectors": SECTORS,
    "window": [None, None],
    "clock": "2026-09-24T12:00:00Z",
}
PLAN = {
    "intent": "question",
    "urgency": "Neutro",
    "quotes": [{"source_id": "f0", "quote": "Tem água gratuita na pista."}],
    "unanswered": False,
}


class EngineTests(unittest.TestCase):
    def setUp(self):
        for patcher in [
            mock.patch.object(
                server, "moderar_texto", return_value={"bloquear": False}
            ),
            mock.patch.object(
                worker, "moderar_texto", return_value={"bloquear": False}
            ),
            mock.patch.object(server, "_openai_chat_client", return_value=None),
            mock.patch.object(server, "classificar_com_ia", return_value=None),
            mock.patch.object(server, "generate_ai_response", return_value=None),
        ]:
            patcher.start()
            self.addCleanup(patcher.stop)

    def reply(self, text, plan=None, state=None, snapshot=None, kind="text"):
        state = {} if state is None else state
        result = exp.respond(
            state, snapshot or SNAP, text, kind, planner=lambda *a: copy.deepcopy(plan)
        )
        return state, result

    def test_experimental_usa_citacao_verificada(self):
        state, r = self.reply("Tem água grátis?", PLAN)
        self.assertEqual(r["cards"], 0)
        self.assertEqual(r["sources"][0]["title"], "Água")
        self.assertIn("gratuita", r["messages"][0]["content"])

    def test_texto_inventado_nao_e_fonte(self):
        p = copy.deepcopy(PLAN)
        p["quotes"][0]["quote"] = "A água custa R$ 99."
        state, r = self.reply("água", p)
        self.assertEqual([], r["sources"])
        self.assertEqual(1, r["cards"])
        self.assertNotIn("99", r["messages"][0]["content"])

    def test_nao_remove_negacao_da_fonte(self):
        snapshot = copy.deepcopy(SNAP)
        snapshot["config"]["knowledge"][0][
            "answer"
        ] = "Não é permitido entrar com vidro."
        p = copy.deepcopy(PLAN)
        p["quotes"][0]["quote"] = "é permitido entrar com vidro."
        state, r = self.reply("posso entrar com vidro?", p, snapshot=snapshot)
        self.assertIn("Não é permitido entrar com vidro.", r["messages"][0]["content"])

    def test_fonte_com_instrucao_editorial_e_rejeitada(self):
        snapshot = copy.deepcopy(SNAP)
        snapshot["config"]["knowledge"][0][
            "answer"
        ] = "Veja [enviar link] para detalhes."
        p = copy.deepcopy(PLAN)
        p["quotes"][0]["quote"] = "Veja [enviar link] para detalhes."
        _, r = self.reply("link", p, snapshot=snapshot)
        self.assertFalse(r["sources"])

    def test_emergencia_nao_chama_planejador(self):
        with mock.patch.object(
            exp, "plan_message", side_effect=AssertionError("não chamar")
        ):
            r = exp.respond({}, SNAP, "socorro", "text")
        self.assertEqual("Critico", r["urgency"])
        self.assertIn("localização", r["messages"][0]["content"])

    def test_desconhecido_registra_antes_de_confirmar(self):
        state, r = self.reply(
            "senha wifi",
            {"intent": "question", "urgency": "Neutro", "unanswered": True},
        )
        self.assertEqual(len(state["cards"]), 1)
        self.assertIn("enviado", r["messages"][0]["content"])

    def test_conversa_nao_cria_chamado(self):
        state, r = self.reply("cadê você?", {"intent": "social", "urgency": "Neutro"})
        self.assertEqual([], state["cards"])
        self.assertIn("bastidores", r["messages"][0]["content"])

    def test_elogio_tem_humor_sem_chamado(self):
        state, r = self.reply("show top", {"intent": "positive", "urgency": "Positivo"})
        self.assertEqual([], state["cards"])
        self.assertIn("batendo asa", r["messages"][0]["content"])

    def test_gps_completa_emergencia_mesmo_apos_outra_duvida(self):
        state, r = self.reply("socorro")
        self.reply("senha wifi", None, state)
        state, r = self.reply("-23.3,-51.2", state=state, kind="location")
        self.assertEqual(2, len(state["cards"]))
        self.assertEqual([-23.3, -51.2], state["cards"][0]["location"]["coords"])
        self.assertIsNone(state["cards"][1]["location"])
        self.assertNotIn("pending", state)

    def test_referencia_textual_completa_chamado(self):
        state, r = self.reply("socorro")
        state, r = self.reply(
            "estou no Bar Tropical",
            {"intent": "location", "urgency": "Neutro", "sector_code": "BAR"},
            state,
        )
        self.assertEqual(1, len(state["cards"]))
        self.assertEqual("BAR", state["cards"][0]["location"]["code"])

    def test_local_ambiguo_pede_referencia_sem_escolher(self):
        state, r = self.reply("socorro")
        state, r = self.reply(
            "no bar",
            {"intent": "location", "urgency": "Neutro", "sector_code": None},
            state,
        )
        self.assertIn("Qual é o nome", r["messages"][0]["content"])
        self.assertIn("pending", state)

    def test_gps_antes_do_relato_e_reutilizado(self):
        state, r = self.reply("-23.3,-51.2", kind="location")
        state, r = self.reply("socorro", state=state)
        self.assertIn("Já tenho sua localização", r["messages"][0]["content"])
        self.assertNotIn("pending", state)

    def test_localizacao_expira(self):
        state = {
            "location": {"code": "BAR", "name": "Bar Tropical", "at": time.time() - 301}
        }
        _, r = self.reply("socorro", state=state)
        self.assertIn("Me diga onde", r["messages"][0]["content"])

    def test_gps_invalido_nao_e_guardado(self):
        state, r = self.reply("nan,1", kind="location")
        self.assertNotIn("location", state)

    def test_qr_invalido_nao_localiza(self):
        state, r = self.reply("#SETOR:INEXISTENTE\nsocorro")
        self.assertIsNone(r["sector"])
        self.assertTrue(r["notes"])

    def test_conflito_de_horario_nao_escolhe(self):
        snapshot = copy.deepcopy(SNAP)
        snapshot["config"]["knowledge"] = [
            {"question": "Abertura", "answer": "Os portões abrem às 15h."},
            {"question": "Grade", "answer": "14:30 | Abertura dos portões"},
        ]
        state, r = self.reply("Que horas abrem os portões?", PLAN, snapshot=snapshot)
        self.assertIn("informações diferentes", r["messages"][0]["content"])
        self.assertEqual(1, r["cards"])

    def test_motor_atual_nao_toca_persistencia_real(self):
        with mock.patch.object(server, "EVENT_STORE") as real:
            result = tuca_lab.run_current({}, SNAP, "socorro", "text")
        self.assertEqual(1, result["cards"])
        self.assertEqual([], real.mock_calls)

    def test_contexto_e_restaurado_apos_erro(self):
        with self.assertRaises(RuntimeError):
            with tuca_lab.frozen(SNAP):
                raise RuntimeError("teste")
        self.assertIsNone(tuca_lab.SNAPSHOT.get())
        self.assertIsNone(server._CONFIG_PREVIEW.get())

    def test_snapshots_concorrentes_nao_se_misturam(self):
        def read(name):
            snap = copy.deepcopy(SNAP)
            snap["sectors"][0]["name"] = name
            with tuca_lab.frozen(snap):
                return server._setores_ativos()[0]["name"]

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(["A", "B"], list(pool.map(read, ["A", "B"])))

    def test_agua_gratis_nao_e_substituida_por_open_bar(self):
        snapshot = copy.deepcopy(SNAP)
        snapshot["config"]["knowledge"].append(
            {"question": "Open bar", "answer": "O lounge inclui bebidas."}
        )
        plan = {
            "intent": "question",
            "urgency": "Neutro",
            "unanswered": False,
            "quotes": [{"source_id": "f1", "quote": "O lounge inclui bebidas."}],
        }
        state, r = self.reply("Tem água grátis?", plan, snapshot=snapshot)
        self.assertIn("água gratuita na pista", r["messages"][0]["content"])
        self.assertNotIn("lounge", r["messages"][0]["content"])

    def test_local_posterior_nao_repete_emergencia_do_historico(self):
        state, r = self.reply("socorro")
        state, r = self.reply(
            "Estou no Bar Tropical",
            {"intent": "incident", "urgency": "Critico", "sector_code": "BAR"},
            state,
        )
        self.assertEqual(1, len(state["cards"]))
        self.assertEqual("BAR", state["cards"][0]["location"]["code"])
        self.assertIn("acrescentada", r["messages"][0]["content"])


class RoutesTests(unittest.TestCase):
    def setUp(self):
        self.client = server.app.test_client()
        self.store = mock.Mock()
        self.store.live_config.return_value = CONFIG
        self.store.draft_payload.return_value = CONFIG
        self.store.list_sectors.return_value = SECTORS
        self.store.event_window.return_value = (None, None)
        patcher = mock.patch.object(server, "EVENT_STORE", self.store)
        patcher.start()
        self.addCleanup(patcher.stop)

    def login(self, client=None):
        with (client or self.client).session_transaction() as s:
            s["logged_in"] = True

    def start(self):
        self.login()
        return self.client.post("/api/tuca-lab/start", json={})

    def test_pagina_e_api_exigem_login(self):
        self.assertEqual(302, self.client.get("/tuca/laboratorio").status_code)
        self.assertEqual(
            302, self.client.post("/api/tuca-lab/start", json={}).status_code
        )
        self.store.live_config.assert_not_called()

    def test_duas_variantes_da_mesma_base(self):
        data = self.start().get_json()
        self.assertEqual({"current", "experimental", "jev", "enxuto"}, set(data["tokens"]))
        self.assertTrue(data["snapshot"])
        self.assertNotEqual(data["tokens"]["current"], data["tokens"]["experimental"])

    def test_estado_adulterado_e_rejeitado(self):
        token = self.start().get_json()["tokens"]["experimental"]
        result = self.client.post(
            "/api/tuca-lab/turn", json={"token": token + "x", "content": "oi"}
        )
        self.assertEqual(400, result.status_code)

    def test_estado_de_outro_login_e_rejeitado(self):
        token = self.start().get_json()["tokens"]["experimental"]
        other = server.app.test_client()
        self.login(other)
        result = other.post(
            "/api/tuca-lab/turn", json={"token": token, "content": "oi"}
        )
        self.assertEqual(400, result.status_code)

    def test_emergencia_http_sem_escrita_em_banco(self):
        token = self.start().get_json()["tokens"]["experimental"]
        self.store.reset_mock()
        result = self.client.post(
            "/api/tuca-lab/turn", json={"token": token, "content": "socorro"}
        )
        self.assertEqual(200, result.status_code)
        self.assertEqual("Critico", result.get_json()["result"]["urgency"])
        self.assertEqual([], self.store.mock_calls)

    def test_json_e_tamanho_validados(self):
        self.login()
        self.assertEqual(
            400, self.client.post("/api/tuca-lab/start", json=[]).status_code
        )
        self.assertEqual(
            400,
            self.client.post(
                "/api/tuca-lab/turn", json={"content": "a" * 2001, "token": "x"}
            ).status_code,
        )

    def test_https_no_proxy_com_backend_http(self):
        self.login()
        result = self.client.post(
            "/api/tuca-lab/start", json={}, headers={"Origin": "https://localhost"}
        )
        self.assertEqual(200, result.status_code)
        self.assertIn("tokens", result.get_json())

    def test_origem_externa_e_rejeitada(self):
        self.login()
        r = self.client.post(
            "/api/tuca-lab/start",
            json={},
            headers={"Origin": "https://outside.invalid"},
        )
        self.assertEqual(400, r.status_code)
        self.store.live_config.assert_not_called()

    def test_sessao_expirada_e_rejeitada(self):
        from itsdangerous import URLSafeTimedSerializer

        signer = URLSafeTimedSerializer(server.app.secret_key, salt="tuca-lab-v1")
        token = self.start().get_json()["tokens"]["experimental"]
        payload = signer.loads(token)
        payload["started_at"] = "2020-01-01T00:00:00+00:00"
        r = self.client.post(
            "/api/tuca-lab/turn", json={"token": signer.dumps(payload), "content": "oi"}
        )
        self.assertEqual(409, r.status_code)

    def test_limite_de_rodadas_e_validado(self):
        from itsdangerous import URLSafeTimedSerializer

        signer = URLSafeTimedSerializer(server.app.secret_key, salt="tuca-lab-v1")
        token = self.start().get_json()["tokens"]["experimental"]
        payload = signer.loads(token)
        payload["state"]["turns"] = 60
        r = self.client.post(
            "/api/tuca-lab/turn", json={"token": signer.dumps(payload), "content": "oi"}
        )
        self.assertEqual(409, r.status_code)

    def test_rascunho_somente_le_sem_publicar(self):
        self.login()
        r = self.client.post("/api/tuca-lab/start", json={"mode": "draft"})
        self.assertEqual(200, r.status_code)
        self.store.draft_payload.assert_called_once()
        self.store.publish_config.assert_not_called()
