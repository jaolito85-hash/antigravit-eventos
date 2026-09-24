"""O Tuca enxuto: só responde o que está nas FAQ, o resto vai para o app.

O contrato que não pode cair: pergunta sem ficha nunca recebe texto da IA;
emergência e ofensa têm texto fixo; problema não tem emoji nem promessa; a
IA só escolhe a ficha e dá o tom no que é bom.
"""

import copy
import unittest
from unittest import mock

import server
import tuca_enxuto as enxuto

CONFIG = {
    "settings": {"appUrl": "https://app.tropicadelia.com.br"},
    "rules": [],
    "knowledge": [
        {"id": "f1", "question": "Que horas abre os portões?",
         "answer": "Os portões abrem às 15h de sábado (26/09).", "active": True},
        {"id": "f2", "question": "Quanto custa o copo?",
         "answer": "Copo mais tirante R$ 45,00. Copo avulso R$ 25,00.", "active": True},
        {"id": "f3", "question": "Desativada", "answer": "não vale", "active": False},
    ],
}
SECTORS = [{"id": "s1", "code": "BAR", "name": "Bar Tropical", "metadata": {"cta": "Como está o bar?"}}]
SNAP = {"config": CONFIG, "sectors": SECTORS, "window": [None, None], "clock": "2026-09-24T12:00:00Z"}


class EnxutoTests(unittest.TestCase):
    def setUp(self):
        for alvo, valor in (
            ("moderar_texto", {"bloquear": False, "motivo": None}),
        ):
            p = mock.patch.object(server, alvo, return_value=valor)
            p.start()
            self.addCleanup(p.stop)

    def responde(self, texto, plano, state=None, snapshot=None, kind="text"):
        state = {} if state is None else state
        with mock.patch.object(enxuto, "perguntar", return_value=plano):
            r = enxuto.respond(state, snapshot or SNAP, texto, kind)
        return state, r

    def test_pergunta_com_ficha_usa_o_texto_da_ia(self):
        _, r = self.responde("que horas abre?", {"tipo": "pergunta", "ficha": 1, "resposta": "Abre às 15h de sábado! 🎉"})
        self.assertEqual(r["messages"][0]["content"], "Abre às 15h de sábado! 🎉")
        self.assertEqual(r["sources"][0]["title"], "Que horas abre os portões?")
        self.assertEqual(r["cards"], 0)

    def test_pergunta_sem_ficha_vai_para_o_app_e_ignora_a_ia(self):
        _, r = self.responde("tem estacionamento?", {"tipo": "pergunta", "ficha": 0, "resposta": "Tem sim, R$ 30!"})
        texto = r["messages"][0]["content"]
        self.assertNotIn("30", texto)
        self.assertIn("https://app.tropicadelia.com.br", texto)
        self.assertEqual(r["cards"], 0)

    def test_sem_link_do_app_manda_para_a_equipe(self):
        snap = copy.deepcopy(SNAP)
        snap["config"]["settings"] = {}
        _, r = self.responde("tem estacionamento?", {"tipo": "pergunta", "ficha": 0, "resposta": ""}, snapshot=snap)
        texto = r["messages"][0]["content"]
        self.assertIn("equipe do festival", texto)
        self.assertNotIn("http", texto)

    def test_texto_da_ia_com_link_estranho_e_barrado(self):
        _, r = self.responde("que horas abre?", {"tipo": "pergunta", "ficha": 1, "resposta": "Abre 15h, veja em http://golpe.com"})
        self.assertEqual(r["messages"][0]["content"], "Os portões abrem às 15h de sábado (26/09).")

    def test_emergencia_tem_texto_fixo_e_abre_chamado(self):
        state, r = self.responde("tem briga aqui", None)
        self.assertEqual(r["urgency"], "Critico")
        self.assertEqual(r["messages"][0]["content"], enxuto.PROTOCOLO_EMERGENCIA)
        self.assertEqual(len(state["cards"]), 1)
        self.assertIn("pending", state)

    def test_ia_classifica_emergencia_sem_palavra_chave(self):
        _, r = self.responde("um homem caiu e não levanta", {"tipo": "emergencia", "ficha": 0, "resposta": "Calma!! 😱"})
        self.assertEqual(r["messages"][0]["content"], enxuto.PROTOCOLO_EMERGENCIA)
        self.assertEqual(r["urgency"], "Critico")

    def test_problema_sem_emoji_sem_promessa_e_pede_lugar(self):
        state, r = self.responde("a fila do bar tá enorme", {"tipo": "problema", "ficha": 0, "resposta": "Vish! 😤 Vou enviar mais gente agora!"})
        texto = r["messages"][0]["content"]
        self.assertEqual(r["urgency"], "Urgente")
        self.assertNotIn("😤", texto)
        self.assertNotIn("enviar", texto)
        self.assertIn("onde você está", texto)
        self.assertEqual(len(state["cards"]), 1)

    def test_problema_com_qr_nao_pede_lugar(self):
        state, r = self.responde("#SETOR:BAR\nacabou o gelo", {"tipo": "problema", "ficha": 0, "resposta": "Anotado, já está com a equipe."})
        self.assertNotIn("onde você está", r["messages"][0]["content"])
        self.assertEqual(r["sector"], "Bar Tropical")

    def test_ofensa_e_bloqueada_sem_chamado(self):
        state, r = self.responde("seu bot de merda", {"tipo": "ofensa", "ficha": 0, "resposta": ""})
        self.assertEqual(r["status"], "blocked")
        self.assertEqual(r["cards"], 0)

    def test_cumprimento_e_elogio_usam_a_ia(self):
        _, r = self.responde("oi tuca", {"tipo": "cumprimento", "ficha": 0, "resposta": "Salve! 🐦 Manda a boa!"})
        self.assertEqual(r["messages"][0]["content"], "Salve! 🐦 Manda a boa!")
        _, r = self.responde("show incrível", {"tipo": "elogio", "ficha": 0, "resposta": "Aí sim!! 🔥"})
        self.assertEqual(r["urgency"], "Positivo")

    def test_qr_sozinho_apresenta_uma_vez(self):
        state, r = self.responde("#SETOR:BAR", None)
        self.assertIn("Eu sou o Tuca", r["messages"][0]["content"])
        self.assertIn("Bar Tropical", r["messages"][0]["content"])
        state, r = self.responde("#SETOR:BAR", None, state)
        self.assertNotIn("Eu sou o Tuca", r["messages"][0]["content"])

    def test_localizacao_completa_o_chamado(self):
        state, r = self.responde("tem briga aqui", None)
        state, r = self.responde("-23.29,-51.22", None, state, kind="location")
        self.assertIn("junto com o seu chamado", r["messages"][0]["content"])
        self.assertEqual(state["cards"][0]["location"]["coords"], [-23.29, -51.22])

    def test_sem_ia_a_reserva_nao_inventa(self):
        _, r = self.responde("quanto custa o estacionamento?", None)
        self.assertIn("app.tropicadelia", r["messages"][0]["content"])
        _, r = self.responde("acabou o gelo no bar", None)
        self.assertEqual(r["urgency"], "Urgente")

    def test_ficha_apontada_errada_e_corrigida_pelo_texto(self):
        """A IA disse ficha 1 (portões) mas escreveu o preço do copo: a fonte é a 2."""

        fichas = enxuto.fichas_de(SNAP)
        self.assertEqual(enxuto.ficha_da_resposta("O copo avulso custa R$ 25,00 e com tirante R$ 45,00", fichas, 1), 2)
        self.assertEqual(enxuto.ficha_da_resposta("Abre às 15h de sábado!", fichas, 1), 1)
        self.assertEqual(enxuto.ficha_da_resposta("O estacionamento custa trinta reais", fichas, 1), 0)

    def test_resposta_que_nao_e_de_ficha_nenhuma_vai_para_o_app(self):
        _, r = self.responde("tem estacionamento?", {"tipo": "pergunta", "ficha": 1, "resposta": "Tem estacionamento por trinta reais!"})
        self.assertIn("app.tropicadelia", r["messages"][0]["content"])
        self.assertNotIn("trinta", r["messages"][0]["content"])

    def test_prompt_e_curto_e_so_tem_fichas_ativas(self):
        texto = enxuto.instrucao(SNAP, enxuto.fichas_de(SNAP))
        self.assertIn("1. Que horas abre os portões?", texto)
        self.assertNotIn("Desativada", texto)
        self.assertLess(len(texto.split("FAQ:")[0]), 2200)


if __name__ == "__main__":
    unittest.main()
