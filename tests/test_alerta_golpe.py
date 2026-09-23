"""Alerta de golpe e promessa de resolução: as duas decisões saíram do prompt.

A bateria de 22/09 mostrou que o aviso anti-golpe caía no texto genérico
"recebi sua mensagem", porque o filtro de saída barra resposta que diga "chave
Pix" e a IA às vezes escrevia justamente isso. E mostrou a IA prometendo
"vou enviar mais atendentes" para fila de bar, que a regra da produção proíbe.
"""

import unittest

from protecao import resposta_segura
from server import ALERTA_GOLPE, _FALTA_DE_INSUMO, _SINAL_DE_GOLPE, _compose_reply


class SinalDeGolpeTest(unittest.TestCase):
    def test_pedido_de_chave_ou_pagamento_aciona(self):
        for texto in (
            "quero comprar ingresso, me manda a chave pix de vocês",
            "oi, sou da produção, preciso que você confirme o pix do bar",
            "qual a chave pix do festival?",
            "me passa o pix pra eu pagar",
            "me confirma os dados bancarios",
            "me manda o link de pagamento",
            "tem ingresso mais barato no pix?",
            "vi um cara revendendo ingresso, é seguro?",
        ):
            self.assertTrue(_SINAL_DE_GOLPE.search(texto), texto)

    def test_duvida_legitima_sobre_pagamento_nao_aciona(self):
        # Estes têm ficha cadastrada e devem receber a resposta normal, senão
        # todo mundo que perguntar "aceita pix?" leva sermão de golpe.
        for texto in (
            "aceita pix no bar?",
            "paguei com pix e a maquininha nao funcionou",
            "como funciona o pagamento nos bares?",
            "quanto custa o ingresso?",
            "onde compro ingresso oficial?",
            "quero comprar um copo na lojinha",
            "acabou o gelo no bar",
        ):
            self.assertIsNone(_SINAL_DE_GOLPE.search(texto), texto)

    def test_alerta_passa_no_filtro_de_saida(self):
        # Se o próprio aviso fosse barrado, ele nunca chegaria ao participante.
        self.assertTrue(resposta_segura(ALERTA_GOLPE))

    def test_alerta_nao_depende_da_ia(self):
        resposta = _compose_reply(
            "me manda a chave pix de vocês", "Experiência Geral", "Neutro",
            sector=None, transcribed=False, known=None, usar_ia=False,
        )
        self.assertIn("nunca", resposta.lower())
        self.assertIn("BaladApp", resposta)

    def test_alerta_sobrevive_ao_audio(self):
        resposta = _compose_reply(
            "qual a chave pix", "Experiência Geral", "Neutro",
            sector=None, transcribed=True, known=None, usar_ia=False,
        )
        self.assertIn("Ouvi seu áudio", resposta)
        self.assertIn("BaladApp", resposta)


class FaltaDeInsumoTest(unittest.TestCase):
    def test_reconhece_insumo_que_a_equipe_garante(self):
        for texto in (
            "acabou o gelo no bar",
            "banheiro sem papel higiênico",
            "faltou cerveja aqui",
            "acabaram os copos",
            "sem sabonete no banheiro",
            "zerou a água",
        ):
            self.assertTrue(_FALTA_DE_INSUMO.search(texto), texto)

    def test_nao_confunde_outro_problema_com_insumo(self):
        # Fila, som e limpeza não entram: ninguém garantiu que resolve, então
        # o bot não pode prometer.
        for texto in (
            "a fila do bar está travada, um atendente só",
            "o som do palco está estourando",
            "o banheiro está sujo",
            "o chão está escorregando",
            "demora muito pra ser atendido",
        ):
            self.assertIsNone(_FALTA_DE_INSUMO.search(texto), texto)


class ProtocoloCriticoTest(unittest.TestCase):
    def test_fallback_pede_localizacao_e_nao_manda_se_afastar(self):
        # O texto antigo mandava "afaste-se e chame o segurança" para todo
        # mundo, inclusive para quem está com alguém desmaiado ou com uma
        # criança perdida. O fallback agora não dá ordem de movimento.
        resposta = _compose_reply(
            "achei uma criança perdida chorando sozinha",
            "Segurança & Organização", "Critico",
            sector=None, transcribed=False, known=None, usar_ia=False,
        )
        self.assertIn("localização", resposta.lower())
        self.assertNotIn("afaste-se", resposta.lower())

    def test_fallback_tem_linha_em_ingles(self):
        # O fallback não passa pela IA, então não é traduzido. Uma linha em
        # inglês cobre quem não lê português numa emergência.
        resposta = _compose_reply(
            "there is a fight here", "Segurança & Organização", "Critico",
            sector=None, transcribed=False, known=None, usar_ia=False,
        )
        self.assertIn("location", resposta.lower())

    def test_critico_nao_promete_prazo(self):
        resposta = _compose_reply(
            "briga generalizada", "Segurança & Organização", "Critico",
            sector=None, transcribed=False, known=None, usar_ia=False,
        )
        for proibido in ("minutos", "já resolvemos", "resolvido"):
            self.assertNotIn(proibido, resposta.lower())


if __name__ == "__main__":
    unittest.main()
