"""Testes da ponte entre o Telegram e o agente da nuvem pelo GitHub.

Contrato protegido: problema investigável vira uma issue só; PR do agente da
nuvem é anunciado uma vez com botão; aprovar faz merge e fecha o anúncio;
rejeitar fecha o PR; chat de fora não aprova nada; e a varredura não fecha
anúncio de PR por conta própria.
"""

import unittest

from monitor import Achado
from telegram_agent import AgenteTelegram, corpo_da_issue
from tests.test_agente_telegram import MonitorFalso, RegistroFalso, TelegramFalso


class GitHubFalso:
    def __init__(self, prs=None):
        self.issues = []
        self.prs = prs or []
        self.merges = []
        self.fechados = []
        self.merge_ok = True

    def criar_issue(self, titulo, corpo):
        self.issues.append((titulo, corpo))
        return 100 + len(self.issues)

    def prs_abertos(self):
        return list(self.prs)

    def merge(self, numero, mensagem):
        self.merges.append((numero, mensagem))
        return (True, "abc123") if self.merge_ok else (False, "GitHub recusou o merge (HTTP 405): conflito")

    def fechar_pr(self, numero, comentario):
        self.fechados.append((numero, comentario))
        return True


def novo_agente(achados=None, prs=None):
    tg = TelegramFalso()
    gh = GitHubFalso(prs)
    agente = AgenteTelegram(tg, MonitorFalso(achados), RegistroFalso(), {"-100"}, "-100", gh)
    agente.monitor.erros = lambda horas=None, limite=10: {"processamento_falhou": [], "entrega_falhou": []}
    agente.monitor._checar_app = lambda: {"ok": True, "no_ar_desde": "20/09 15:00"}
    return agente, tg, gh


IA_FORA = Achado("ia_fora", "atencao", "A IA não está respondendo", "erro X", investigar=True)
CRITICOS = Achado("criticos_sem_atendimento", "critico", "Críticos sem atender", "3 abertos")
PR = {"numero": 12, "titulo": "fix: timeout da OpenAI", "corpo": "Sobe o timeout.\n\nTestes: 85 ok", "branch": "tuca/ia-fora", "url": "https://github.com/x/y/pull/12"}


class IssueTests(unittest.TestCase):
    def test_achado_investigavel_vira_uma_issue_e_o_outro_nao(self):
        agente, tg, gh = novo_agente([IA_FORA, CRITICOS])
        agente.executar_varredura()
        agente.executar_varredura()
        self.assertEqual(len(gh.issues), 1)
        self.assertIn("[Tuca] A IA não está respondendo", gh.issues[0][0])
        alerta = next(a for a in agente.registro.linhas.values() if a["chave"] == "ia_fora")
        self.assertEqual(alerta.get("github_issue"), 101)
        self.assertIn("Issue #101", [t for _, t, _ in tg.enviadas if "IA" in t][0])

    def test_corpo_da_issue_traz_contrato_e_nao_traz_dado_pessoal(self):
        corpo = corpo_da_issue(IA_FORA, {"entrega_falhou": [{"erro": "MetaAPIError: 131026", "chamado": 7}]})
        self.assertIn("tuca-agente", corpo)
        self.assertIn("prompt_agente_nuvem.md", corpo)
        self.assertIn("131026", corpo)
        self.assertNotIn("sender", corpo)


class PRTests(unittest.TestCase):
    def test_pr_e_anunciado_uma_vez_com_botoes(self):
        agente, tg, gh = novo_agente(prs=[PR])
        agente.vigiar_prs()
        agente.vigiar_prs()
        anuncios = [e for e in tg.enviadas if "PR #12" in e[1]]
        self.assertEqual(len(anuncios), 1)
        botoes = anuncios[0][2][0]
        self.assertEqual([b["callback_data"] for b in botoes], ["pr_ok:12", "pr_no:12"])
        self.assertIn("pr:12", {a["chave"] for a in agente.registro.linhas.values()})

    def test_reinicio_nao_anuncia_de_novo(self):
        agente, tg, gh = novo_agente(prs=[PR])
        agente.vigiar_prs()
        novo = AgenteTelegram(tg, agente.monitor, agente.registro, {"-100"}, "-100", gh)
        novo.vigiar_prs()
        self.assertEqual(len([e for e in tg.enviadas if "PR #12" in e[1]]), 1)

    def test_aprovar_faz_merge_fecha_anuncio_e_vigia_o_deploy(self):
        agente, tg, gh = novo_agente(prs=[PR])
        agente.vigiar_prs()
        agente.tratar_update({"callback_query": {
            "id": "cb", "data": "pr_ok:12", "from": {"first_name": "Lucas"},
            "message": {"chat": {"id": -100}, "message_id": 3},
        }})
        self.assertEqual(gh.merges[0][0], 12)
        self.assertIn("Lucas", gh.merges[0][1])
        alerta = next(a for a in agente.registro.linhas.values() if a["chave"] == "pr:12")
        self.assertEqual((alerta["status"], alerta["decidido_por"]), ("corrigido", "Lucas"))
        self.assertEqual(agente._deploy_esperado["pr"], 12)
        # O /health mudou: confirma no grupo e para de vigiar.
        agente.monitor._checar_app = lambda: {"ok": True, "no_ar_desde": "20/09 15:07"}
        agente.vigiar_deploy()
        self.assertIsNone(agente._deploy_esperado)
        self.assertIn("Versão nova no ar", tg.enviadas[-1][1])

    def test_merge_recusado_avisa_e_nao_fecha(self):
        agente, tg, gh = novo_agente(prs=[PR])
        gh.merge_ok = False
        agente.vigiar_prs()
        agente._aprovar_pr(12, "Lucas", -100)
        self.assertIn("Não consegui subir", tg.enviadas[-1][1])
        alerta = next(a for a in agente.registro.linhas.values() if a["chave"] == "pr:12")
        self.assertEqual(alerta["status"], "aberto")
        self.assertIsNone(agente._deploy_esperado)

    def test_rejeitar_fecha_o_pr(self):
        agente, tg, gh = novo_agente(prs=[PR])
        agente.vigiar_prs()
        agente.tratar_update({"message": {"chat": {"id": -100, "type": "supergroup"}, "text": "/rejeitar 12"}})
        self.assertEqual(gh.fechados[0][0], 12)
        self.assertEqual(gh.merges, [])
        alerta = next(a for a in agente.registro.linhas.values() if a["chave"] == "pr:12")
        self.assertEqual(alerta["status"], "ignorado")

    def test_chat_de_fora_nao_aprova(self):
        agente, tg, gh = novo_agente(prs=[PR])
        agente.tratar_update({"callback_query": {
            "id": "cb", "data": "pr_ok:12", "from": {"first_name": "Intruso"},
            "message": {"chat": {"id": 777}, "message_id": 3},
        }})
        agente.tratar_update({"message": {"chat": {"id": 777, "type": "private"}, "text": "/aprovar 12"}})
        self.assertEqual(gh.merges, [])

    def test_varredura_nao_fecha_anuncio_de_pr(self):
        agente, tg, gh = novo_agente(prs=[PR])
        agente.vigiar_prs()
        agente.executar_varredura()
        alerta = next(a for a in agente.registro.linhas.values() if a["chave"] == "pr:12")
        self.assertEqual(alerta["status"], "aberto")

    def test_sem_github_os_comandos_explicam(self):
        tg = TelegramFalso()
        agente = AgenteTelegram(tg, MonitorFalso(), RegistroFalso(), {"-100"}, "-100", None)
        agente.tratar_update({"message": {"chat": {"id": -100, "type": "supergroup"}, "text": "/prs"}})
        self.assertIn("GITHUB_TOKEN", tg.enviadas[-1][1])


if __name__ == "__main__":
    unittest.main()
