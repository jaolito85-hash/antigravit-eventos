"""Regressoes dos prints de WhatsApp de 26/09: intencao antes da arte."""
import unittest
from unittest.mock import patch
import server, worker
from tuca_intencao import permite_arte, agua_gratis, reserva_informativa
try:
    from test_worker import FakeStore, _message, LIBERADO
except ImportError:
    from tests.test_worker import FakeStore, _message, LIBERADO

MENU = {'id':'menu','question':'Cervejas e agua nos bares','answer':'CERVEJAS (à venda nos bares)\nBudweiser R$ 15','kind':'bar','image_url':'https://example.invalid/menu.png'}
PAYMENT = {'id':'pay','question':'Como compro bebida?','answer':'No caixa você compra as fichas. As formas de pagamento são pix, dinheiro e cartão.','kind':'faq','active':True}

class IntencaoTests(unittest.TestCase):
    def test_perguntas_informativas_nao_autorizam_arte(self):
        for text in ['Posso pagar cerveja no pix','aceita cartão?','tem cerveja?','sabe se tem seda?','onde é?','onde fica?','onde tem água?','Tem água grátis da torneira gelada?','onde fica o palco Hype?','quanto custa e onde compro?']:
            with self.subTest(text=text):
                self.assertFalse(permite_arte(text,MENU))

    def test_pedidos_de_cardapio_e_preco_autorizam_arte(self):
        for text in ['manda o cardápio','quero a arte','quanto custa a cerveja?']:
            self.assertTrue(permite_arte(text,MENU))
        self.assertTrue(permite_arte('quem toca no hype?',dict(MENU,kind='lineup')))
        self.assertFalse(permite_arte('onde fica o hype?',dict(MENU,kind='lineup')))

    def test_agua_gratis_e_temperatura_nao_confirmada(self):
        for text in ['To com sede onde tem agua de graça?','Tem água grátis da torneira gelada?','onde tem bebedouro?']:
            reply=agua_gratis(text)
            # Texto das fichas oficiais: um ponto, na pista (26/09).
            self.assertIn('ponto de hidratação na pista',reply)
            self.assertIn('equipe em campo',reply)
            self.assertNotIn('R$',reply)
        self.assertIn('Não tenho confirmação da temperatura',agua_gratis('tem água grátis gelada?'))

    def test_agua_nao_abafa_problema_nem_herda_assunto_antigo(self):
        for text in ['acabou a água grátis','água grátis, uma pessoa desmaiou','não tem água no bebedouro']:
            self.assertIsNone(agua_gratis(text))
        history=[{'direction':'out','content':agua_gratis('tem agua gratis?')}]
        self.assertIsNotNone(agua_gratis('onde fica?',history))
        history.append({'direction':'out','content':'Tem cerveja no bar.'})
        self.assertIsNone(agua_gratis('onde fica?',history))

    def test_local_sem_ia_nao_despeja_precos(self):
        reply=reserva_informativa('onde fica?',dict(MENU,answer='LOJA OFICIAL (na pista, perto da feirinha)\nSEDA R$ 5'))
        self.assertIn('feirinha',reply)
        self.assertNotIn('R$',reply)
        self.assertIn('qual lugar',reserva_informativa('onde é?',None))

    def test_pagamento_corrige_ficha_de_cardapio_errada(self):
        with patch.object(server,'_fichas_ativas',return_value=[MENU,PAYMENT]),patch.object(server,'generate_ai_response',return_value=None),patch.object(server,'_com_link_se_couber',side_effect=lambda x,u:x):
            reply=server._compose_reply('posso pagar cerveja no pix?','Alimentação & Bebidas','Neutro',None,False,known=MENU)
        self.assertIn('pix',reply)
        self.assertIn('caixa',reply)
        self.assertNotIn('R$',reply)

    def test_worker_erro_da_triagem_nao_vira_imagem(self):
        for text in ['posso pagar cerveja no pix?','tem cerveja?','onde é?','onde fica?']:
            with self.subTest(text=text):
                store=FakeStore(count=2)
                triagem={'tipo':'relato','urgencia':'Neutro','ficha':MENU,'setor':None,'lugar':None}
                with patch.object(worker,'moderar_texto',return_value=LIBERADO),patch.object(worker,'_atendimento_aprovado',return_value=False),patch.object(worker,'triar_mensagem',return_value=triagem),patch.object(worker,'_classify',return_value=('Neutro','Alimentação & Bebidas','N/A')),patch.object(worker,'_compose_reply',return_value='Resposta textual'):
                    worker.process_inbox(store,_message(content=text))
                self.assertIsNone(store.failed)
                # Disponibilidade ganha o convite para a arte; os outros, só texto.
                esperado='Resposta textual'
                if text=='tem cerveja?':
                    esperado+=f'\n\n{worker.PERGUNTA_ARTE_VALORES}'
                self.assertEqual(store.responses,[esperado])

    def test_preco_nao_pedido_e_removido_da_resposta_da_ia(self):
        with patch.object(server,'generate_ai_response',return_value='Tem sim! Fica na loja oficial. 1 por R$ 5 ou 3 por R$ 10.'),patch.object(server,'_com_link_se_couber',side_effect=lambda x,u:x):
            reply=server._compose_reply('tem seda?','Experiência Geral','Neutro',None,False,known=MENU)
        self.assertIn('loja oficial',reply)
        self.assertNotIn('R$',reply)

    def test_local_sem_contexto_pede_esclarecimento(self):
        reply=server._compose_reply('onde é?','Experiência Geral','Neutro',None,False,known=MENU)
        self.assertIn('qual lugar',reply)

    def test_disponibilidade_nunca_perde_o_lugar(self):
        """26/09: "tem seda?" voltou só "Tem sim!" depois do filtro de preço."""
        loja=dict(MENU,answer='LOJA OFICIAL (na pista, perto da feirinha)\nSEDA Papelito R$ 5')
        with patch.object(server,'generate_ai_response',return_value='Tem sim! Na loja oficial a seda custa R$ 5.'),patch.object(server,'_com_link_se_couber',side_effect=lambda x,u:x):
            reply=server._compose_reply('tem seda?','Experiência Geral','Neutro',None,False,known=loja)
        self.assertIn('perto da feirinha',reply)
        self.assertNotIn('R$',reply)

    def test_lugar_documentado_das_fichas(self):
        from tuca_intencao import local_documentado
        self.assertEqual(local_documentado('LOJA OFICIAL (na pista, perto da feirinha)\nSEDA R$ 5'),
                         'Fica na Loja Oficial, na pista, perto da feirinha.')
        self.assertEqual(local_documentado('CERVEJAS E ÁGUA (à venda nos bares)\nBud R$ 15'), 'À venda nos bares.')
        self.assertEqual(local_documentado('À VENDA NOS BARES do festival. RED BULL R$ 18'), 'À venda nos bares do festival.')
        self.assertIsNone(local_documentado('Comida inclusa no ingresso'))

    def test_lugar_ja_dito_nao_repete(self):
        from tuca_intencao import com_local
        loja={'answer':'LOJA OFICIAL (na pista, perto da feirinha)'}
        self.assertEqual(com_local('Tem sim, na loja da feirinha!','tem seda?',loja),'Tem sim, na loja da feirinha!')

    def test_quero_depois_do_convite_manda_a_arte_da_pergunta(self):
        class Store(FakeStore):
            imagens=[]
            def conversation_thread(self,_h,limit=8):
                return {'messages':[
                    {'direction':'in','content':'tem cerveja?'},
                    {'direction':'out','content':f'Tem sim!\n\n{worker.PERGUNTA_ARTE_VALORES}'},
                    {'direction':'in','content':'quero'}]}
            def enqueue_image(self,message,media_url,caption,feedback_id=None,**kw):
                self.imagens.append((media_url,caption))
        worker._ARTES_OFERECIDAS.clear()
        store=Store(count=2)
        store.imagens=[]
        with patch.object(worker,'moderar_texto',return_value=LIBERADO),patch.object(worker,'_atendimento_aprovado',return_value=False),\
                patch.object(worker,'triar_mensagem',return_value={'ficha':MENU}) as triar,patch.object(worker,'ficha_cardapio_geral',return_value=None):
            worker.process_inbox(store,_message(content='quero'))
        # Sem a oferta na memória (worker reiniciou), a pergunta é relida.
        self.assertEqual(store.imagens,[(MENU['image_url'],'')])
        self.assertEqual(triar.call_args.args[0],'tem cerveja?')
        self.assertEqual(store.responses,[])

    def test_quero_manda_a_arte_lembrada_sem_reler(self):
        """A ficha oferecida vale mais que a releitura: seda tem duas fichas (26/09)."""
        loja=dict(MENU,id='loja',image_url='https://example.invalid/loja.png')
        worker._ARTES_OFERECIDAS.clear()
        worker._lembrar_oferta('h1',loja)
        with patch.object(worker,'triar_mensagem') as triar:
            self.assertEqual(worker._ficha_da_oferta(FakeStore(),'h1')['image_url'],loja['image_url'])
        triar.assert_not_called()
        self.assertIsNone(worker._oferta_lembrada('outra pessoa'))
        worker._ARTES_OFERECIDAS.clear()

    def test_agua_suja_ou_quebrada_nao_e_faq(self):
        self.assertIsNone(agua_gratis('o bebedouro está quebrado'))
        self.assertIsNone(agua_gratis('água grátis está suja'))
