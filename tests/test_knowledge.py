"""Testes do casamento entre a mensagem e a base de perguntas do Tuca."""

import unittest

from server import _normalize, match_knowledge

BASE = [
    {
        "id": "1",
        "question": "Que horas começa e termina o festival?",
        "answer": "Abre às 15h30 e vai até as 4h.",
        "keywords": ["que horas", "horario", "abre", "termina"],
        "priority": 90,
        "active": True,
    },
    {
        "id": "2",
        "question": "Como funciona o pagamento nos bares?",
        "answer": "Cartão e Pix nos totens oficiais.",
        "keywords": ["pagamento", "pix", "cartao", "como pago"],
        "priority": 60,
        "active": True,
    },
    {
        "id": "3",
        "question": "Quem toca e a que horas?",
        "answer": "A grade está nos telões.",
        "keywords": ["line up", "quem toca", "show de"],
        "priority": 65,
        "active": True,
    },
    {
        "id": "4",
        "question": "Tem guarda-volumes no evento?",
        "answer": "Sim, os lockers ficam na zona central.",
        "keywords": ["locker", "guarda volumes"],
        "priority": 40,
        "active": False,
    },
]


class NormalizeTests(unittest.TestCase):
    def test_remove_acento_e_caixa(self):
        self.assertEqual(_normalize("Programação ÀS 15H"), "programacao as 15h")

    def test_valor_vazio(self):
        self.assertEqual(_normalize(None), "")


class MatchKnowledgeTests(unittest.TestCase):
    def test_gatilho_direto(self):
        entry = match_knowledge("que horas comeca o festival?", BASE)
        self.assertEqual(entry["id"], "1")

    def test_ignora_acento_e_caixa(self):
        entry = match_knowledge("QUE HORÁRIO abre o portão?", BASE)
        self.assertEqual(entry["id"], "1")

    def test_gatilho_com_palavra_no_meio(self):
        """"como pago" precisa pegar "como eu pago", senão a base não serve."""

        entry = match_knowledge("como eu pago a cerveja no bar", BASE)
        self.assertEqual(entry["id"], "2")

    def test_gatilho_de_duas_palavras_nao_degrada_para_uma(self):
        """"show de" não pode transformar todo elogio ao show em pergunta."""

        self.assertIsNone(match_knowledge("show incrivel, melhor da vida!", BASE))

    def test_reclamacao_nao_casa_com_a_base(self):
        self.assertIsNone(match_knowledge("o banheiro esta sujo e alagado", BASE))

    def test_pergunta_desativada_nao_responde(self):
        self.assertIsNone(match_knowledge("onde fica o locker?", BASE))

    def test_prioridade_desempata(self):
        """Mensagem que casa com duas perguntas fica com a de maior prioridade."""

        entry = match_knowledge("que horas abre e como funciona o pagamento?", BASE)
        self.assertEqual(entry["id"], "1")

    def test_mensagem_vazia(self):
        self.assertIsNone(match_knowledge("", BASE))

    def test_base_vazia(self):
        self.assertIsNone(match_knowledge("que horas abre?", []))

    def test_palavras_da_propria_pergunta_servem_de_gatilho(self):
        """Sem gatilho cadastrado, a pergunta em si ainda deve casar."""

        base = [{
            "id": "9",
            "question": "Onde fica o posto medico do festival?",
            "answer": "Zona Oeste, ao lado do Palco 3.",
            "keywords": [],
            "priority": 50,
            "active": True,
        }]
        entry = match_knowledge("onde fica o posto medico?", base)
        self.assertEqual(entry["id"], "9")


if __name__ == "__main__":
    unittest.main()
