"""Plano B: o motor enxuto ligado no WhatsApp pela chave do evento.

E os três deslizes do Tuca atual corrigidos em 24/09: link do painel nunca
vai para o público, ficha oficial dispensa a pergunta de lugar, e relato
não manda a pessoa para o app.
"""

import unittest
from unittest import mock

import server
import worker
from event_store import EventStore
try:
    from test_worker import LIBERADO, FakeStore, _message
except ImportError:  # rodado como tests.test_motor_plano_b
    from tests.test_worker import LIBERADO, FakeStore, _message


class StoreComMotor(FakeStore):
    def __init__(self, motor="enxuto", **kw):
        super().__init__(**kw)
        self.motor = motor
        self.thread = {"messages": [
            {"direction": "in", "content": "oi"},
            {"direction": "out", "content": "Oi! Eu sou o Tuca"},
            {"direction": "in", "content": "acabou o gelo aqui"},
        ]}

    def motor_ativo(self):
        return self.motor

    def live_config(self):
        return {"settings": {}, "rules": [], "knowledge": []}

    def list_sectors(self):
        return [{"id": "sector-id", "code": "PALCO", "name": "Palco Tropical", "metadata": {}}]

    def event_window(self):
        return (None, None)

    def conversation_thread(self, _h, limit=8):
        return self.thread


def _respond_falso(state, snapshot, content, kind):
    """Imita o enxuto: abre um chamado Urgente com o lugar que o estado tem."""

    state["cards"].append({"id": 1, "content": content, "urgency": "Urgente", "location": state.get("location")})
    return {"messages": [{"type": "text", "content": "Recebi. Já está com a equipe."}], "status": "processed",
            "urgency": "Urgente", "notes": [], "sources": []}


class PlanoBTests(unittest.TestCase):
    def setUp(self):
        for alvo in ("generate_ai_response", "classificar_com_ia"):
            p = mock.patch.object(server, alvo, lambda *a, **k: None)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(worker, "moderar_texto", return_value=LIBERADO)
        p.start()
        self.addCleanup(p.stop)

    @mock.patch("server.triar_mensagem_ia")
    def test_motor_enxuto_responde_e_grava_o_chamado(self, triagem):
        store = StoreComMotor()
        with mock.patch("tuca_enxuto.respond", side_effect=_respond_falso) as respond:
            worker.process_inbox(store, _message(content="#SETOR:PALCO\nacabou o gelo aqui"))

        triagem.assert_not_called()
        self.assertEqual(store.feedback["urgency"], "Urgente")
        self.assertEqual(store.feedback["sector_id"], "sector-id")
        self.assertEqual(store.feedback["sector_source"], "qr")
        self.assertEqual(store.feedback["content"], "acabou o gelo aqui")
        self.assertEqual(store.response[1], "Recebi. Já está com a equipe.")
        self.assertEqual(store.response[2], 42)
        self.assertEqual(store.finished, "processed")
        # A mensagem atual sai do histórico, senão o enxuto a veria duas vezes.
        state = respond.call_args.args[0]
        self.assertEqual([m["content"] for m in state["history"]], ["oi", "Oi! Eu sou o Tuca"])
        self.assertEqual(state["location"]["id"], "sector-id")

    def test_motor_enxuto_sem_chamado_e_bloqueio(self):
        store = StoreComMotor()
        bloqueado = {"messages": [{"type": "text", "content": "Isso eu não levo."}], "status": "blocked",
                     "urgency": None, "notes": [], "sources": []}
        with mock.patch("tuca_enxuto.respond", return_value=bloqueado):
            worker.process_inbox(store, _message(content="seu bot de merda"))
        self.assertIsNone(store.feedback)
        self.assertEqual(store.blocked_reason, "conteudo ofensa")

    def test_operador_no_comando_o_enxuto_grava_e_nao_responde(self):
        store = StoreComMotor(mode="human")
        with mock.patch("tuca_enxuto.respond", side_effect=_respond_falso):
            worker.process_inbox(store, _message(content="acabou o gelo aqui"))
        self.assertIsNotNone(store.feedback)
        self.assertIsNone(store.response)

    @mock.patch("server.triar_mensagem_ia", return_value={"tipo": "relato", "urgencia": "Urgente"})
    def test_motor_atual_e_o_padrao(self, _ia):
        store = StoreComMotor(motor="atual")
        with mock.patch("tuca_enxuto.respond") as respond:
            worker.process_inbox(store, _message(content="acabou o gelo aqui"))
        respond.assert_not_called()
        self.assertIsNotNone(store.feedback)

    @mock.patch("server.triar_mensagem_ia", return_value={"tipo": "relato", "urgencia": "Urgente"})
    def test_store_sem_a_chave_usa_o_motor_atual(self, _ia):
        store = FakeStore()
        worker.process_inbox(store, _message(content="acabou o gelo aqui"))
        self.assertIsNotNone(store.feedback)


class DeslizesDoAtualTests(unittest.TestCase):
    def setUp(self):
        for alvo in ("generate_ai_response", "classificar_com_ia"):
            p = mock.patch.object(server, alvo, lambda *a, **k: None)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(worker, "moderar_texto", return_value=LIBERADO)
        p.start()
        self.addCleanup(p.stop)

    @mock.patch("server.triar_mensagem_ia", return_value={
        "tipo": "relato", "urgencia": "Urgente", "lugar": "Atendimento ao Público",
        "ficha": {"id": "f1", "question": "Perdi minha pulseira", "answer": "Procure o SAC da pista."},
    })
    def test_ficha_oficial_dispensa_a_pergunta_de_lugar(self, _ia):
        store = FakeStore()
        worker.process_inbox(store, _message(content="perdi minha pulseira"))
        self.assertIn("SAC", store.response[1])
        self.assertNotIn("Em qual", store.response[1])
        self.assertNotIn("onde você está", store.response[1])

    @mock.patch("server.triar_mensagem_ia", return_value={
        "tipo": "relato", "urgencia": "Urgente", "lugar": "Bares", "ficha": None,
    })
    def test_sem_ficha_a_pergunta_de_lugar_continua(self, _ia):
        store = FakeStore()
        worker.process_inbox(store, _message(content="acabou o gelo"))
        self.assertIn("Em qual bar?", store.response[1])

    def test_link_do_painel_nunca_vai_para_o_publico(self):
        self.assertEqual(server.link_publico_do_app("https://app.nodedata.com.br/"), "")
        self.assertEqual(server.link_publico_do_app("  "), "")
        self.assertEqual(server.link_publico_do_app("https://tropicadelia.app/x"), "https://tropicadelia.app/x")

    def test_regras_nao_carregam_o_link_do_painel(self):
        with mock.patch.object(server, "_bot_config", return_value={
            "settings": {"appUrl": "https://app.nodedata.com.br/"},
            "rules": [{"title": "Nunca inventar", "body": "Se não sabe, diga."}],
        }):
            bloco = server._rules_block("en")
        self.assertNotIn("nodedata", bloco)
        self.assertIn("no app link", bloco)


class PromptDoRelatoTests(unittest.TestCase):
    def test_relato_manda_nao_mandar_para_o_app(self):
        cliente = mock.MagicMock()
        resposta = mock.MagicMock()
        resposta.choices = [mock.MagicMock()]
        resposta.choices[0].message.content = "Registrei, já está com a equipe."
        cliente.chat.completions.create.return_value = resposta
        with mock.patch.object(server, "_openai_chat_client", return_value=cliente), \
                mock.patch.object(server, "_bot_config", return_value={"settings": {}, "rules": []}), \
                mock.patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}):
            server.generate_ai_response("a fila do banheiro tá enorme", "Estrutura & Espaço", "Urgente")
        prompt = cliente.chat.completions.create.call_args.kwargs["messages"][1]["content"]
        self.assertIn("do NOT send them to the app", prompt)
        sistema = cliente.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        self.assertIn("Never guess where something is", sistema)


class RotaDoMotorTests(unittest.TestCase):
    def setUp(self):
        self.client = server.app.test_client()
        with self.client.session_transaction() as s:
            s["logged_in"] = True

    def test_le_e_troca_o_motor(self):
        with mock.patch.object(server.EVENT_STORE, "motor_ativo", return_value="atual"):
            r = self.client.get("/api/bot/motor")
        self.assertEqual(r.get_json(), {"motor": "atual", "opcoes": ["atual", "enxuto"]})
        with mock.patch.object(server.EVENT_STORE, "definir_motor", return_value="enxuto") as definir:
            r = self.client.post("/api/bot/motor", json={"motor": "enxuto"})
        self.assertEqual(r.status_code, 200)
        definir.assert_called_once_with("enxuto")

    def test_motor_desconhecido_e_recusado(self):
        with mock.patch.object(server.EVENT_STORE, "definir_motor") as definir:
            r = self.client.post("/api/bot/motor", json={"motor": "gpt"})
        self.assertEqual(r.status_code, 400)
        definir.assert_not_called()

    def test_exige_login(self):
        anonimo = server.app.test_client()
        self.assertEqual(anonimo.post("/api/bot/motor", json={"motor": "enxuto"}).status_code, 302)

    def test_nomes_dos_motores(self):
        self.assertEqual(EventStore.MOTORES, ("atual", "enxuto"))


if __name__ == "__main__":
    unittest.main()
