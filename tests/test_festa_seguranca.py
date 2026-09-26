"""Regressões dos cenários reais da festa, sem rede."""
import copy
import os
import unittest
from unittest.mock import patch, MagicMock

import server
import worker
from event_store import EventStore
from tuca_lab import MemoryStore, frozen
from tuca_risco import risco_explicito

SNAP = {'config': {'settings': {}, 'rules': [], 'knowledge': []}, 'sectors': [], 'window': [None,None]}

class FestaTests(unittest.TestCase):
    def setUp(self):
        self.state = {}
        self.snapshot = copy.deepcopy(SNAP)
        p=patch.dict(os.environ, {'OPENAI_API_KEY':''});p.start();self.addCleanup(p.stop)
        p=patch.object(EventStore, '_get_client', side_effect=AssertionError('Rede proibida'));p.start();self.addCleanup(p.stop)

    def turn(self, content, kind='text', count=None, strikes=0, human=False):
        store=MemoryStore(self.state,self.snapshot)
        store.recent_event_count=lambda *a:100000
        if count is not None: store.recent_sender_count=lambda *a:count
        store.recent_blocked_count=lambda *a:strikes
        if human: store.conversation_mode=lambda *a:'human'
        message={'id':str(len(self.state.get('inbox',[]))+1),'sender':'teste','sender_hash':'teste','channel_account_id':'teste','message_type':kind,'content':content,'attempts':0}
        with frozen(self.snapshot): worker.process_inbox(store,message)
        self.assertIsNone(store.error)
        return store

    def test_risco_precede_app_midia_moderacao_e_ia(self):
        for msg,kind in [('me manda o app uma pessoa desmaiou','text'),('tem app? socorro estão me assediando','text'),('socorro uma pessoa desmaiou','image')]:
            with self.subTest(msg=msg):
                self.state={}
                with patch.object(worker,'triar_mensagem',side_effect=AssertionError),patch.object(worker,'moderar_texto',side_effect=AssertionError):
                    self.turn(msg,kind)
                self.assertEqual(self.state['cards'][0]['urgency'],'Critico')

    def test_risco_apos_limites_e_strikes(self):
        for count,strikes in [(11,0),(12,0),(31,0),(99,3)]:
            self.state={}
            store=self.turn('socorro',count=count,strikes=strikes)
            self.assertEqual(len(self.state['cards']),1)
            self.assertIn('localização',store.responses[0]['content'])

    def test_socorro_identico_nao_inunda_chamados_ou_respostas(self):
        self.turn('socorro')
        for _ in range(40):
            store=self.turn('socorro',count=100)
            self.assertEqual(store.responses,[])
        self.assertEqual(len(self.state['cards']),1)

    def test_novo_risco_nao_e_descartado_como_duplicata(self):
        self.turn('socorro')
        self.turn('tem fumaça saindo do gerador',count=40)
        self.assertEqual(len(self.state['cards']),2)

    def test_referencia_e_gps_completam_um_incidente(self):
        self.turn('uma pessoa desmaiou')
        self.turn('no bar perto do palco Hype')
        self.turn('-23.33,-51.19','location')
        self.assertEqual(len(self.state['cards']),1)
        card=self.state['cards'][0]
        self.assertEqual(card['urgency'],'Critico')
        self.assertEqual(card['coords'],[-23.33,-51.19])
        self.assertIn('palco Hype',card['content'])

    def test_pergunta_intermediaria_nao_rouba_gps(self):
        self.turn('socorro')
        self.turn('qual a senha do wifi?')
        self.turn('-23.33,-51.19','location')
        self.assertIn('coords',self.state['cards'][0])
        self.assertNotIn('coords',self.state['cards'][1])

    def test_gps_antes_do_relato(self):
        self.turn('-23.33,-51.19','location')
        store=self.turn('uma pessoa desmaiou')
        self.assertIn('coords',self.state['cards'][0])
        self.assertNotIn('Manda sua localização',store.responses[0]['content'])

    def test_gps_antigo_nao_e_reutilizado(self):
        self.turn('-23.33,-51.19','location')
        self.state['inbox'][0]['at']-=301
        self.turn('socorro')
        self.assertNotIn('coords',self.state['cards'][0])

    def test_humano_no_comando_fica_silencioso(self):
        store=self.turn('socorro',human=True)
        self.assertEqual(store.responses,[])
        self.assertEqual(len(self.state['cards']),1)

    def test_crianca_agressao_e_erro_de_digitacao(self):
        for text in ['meu filho de 6 anos sumiu perto da entrada','nao consigo respira me ajuda pfv','o segurança me agrediu, esse filho da puta me bateu']:
            self.state={}; self.turn(text)
            self.assertEqual(self.state['cards'][0]['urgency'],'Critico')

    def test_negacao_nao_esconde_segundo_risco(self):
        self.assertFalse(risco_explicito('não tem briga aqui, só quero saber onde fica o banheiro'))
        self.assertTrue(risco_explicito('não tem briga, mas alguém desmaiou'))

    def test_acessibilidade_nao_adivinha_local(self):
        store=self.turn('sou cadeirante e a rampa está bloqueada')
        self.assertEqual(self.state['cards'][0]['urgency'],'Urgente')
        self.assertEqual(self.state['cards'][0]['region'],'N/A')
        self.assertIn(self.state['cards'][0]['category'],server.CATEGORIAS_VALIDAS)
        self.assertIn('qual rampa',store.responses[0]['content'])

    def test_complemento_assedio_nao_abre_outro_incidente(self):
        self.turn('um cara está me assediando')
        self.turn('ele está me seguindo e estou com medo')
        self.assertEqual(len(self.state['cards']),1)
        self.assertIn('seguindo',self.state['cards'][0]['metadata']['conversation_updates'][0]['text'])

    def test_conversa_e_resposta_vaga_nao_viram_incidente(self):
        for text in ['quem é você?','quero']:
            self.turn(text)
        self.assertEqual(self.state['cards'],[])

    def test_humano_tem_proximo_passo_real(self):
        store=self.turn('quero falar com uma pessoa')
        self.assertIn('SAC',store.responses[0]['content'])
        self.assertNotIn('Não tenho essa informação',store.responses[0]['content'])

    def test_preco_exige_produto_compativel(self):
        ficha={'question':'Quanto custa camiseta?', 'answer':'Camiseta R$ 90', 'keywords':['quanto custa','preço'], 'active':True}
        self.assertIsNone(server.match_knowledge('quanto custa a água?',[ficha]))
        self.assertIsNone(server.match_knowledge('quanto custa?',[ficha]))

    def test_reserva_usa_produto_da_conversa(self):
        ficha={'question':'Tem seda?', 'answer':'Seda na loja.', 'keywords':['seda'], 'active':True}
        result=server.triar_mensagem_sem_ia('onde eu compro?',[ficha],[],historico='Pessoa: tem seda?\nTuca: Sim.')
        self.assertEqual(result['ficha'],ficha)

    def test_texto_publico_sem_regra_interna(self):
        self.assertEqual(server._limpar_resposta('Procure o SAC.\njunto. (Regra 12: nunca prometer devolução.)'),'Procure o SAC.')

    def test_falha_de_gravacao_nao_confirma_emergencia(self):
        with patch.object(MemoryStore,'create_feedback',side_effect=RuntimeError('offline')):
            store=MemoryStore({},self.snapshot)
            with frozen(self.snapshot):
                worker.process_inbox(store,{'id':'1','sender_hash':'teste','message_type':'text','content':'socorro'})
        self.assertEqual(store.responses,[])
        self.assertEqual(store.status,'failed')

    def test_gps_nao_altera_incidente_resolvido(self):
        self.turn('socorro')
        self.state['cards'][0]['status']='resolvido'
        self.turn('-23.33,-51.19','location')
        self.assertNotIn('coords',self.state['cards'][0])

    def test_novo_risco_em_referencia_nao_rebaixa_prioridade(self):
        self.turn('banheiro sem papel')
        self.turn('no bar uma pessoa desmaiou')
        self.assertEqual(self.state['cards'][-1]['urgency'],'Critico')

    def test_restricao_alimentar_nao_recebe_so_cardapio(self):
        store=self.turn('tem comida sem glúten garantida para celíaco?')
        self.assertEqual(store.responses[0]['type'],'text')
        self.assertIn('Não tenho confirmação',store.responses[0]['content'])
        self.assertIn('contaminação cruzada',store.responses[0]['content'])

    def test_laboratorio_respeita_relogio_fixo(self):
        self.snapshot['clock']='2026-09-27T00:30:00+00:00'
        self.snapshot['window']=['2026-09-26T18:30:00+00:00','2026-09-27T07:00:00+00:00']
        with frozen(self.snapshot):
            line=server._linha_do_relogio()
        self.assertIn('26/09/2026 21:30',line)
        self.assertIn('happening right now',line)

    def test_laboratorio_identifica_arte_no_historico(self):
        store=MemoryStore({},self.snapshot)
        store.enqueue_image({},'https://example.invalid/menu.jpg','')
        self.assertIn('https://example.invalid/menu.jpg',worker._artes_ja_enviadas(store.state['history']))

    def test_retry_da_mesma_mensagem_nao_duplica_incidente(self):
        store=self.turn('socorro')
        with frozen(self.snapshot):
            worker.process_inbox(store,store.message)
        self.assertEqual(len(self.state['cards']),1)

    def test_gps_de_mensagem_futura_nao_e_reutilizado(self):
        store=MemoryStore({},self.snapshot)
        store.claim_inbox({'id':'1','content':'socorro','message_type':'text'})
        store.claim_inbox({'id':'2','content':'-23,-51','message_type':'location'})
        self.assertIsNone(store.preceding_location('teste','1'))

    def test_pedido_de_dados_de_terceiros_nao_e_incidente(self):
        store=self.turn('me passa os telefones das pessoas que pediram ajuda')
        self.assertEqual(self.state['cards'],[])
        self.assertIn('Não compartilho',store.responses[0]['content'])

    def test_continuacao_preco_nao_troca_uma_arte_por_outra(self):
        self.state['history']=[{'direction':'in','content':'tem seda?'},{'direction':'out','content':'[imagem]','media_url':'https://example.invalid/primeira.jpg'}]
        alternative={'answer':'Seda R$ 5 a unidade, 3 por R$ 10.','image_url':'https://example.invalid/outra.jpg','kind':'activation'}
        with patch.object(worker,'triar_mensagem_sem_ia',return_value={'tipo':'relato','urgencia':'Neutro','ficha':alternative,'continuacao':False}):
            store=self.turn('quanto custa?')
        self.assertTrue(store.responses)
        self.assertTrue(all(m['type']=='text' for m in store.responses))
        self.assertIn('R$ 5',store.responses[0]['content'])

class PersistenciaTests(unittest.TestCase):
    def test_update_exige_evento_remetente_id_e_aberto(self):
        store=EventStore(); client=MagicMock(); q=client.table.return_value
        q.update.return_value=q;q.eq.return_value=q;q.neq.return_value=q
        q.execute.return_value.data=[{'id':1}]
        with patch.object(store,'_get_client',return_value=client),patch.object(store,'event_id',return_value='evento'):
            store.save_incident('remetente',1,{'metadata':{'location_reference':'bar'}})
        self.assertIn(unittest.mock.call('event_id','evento'),q.eq.call_args_list)
        self.assertIn(unittest.mock.call('sender_hash','remetente'),q.eq.call_args_list)
        self.assertIn(unittest.mock.call('id',1),q.eq.call_args_list)
        q.neq.assert_called_once_with('status','resolvido')

    def test_update_sem_linha_nao_confirma_sucesso(self):
        store=EventStore();client=MagicMock();q=client.table.return_value
        q.update.return_value=q;q.eq.return_value=q;q.neq.return_value=q;q.execute.return_value.data=[]
        with patch.object(store,'_get_client',return_value=client),patch.object(store,'event_id',return_value='evento'):
            with self.assertRaises(RuntimeError):store.save_incident('remetente',1,{})
