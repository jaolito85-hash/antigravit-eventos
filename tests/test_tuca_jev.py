"""JEV: limites, sigilo, falhas de API e integração com memória do laboratório."""

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock
import requests
import server
import tuca_jev as jev
import tuca_jev_config as provider
import tuca_lab
from test_tuca_lab import SNAP, PLAN


class JevTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "private.json"
        self.patch(
            mock.patch.dict(
                os.environ,
                {"TUCA_JEV_CONFIG_FILE": str(self.path), "TYPESAFE_API_KEY": ""},
            )
        )
        self.patch(
            mock.patch.object(server, "moderar_texto", return_value={"bloquear": False})
        )
        self.patch(
            mock.patch.object(jev.exp, "plan_message", return_value=copy.deepcopy(PLAN))
        )
        self.intent = "question"
        self.confidence = 0.96
        self.risk = 0.01
        self.relevance = 0.98
        self.sector = "unknown"
        self.local = 0.01
        self.conflict = 0.01
        self.ask = self.patch(
            mock.patch.object(provider, "ask", side_effect=self.answer)
        )

    def patch(self, patcher):
        value = patcher.start()
        self.addCleanup(patcher.stop)
        return value

    def answer(self, state, questions, config):
        answers = {}
        for name, q in questions.items():
            if q["type"] == "choice":
                selected = self.intent if name == "intent" else self.sector
                probs = {k: float(k == selected) for k in q["criteria"]}
                answers[name] = {
                    "type": "choice",
                    "choice": selected,
                    "confidence": self.confidence,
                    "probabilities": probs,
                }
            else:
                value = {
                    "danger": self.risk,
                    "has_location": self.local,
                    "conflict": self.conflict,
                }.get(name, self.relevance)
                answers[name] = {"type": "noul", "noul": value}
        return {"answers": answers, "model": "jev-test", "usage": {"input_tokens": 123}}

    def respond(self, text="Tem água grátis?", state=None, kind="text"):
        with tuca_lab.frozen(SNAP):
            return jev.respond({} if state is None else state, SNAP, text, kind)

    def test_fonte_aprovada_e_citada(self):
        r = self.respond()
        self.assertEqual("Respondido com fonte oficial", r["action"])
        self.assertEqual("ok", r["jev"]["status"])
        self.assertEqual(["f0"], r["jev"]["approved_sources"])

    def test_fonte_reprovada_nao_e_resgatada_pela_busca_local(self):
        self.relevance = 0.2
        r = self.respond()
        self.assertEqual([], r["sources"])
        self.assertEqual(1, r["cards"])
        jev.exp.plan_message.assert_not_called()

    def test_intencao_incerta_nao_gera_resposta_factual(self):
        self.confidence = 0.4
        r = self.respond()
        self.assertEqual([], r["sources"])
        jev.exp.plan_message.assert_not_called()

    def test_suspeita_de_risco_sobrepoe_elogio(self):
        self.intent = "positive"
        self.risk = 0.4
        r = self.respond("Estou ficando tonto aqui")
        self.assertEqual("Critico", r["urgency"])
        self.assertEqual(1, r["cards"])

    def test_sos_nao_depende_de_jev(self):
        r = self.respond("Socorro!")
        self.ask.assert_not_called()
        self.assertEqual("bypass", r["jev"]["status"])
        self.assertEqual("Critico", r["urgency"])

    def test_erro_api_tem_reserva_sem_fato_inventado(self):
        self.ask.side_effect = provider.JevError("API indisponível")
        r = self.respond()
        self.assertEqual("unavailable", r["jev"]["status"])
        self.assertEqual([], r["sources"])
        self.assertEqual(1, r["cards"])

    def test_llm_nao_pode_mudar_local_ou_intencao(self):
        jev.exp.plan_message.return_value = {
            **PLAN,
            "intent": "incident",
            "urgency": "Critico",
            "sector_code": "BAR",
        }
        r = self.respond()
        self.assertEqual("Neutro", r["urgency"])
        self.assertIsNone(r["sector"])

    def test_local_ambiguo_nao_escolhe_setor(self):
        self.intent = "location"
        self.sector = "BAR"
        self.confidence = 0.8
        self.local = 0.99
        r = self.respond("Estou no bar")
        self.assertIsNone(r["sector"])
        self.assertIn("Qual é o nome", r["messages"][0]["content"])

    def test_local_nao_e_inferido_de_pergunta(self):
        self.sector = "BAR"
        self.local = 0.05
        r = self.respond("Onde fica o bar?")
        self.assertIsNone(r["sector"])

    def test_local_anexado_ao_sos_apos_outra_pergunta(self):
        state = {}
        self.respond("Socorro!", state)
        self.relevance = 0.1
        self.respond("Qual a senha do wifi?", state)
        self.intent = "location"
        self.sector = "BAR"
        self.local = 0.98
        r = self.respond("Estou no Bar Tropical", state)
        self.assertEqual(2, r["cards"])
        self.assertEqual("Local anexado ao chamado simulado", r["action"])
        self.assertEqual("BAR", state["cards"][0]["location"]["code"])

    def test_conflito_recusa_fonte(self):
        self.conflict = 0.9
        r = self.respond()
        self.assertEqual([], r["sources"])
        self.assertIn("informações diferentes", r["messages"][0]["content"])

    def test_gps_sem_jev(self):
        r = self.respond("-23.3,-51.2", kind="location")
        self.ask.assert_not_called()
        self.assertEqual("GPS recebido", r["sector"])

    def test_config_salva_chave_mas_nao_devolve(self):
        output = provider.save_config(
            {**provider.DEFAULTS, "api_key": "secret-test-key"}
        )
        self.assertNotIn("secret-test-key", json.dumps(output))
        self.assertEqual("secret-test-key", provider.api_key())
        provider.save_config({**provider.DEFAULTS, "api_key": ""})
        self.assertEqual("secret-test-key", provider.api_key())
        provider.save_config({**provider.DEFAULTS, "remove_key": True})
        self.assertFalse(provider.api_key())

    def test_limites_invalidos(self):
        for value in (float("nan"), float("inf"), True, -1, 1.1, "0.9"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                provider.validate({**provider.DEFAULTS, "intent_threshold": value})
        with self.assertRaises(ValueError):
            provider.validate({"model": "https://evil.invalid"})

    def test_resposta_fora_da_lista_ou_probabilidade_invalida(self):
        q = {"x": jev.choice("Escolha", {"a": "A", "b": "B"})}
        for answer in (
            {
                "type": "choice",
                "choice": "c",
                "confidence": 1,
                "probabilities": {"a": 0, "b": 1},
            },
            {
                "type": "choice",
                "choice": "a",
                "confidence": 1,
                "probabilities": {"a": 1, "b": 1},
            },
            {
                "type": "choice",
                "choice": "a",
                "confidence": float("nan"),
                "probabilities": {"a": 1, "b": 0},
            },
        ):
            with self.assertRaises(provider.JevError):
                provider.checked_answers({"answers": {"x": answer}}, q)

    def test_apis_config_exigem_login(self):
        c = server.app.test_client()
        for path in ("jev-config", "jev-test"):
            self.assertEqual(302, c.post("/api/tuca-lab/" + path, json={}).status_code)
        self.assertFalse(self.path.exists())

    def test_config_http_sem_vazamento_e_origem_externa_bloqueada(self):
        c = server.app.test_client()
        with c.session_transaction() as s:
            s["logged_in"] = True
        r = c.post(
            "/api/tuca-lab/jev-config",
            json={**provider.DEFAULTS, "api_key": "private-marker"},
        )
        self.assertEqual(200, r.status_code)
        self.assertNotIn("private-marker", r.get_data(as_text=True))
        r = c.get("/api/tuca-lab/jev-config")
        self.assertNotIn("private-marker", r.get_data(as_text=True))
        self.assertEqual("no-store", r.headers["Cache-Control"])
        r = c.post(
            "/api/tuca-lab/jev-config",
            json=provider.DEFAULTS,
            headers={"Origin": "https://evil.invalid"},
        )
        self.assertEqual(400, r.status_code)

    def test_snapshot_nao_contem_chave_e_preserva_limites(self):
        provider.save_config({**provider.DEFAULTS, "api_key": "private-marker"})
        c = server.app.test_client()
        with c.session_transaction() as s:
            s["logged_in"] = True
        store = mock.Mock()
        store.live_config.return_value = SNAP["config"]
        store.list_sectors.return_value = SNAP["sectors"]
        store.event_window.return_value = (None, None)
        with mock.patch.object(server, "EVENT_STORE", store):
            r = c.post("/api/tuca-lab/start", json={})
        self.assertEqual(200, r.status_code)
        from itsdangerous import URLSafeTimedSerializer

        data = r.get_json()
        self.assertEqual({"current", "experimental", "jev", "enxuto"}, set(data["tokens"]))
        payload = URLSafeTimedSerializer(
            server.app.secret_key, salt="tuca-lab-v1"
        ).loads(data["tokens"]["jev"])
        self.assertNotIn("private-marker", json.dumps(payload))
        self.assertEqual(0.75, payload["snapshot"]["jev_settings"]["intent_threshold"])


class ClientTests(unittest.TestCase):
    def test_erro_http_nao_expoe_corpo_ou_chave(self):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.status_code = 401
        with mock.patch.object(
            provider, "api_key", return_value="supersecret"
        ), mock.patch.object(requests, "post", return_value=response) as post:
            with self.assertRaisesRegex(provider.JevError, "Chave JEV inválida"):
                provider.ask({}, {}, provider.DEFAULTS)
        self.assertFalse(post.call_args.kwargs["allow_redirects"])
        self.assertEqual(provider.API, post.call_args.args[0])

    def test_timeout_generico(self):
        with mock.patch.object(
            provider, "api_key", return_value="supersecret"
        ), mock.patch.object(
            requests, "post", side_effect=requests.Timeout("supersecret")
        ):
            with self.assertRaises(provider.JevError) as ctx:
                provider.ask({}, {}, provider.DEFAULTS)
        self.assertNotIn("supersecret", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
