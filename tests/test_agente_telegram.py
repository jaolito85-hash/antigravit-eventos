"""Testes do agente de operação no Telegram.

O que está protegido aqui: só chat autorizado fala com o agente, a varredura
avisa cada problema uma vez, a correção só roda pelo catálogo e com o botão
apertado uma vez, e as leituras nunca carregam dado pessoal.
"""

import unittest
from datetime import timedelta
from unittest import mock

import monitor
import telegram_agent
from monitor import CORRECOES, Achado, Monitor, agora, iso
from telegram_agent import AgenteTelegram, texto_alerta, texto_resumo


class TelegramFalso:
    def __init__(self):
        self.enviadas = []
        self.editadas = []
        self.callbacks = []

    def enviar(self, chat_id, texto, botoes=None, html=True, responder_a=None):
        self.enviadas.append((str(chat_id), texto, botoes))
        return {"message_id": len(self.enviadas)}

    def editar(self, chat_id, message_id, texto, botoes=None):
        self.editadas.append((texto, botoes))

    def responder_callback(self, cb_id, texto=""):
        self.callbacks.append(texto)

    def digitando(self, chat_id):
        pass


class RegistroFalso:
    def __init__(self):
        self.linhas = {}
        self._seq = 0

    def abertos(self):
        return [a for a in self.linhas.values() if a["status"] == "aberto"]

    def ignorados_recentes(self, horas=6):
        return {a["chave"] for a in self.linhas.values() if a["status"] == "ignorado"}

    def recentes(self, limite=10):
        return list(self.linhas.values())[-limite:]

    def por_id(self, alerta_id):
        return self.linhas.get(alerta_id)

    def abrir(self, achado):
        self._seq += 1
        alerta = {
            "id": f"a{self._seq}", "chave": achado.chave, "gravidade": achado.gravidade,
            "titulo": achado.titulo, "detalhe": achado.detalhe, "acao": achado.acao,
            "status": "aberto", "created_at": iso(agora()), "decidido_por": None, "resultado": None,
        }
        self.linhas[alerta["id"]] = alerta
        return alerta

    def anotar_mensagem(self, alerta_id, chat_id, message_id):
        self.linhas[alerta_id]["telegram_message_id"] = message_id

    def fechar(self, alerta_id, status, resultado=None, por=None):
        self.linhas[alerta_id].update({"status": status, "resultado": resultado, "decidido_por": por})


class MonitorFalso:
    def __init__(self, achados=None):
        self.achados = achados or []
        self.corrigidas = []

    def varrer(self):
        return list(self.achados)

    def corrigir(self, acao):
        self.corrigidas.append(acao)
        return f"rodou {acao}"

    def criticos_desde(self, momento):
        return []


def novo_agente(achados=None):
    tg = TelegramFalso()
    agente = AgenteTelegram(tg, MonitorFalso(achados), RegistroFalso(), {"-100"}, "-100")
    return agente, tg


PRESAS = Achado("presas_processando", "atencao", "Mensagens presas", "3 presas", acao="destravar_processando", quantidade=3)
APP_FORA = Achado("app_fora", "critico", "O app não responde", "HTTP 503")


class AutorizacaoTests(unittest.TestCase):
    def test_chat_desconhecido_so_recebe_o_id(self):
        agente, tg = novo_agente()
        agente.tratar_update({"message": {"chat": {"id": 555, "type": "private"}, "text": "/resumo"}})
        self.assertEqual(tg.enviadas, [])
        agente.tratar_update({"message": {"chat": {"id": 555, "type": "private"}, "text": "/id"}})
        self.assertIn("555", tg.enviadas[0][1])

    def test_botao_de_chat_desconhecido_nao_corrige(self):
        agente, tg = novo_agente([PRESAS])
        agente.executar_varredura()
        alerta_id = next(iter(agente.registro.linhas))
        agente.tratar_update({"callback_query": {
            "id": "cb", "data": f"fix:{alerta_id}", "from": {"first_name": "Intruso"},
            "message": {"chat": {"id": 999}, "message_id": 1},
        }})
        self.assertEqual(agente.monitor.corrigidas, [])
        self.assertEqual(agente.registro.linhas[alerta_id]["status"], "aberto")

    def test_comando_com_arroba_do_grupo_e_reconhecido(self):
        agente, _ = novo_agente()
        self.assertEqual(agente._parse_comando("/resumo@TucaBot 6"), ("resumo", "6"))
        self.assertEqual(agente._parse_comando("oi, tudo bem?"), (None, ""))


class VarreduraTests(unittest.TestCase):
    def test_avisa_uma_vez_e_fecha_quando_some(self):
        agente, tg = novo_agente([PRESAS, APP_FORA])
        agente.executar_varredura()
        self.assertEqual(len(tg.enviadas), 2)
        # Segunda varredura com os mesmos problemas: silêncio.
        agente.executar_varredura()
        self.assertEqual(len(tg.enviadas), 2)
        # O app voltou: avisa que resolveu e fecha o alerta.
        agente.monitor.achados = [PRESAS]
        agente.executar_varredura()
        self.assertEqual(len(tg.enviadas), 3)
        self.assertIn("Resolvido", tg.enviadas[-1][1])
        status = {a["chave"]: a["status"] for a in agente.registro.linhas.values()}
        self.assertEqual(status, {"presas_processando": "aberto", "app_fora": "resolvido"})

    def test_botao_so_aparece_quando_ha_correcao_no_catalogo(self):
        agente, tg = novo_agente([PRESAS, APP_FORA])
        agente.executar_varredura()
        por_titulo = {texto.split("</b>")[0]: botoes for _, texto, botoes in tg.enviadas}
        presas = [b for t, b in por_titulo.items() if "presas" in t][0]
        app = [b for t, b in por_titulo.items() if "app" in t][0]
        self.assertTrue(any(b["callback_data"].startswith("fix:") for b in presas[0]))
        self.assertFalse(any(b["callback_data"].startswith("fix:") for b in app[0]))

    def test_ignorado_nao_volta_a_avisar(self):
        agente, tg = novo_agente([PRESAS])
        agente.executar_varredura()
        alerta_id = next(iter(agente.registro.linhas))
        agente.tratar_update({"callback_query": {
            "id": "cb", "data": f"ign:{alerta_id}", "from": {"first_name": "Lucas"},
            "message": {"chat": {"id": -100}, "message_id": 1},
        }})
        agente.executar_varredura()
        self.assertEqual(len(tg.enviadas), 1)
        self.assertEqual(agente.registro.linhas[alerta_id]["decidido_por"], "Lucas")


class CorrecaoTests(unittest.TestCase):
    def test_confirmar_roda_a_correcao_e_registra_quem(self):
        agente, tg = novo_agente([PRESAS])
        agente.executar_varredura()
        alerta_id = next(iter(agente.registro.linhas))
        agente.tratar_update({"callback_query": {
            "id": "cb", "data": f"fix:{alerta_id}", "from": {"first_name": "Lucas", "last_name": "Sócio"},
            "message": {"chat": {"id": -100}, "message_id": 7},
        }})
        self.assertEqual(agente.monitor.corrigidas, ["destravar_processando"])
        alerta = agente.registro.linhas[alerta_id]
        self.assertEqual(alerta["status"], "corrigido")
        self.assertEqual(alerta["decidido_por"], "Lucas Sócio")
        self.assertIn("rodou destravar_processando", tg.editadas[-1][0])

    def test_segundo_clique_nao_roda_de_novo(self):
        agente, tg = novo_agente([PRESAS])
        agente.executar_varredura()
        alerta_id = next(iter(agente.registro.linhas))
        cb = {"callback_query": {
            "id": "cb", "data": f"fix:{alerta_id}", "from": {"first_name": "Lucas"},
            "message": {"chat": {"id": -100}, "message_id": 7},
        }}
        agente.tratar_update(cb)
        agente.tratar_update(cb)
        self.assertEqual(len(agente.monitor.corrigidas), 1)
        self.assertIn("Já tratado", tg.callbacks[-1])

    def test_catalogo_so_tem_correcoes_reais(self):
        store = mock.MagicMock()
        m = Monitor(store, health_url="http://x/health")
        for nome, (rotulo, funcao) in CORRECOES.items():
            self.assertTrue(rotulo)
            self.assertTrue(callable(funcao), nome)
        self.assertIn("Não conheço", m.corrigir("apagar_tudo"))


class MonitorTests(unittest.TestCase):
    def _monitor(self):
        store = mock.MagicMock()
        store.event_id.return_value = "evt"
        store.list_sectors.return_value = [{"id": "s1", "code": "PALCO", "name": "Palco Principal"}]
        return Monitor(store, health_url="http://x/health")

    def test_chamado_publico_nao_carrega_dado_pessoal(self):
        m = self._monitor()
        publico = m._chamado_publico({
            "id": 9, "message": "faltou papel", "urgency": "Critico", "category": "Estrutura",
            "status": "aberto", "created_at": iso(agora()), "sector_id": "s1",
            "sender_hash": "abc", "sender": "+55", "name": "Fulano",
        })
        self.assertEqual(publico["setor"], "Palco Principal")
        self.assertEqual(publico["urgencia"], "Crítico")
        for proibido in ("sender", "sender_hash", "name", "telefone"):
            self.assertNotIn(proibido, publico)

    def test_varredura_isola_checagem_quebrada(self):
        m = self._monitor()
        with mock.patch.object(Monitor, "_checar_app", side_effect=RuntimeError("boom")), \
                mock.patch.object(Monitor, "_inbox_esperando", return_value=[{"next_attempt_at": iso(agora() - timedelta(minutes=8))}]), \
                mock.patch.object(Monitor, "_inbox_presas", return_value=[]), \
                mock.patch.object(Monitor, "_inbox_esgotadas", return_value=[]), \
                mock.patch.object(Monitor, "_inbox_pendentes", return_value=0), \
                mock.patch.object(Monitor, "_saidas_canceladas", return_value=[]), \
                mock.patch.object(Monitor, "_criticos_abertos", return_value=[]), \
                mock.patch.object(Monitor, "_checar_meta", return_value={"ok": None}), \
                mock.patch.object(Monitor, "_checar_ia", return_value={"ok": None}):
            achados = m.varrer()
        self.assertEqual([a.chave for a in achados], ["worker_parado"])
        self.assertEqual(achados[0].gravidade, "critico")

    def test_nao_entregues_so_oferece_reenvio_do_que_a_meta_nao_viu(self):
        m = self._monitor()
        recusadas = [{"id": "o1", "provider_message_id": "wamid", "last_error": "MetaAPIError: 131026"}]
        with mock.patch.object(Monitor, "_saidas_canceladas", return_value=recusadas):
            achado = m._achado_nao_entregues()
        self.assertIsNone(achado.acao)
        with mock.patch.object(Monitor, "_saidas_canceladas", return_value=recusadas + [{"id": "o2", "provider_message_id": None}]):
            achado = m._achado_nao_entregues()
        self.assertEqual(achado.acao, "reenviar_cancelados")

    def test_tempo_de_resposta_ignora_operador(self):
        base = agora()
        feedbacks = [{"id": 1, "inbox_message_id": "in1"}]
        recebidas = [{"id": "in1", "created_at": iso(base)}]
        entregas = [
            {"feedback_id": 1, "origin": "bot", "sent_at": iso(base + timedelta(seconds=4))},
            {"feedback_id": 1, "origin": "operator", "sent_at": iso(base + timedelta(minutes=30))},
        ]
        tempos = Monitor._tempos_de_resposta(feedbacks, entregas, recebidas)
        self.assertEqual(tempos["amostras"], 1)
        self.assertEqual(tempos["mediana"], 4.0)


class TextosTests(unittest.TestCase):
    def test_alerta_escapa_html_e_anuncia_correcao(self):
        texto = texto_alerta(Achado("x", "atencao", "Erro <b>", "detalhe & tal", acao="destravar_processando"))
        self.assertIn("Erro &lt;b&gt;", texto)
        self.assertIn("detalhe &amp; tal", texto)
        self.assertIn("Confirme no botão", texto)

    def test_resumo_sem_amostra_nao_quebra(self):
        texto = texto_resumo({
            "janela_horas": 24, "mensagens_recebidas": 0, "audios": 0, "processamento": {},
            "chamados": 0, "por_urgencia": {}, "por_status": {}, "por_categoria": {}, "por_setor": {},
            "respostas_enviadas": 0, "entregas": {}, "tempo_resposta_seg": {"amostras": 0},
        })
        self.assertIn("sem amostra", texto)


class IAForaTests(unittest.TestCase):
    def test_sem_ia_o_texto_livre_recebe_a_ajuda(self):
        agente, tg = novo_agente()
        with mock.patch.object(telegram_agent.Cerebro, "responder", return_value=None):
            agente.tratar_update({"message": {"chat": {"id": -100, "type": "supergroup"}, "text": "como está o festival?"}})
        self.assertIn("/resumo", tg.enviadas[-1][1])


if __name__ == "__main__":
    unittest.main()
