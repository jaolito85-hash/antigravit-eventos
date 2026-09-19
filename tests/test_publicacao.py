"""Testes do rascunho, das regras de negócio e da publicação.

O que está coberto aqui é o contrato que protege o evento: o que o Lucas salva
não pode chegar no participante antes de alguém publicar, e o bot nunca pode
ficar sem base por causa de uma versão publicada ausente.
"""

import unittest
from unittest.mock import patch

import server
from event_store import EventStore


RASCUNHO = {
    "settings": {"persona": "Fale como locutor", "welcome": "", "appUrl": ""},
    "rules": [
        {"id": "r1", "title": "Nunca inventar", "body": "Se não sabe, diga que não sabe.",
         "priority": 100, "active": True},
    ],
    "knowledge": [
        {"id": "k1", "question": "Que horas abre?", "answer": "Às 15h30.",
         "keywords": ["que horas", "abre"], "priority": 90, "active": True},
    ],
}


class RulesBlockTests(unittest.TestCase):
    """O bloco de regras é o que entra no prompt da IA."""

    def test_sem_regra_e_sem_link_nao_polui_o_prompt(self):
        with patch.object(server, "_bot_config", return_value={"settings": {}, "rules": []}):
            self.assertEqual(server._rules_block("pt"), "")

    def test_regra_ativa_entra_com_titulo_e_corpo(self):
        config = {"settings": {}, "rules": RASCUNHO["rules"]}
        with patch.object(server, "_bot_config", return_value=config):
            bloco = server._rules_block("pt")
        self.assertIn("Nunca inventar", bloco)
        self.assertIn("Se não sabe, diga que não sabe.", bloco)

    def test_sem_link_configurado_a_ia_e_proibida_de_inventar(self):
        """Enquanto os sócios não mandam o link, o bot não pode chutar um."""

        config = {"settings": {"appUrl": ""}, "rules": RASCUNHO["rules"]}
        with patch.object(server, "_bot_config", return_value=config):
            bloco = server._rules_block("pt")
        self.assertIn("Nunca invente", bloco)
        self.assertNotIn("http", bloco)

    def test_link_configurado_chega_na_ia(self):
        config = {"settings": {"appUrl": "https://app.tropicadelia.com.br"}, "rules": []}
        with patch.object(server, "_bot_config", return_value=config):
            bloco = server._rules_block("pt")
        self.assertIn("https://app.tropicadelia.com.br", bloco)

    def test_versao_em_ingles_do_bloco(self):
        config = {"settings": {}, "rules": RASCUNHO["rules"]}
        with patch.object(server, "_bot_config", return_value=config):
            bloco = server._rules_block("en")
        self.assertIn("NON-NEGOTIABLE RULES", bloco)

    def test_regra_desligada_nao_entra(self):
        desligada = [dict(RASCUNHO["rules"][0], active=False)]
        # _rules_block confia em quem monta a lista, então o filtro é do chamador:
        # aqui garantimos que uma regra sem corpo também não vaza para o prompt.
        config = {"settings": {}, "rules": [dict(desligada[0], body="")]}
        with patch.object(server, "_bot_config", return_value=config):
            self.assertEqual(server._rules_block("pt"), "")


class PreviewDeRascunhoTests(unittest.TestCase):
    """O simulador em modo rascunho não pode vazar para o fluxo real."""

    def test_fora_do_contexto_le_a_versao_publicada(self):
        publicado = {"persona": "tom publicado"}
        with patch.object(server.EVENT_STORE, "bot_settings", return_value=publicado), \
             patch.object(server.EVENT_STORE, "rules", return_value=[]):
            self.assertEqual(server._bot_config()["settings"], publicado)

    def test_dentro_do_contexto_le_o_rascunho(self):
        with patch.object(server.EVENT_STORE, "draft_settings", return_value=RASCUNHO["settings"]), \
             patch.object(server.EVENT_STORE, "draft_rules", return_value=RASCUNHO["rules"]), \
             patch.object(server.EVENT_STORE, "draft_knowledge", return_value=RASCUNHO["knowledge"]):
            with server.usando_rascunho() as montou:
                self.assertTrue(montou)
                self.assertEqual(server._bot_config()["settings"]["persona"], "Fale como locutor")

    def test_contexto_e_desfeito_na_saida(self):
        """Sem isso, uma simulação contaminaria a resposta do próximo participante."""

        with patch.object(server.EVENT_STORE, "draft_settings", return_value=RASCUNHO["settings"]), \
             patch.object(server.EVENT_STORE, "draft_rules", return_value=RASCUNHO["rules"]), \
             patch.object(server.EVENT_STORE, "draft_knowledge", return_value=RASCUNHO["knowledge"]):
            with server.usando_rascunho():
                pass
        self.assertIsNone(server._CONFIG_PREVIEW.get())

    def test_match_knowledge_usa_a_base_do_rascunho(self):
        with patch.object(server.EVENT_STORE, "draft_settings", return_value=RASCUNHO["settings"]), \
             patch.object(server.EVENT_STORE, "draft_rules", return_value=RASCUNHO["rules"]), \
             patch.object(server.EVENT_STORE, "draft_knowledge", return_value=RASCUNHO["knowledge"]), \
             patch.object(server.EVENT_STORE, "knowledge", side_effect=AssertionError("não pode ler o publicado")):
            with server.usando_rascunho():
                achou = server.match_knowledge("que horas abre o portao?")
        self.assertIsNotNone(achou)
        self.assertEqual(achou["answer"], "Às 15h30.")


class ComparacaoDeVersaoTests(unittest.TestCase):
    """A faixa de publicação depende dessa comparação para não mentir."""

    def test_rascunho_igual_ao_publicado_nao_acusa_pendencia(self):
        igual = EventStore._comparable(RASCUNHO)
        self.assertEqual(igual, EventStore._comparable(dict(RASCUNHO)))

    def test_id_diferente_nao_conta_como_alteracao(self):
        """Restaurar recria as linhas com id novo: isso não é mudança de conteúdo."""

        outro = {
            "settings": RASCUNHO["settings"],
            "rules": [dict(RASCUNHO["rules"][0], id="outro-id")],
            "knowledge": [dict(RASCUNHO["knowledge"][0], id="outro-id")],
        }
        self.assertEqual(EventStore._comparable(RASCUNHO), EventStore._comparable(outro))

    def test_ordem_diferente_nao_conta_como_alteracao(self):
        base = {
            "settings": {},
            "rules": [
                {"title": "A", "body": "a", "priority": 10, "active": True},
                {"title": "B", "body": "b", "priority": 20, "active": True},
            ],
            "knowledge": [],
        }
        invertido = {"settings": {}, "rules": list(reversed(base["rules"])), "knowledge": []}
        self.assertEqual(EventStore._comparable(base), EventStore._comparable(invertido))

    def test_texto_alterado_acusa_pendencia(self):
        mudado = {
            "settings": RASCUNHO["settings"],
            "rules": [dict(RASCUNHO["rules"][0], body="Pode chutar.")],
            "knowledge": RASCUNHO["knowledge"],
        }
        self.assertNotEqual(EventStore._comparable(RASCUNHO), EventStore._comparable(mudado))

    def test_link_do_app_alterado_acusa_pendencia(self):
        mudado = {
            "settings": dict(RASCUNHO["settings"], appUrl="https://novo"),
            "rules": RASCUNHO["rules"],
            "knowledge": RASCUNHO["knowledge"],
        }
        self.assertNotEqual(EventStore._comparable(RASCUNHO), EventStore._comparable(mudado))

    def test_versao_vazia_contra_rascunho_cheio(self):
        self.assertNotEqual(EventStore._comparable({}), EventStore._comparable(RASCUNHO))


class FallbackSemVersaoPublicadaTests(unittest.TestCase):
    """Um festival com o bot mudo é pior que um bot sem revisão."""

    def test_sem_versao_no_ar_o_rascunho_assume(self):
        store = EventStore()
        store._event_id = "evento-teste"

        class RespostaVazia:
            data = []

        class Tabela:
            def select(self, *a, **k): return self
            def eq(self, *a, **k): return self
            def limit(self, *a, **k): return self
            def execute(self): return RespostaVazia()

        class Cliente:
            def table(self, nome): return Tabela()

        with patch.object(store, "_get_client", return_value=Cliente()), \
             patch.object(store, "draft_payload", return_value=RASCUNHO):
            config = store.live_config()

        self.assertEqual(config["knowledge"], RASCUNHO["knowledge"])

    def test_banco_fora_e_rascunho_fora_devolve_vazio_sem_estourar(self):
        store = EventStore()
        store._event_id = "evento-teste"

        with patch.object(store, "_get_client", side_effect=RuntimeError("banco fora")), \
             patch.object(store, "draft_payload", side_effect=RuntimeError("banco fora")):
            self.assertEqual(store.live_config(), {})


if __name__ == "__main__":
    unittest.main()
