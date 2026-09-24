"""Regressões da auditoria de 24/09. Não fazem chamadas de rede."""
import logging
import os
import unittest
from unittest import mock
import server
import worker
from test_worker import FakeStore, _message, LIBERADO
from test_localizacao import FakeStore as LocationStore, _localizacao

class AuditoriaTests(unittest.TestCase):
    def setUp(self):
        self.stack=[]
        for patcher in [mock.patch.dict(os.environ, {'OPENAI_API_KEY':''}),
                        mock.patch.object(server,'_fichas_ativas',return_value=[]),
                        mock.patch.object(server,'_setores_ativos',return_value=[]),
                        mock.patch.object(worker,'_setores_ativos',return_value=[]),
                        mock.patch.object(server,'_bot_config',return_value={}),
                        mock.patch.object(worker,'moderar_texto',return_value=LIBERADO)]:
            patcher.start(); self.addCleanup(patcher.stop)

    def test_sem_chave_preserva_resposta_oficial(self):
        result=server._compose_reply('quantos palcos?', 'Evento', 'Neutro', None,False,known={'answer':'Temos três palcos.'})
        self.assertEqual('Temos três palcos.',result)

    def test_sem_chave_emergencia_tem_protocolo(self):
        result=server._compose_reply('socorro','Saúde','Critico',None,False,known=None)
        self.assertIn('prioridade máxima',result)
        self.assertIn('localização',result)

    def test_emergencia_nao_e_substituida_por_ficha(self):
        result=server._compose_reply('desmaiou','Saúde','Critico',None,False,known={'answer':'Aproveite a festa!'})
        self.assertNotIn('Aproveite',result)
        self.assertIn('localização',result)

    def test_critico_com_setor_nao_repete_pergunta(self):
        result=server._compose_reply('desmaiou','Saúde','Critico',{'name':'Palco Tropical'},False,known=None)
        self.assertIn('Palco Tropical',result)
        self.assertNotIn('Manda sua localização',result)

    def test_desconhecido_confirma_encaminhamento_sem_prometer_retorno(self):
        store=FakeStore(); worker.process_inbox(store,_message(content='Qual a senha do wifi VIP?'))
        self.assertIsNotNone(store.feedback)
        self.assertIn('Não tenho essa informação confirmada',store.response[1])
        self.assertIn('já foi enviado',store.response[1])
        self.assertNotIn('responde por aqui',store.response[1])

    def test_conversa_nao_promete_chamado_inexistente(self):
        with mock.patch.object(worker,'triar_mensagem',return_value={'tipo':'conversa','urgencia':'Neutro'}):
            store=FakeStore(); worker.process_inbox(store,_message(content='cadê você?'))
        self.assertIsNone(store.feedback)
        self.assertNotIn('já foi enviado',store.response[1])

    def test_localizacao_apos_limite_ainda_completa_chamado(self):
        for count in [11,12,30,31,99]:
            with self.subTest(count=count):
                store=LocationStore(alvo={'id':42,'urgency':'Critico'})
                store.recent_sender_count=lambda *a: count
                worker.process_inbox(store,_localizacao())
                self.assertIsNotNone(store.anexado)
                self.assertEqual([],store.responses)

    def test_localizacao_apos_strikes_ainda_completa_chamado(self):
        store=LocationStore(alvo={'id':42,'urgency':'Critico'})
        store.recent_blocked_count=lambda *a: 3
        worker.process_inbox(store,_localizacao())
        self.assertIsNotNone(store.anexado)
        self.assertEqual([],store.responses)

    def test_localizacao_nao_afirma_deslocamento(self):
        self.assertNotRegex(worker.AVISO_LOCALIZACAO_RECEBIDA,r'estão indo|a caminho')

    def test_reserva_reconhece_pedidos_criticos(self):
        for text in ['sos','SOS!','um cara me assediando','assédio no bar','criança perdida','crianca desaparecida','pisoteio na entrada']:
            with self.subTest(text=text):
                self.assertEqual('Critico',server.triar_mensagem_sem_ia(text,[],[])['urgencia'])

    def test_ficha_vazia_nao_produz_resposta_vazia(self):
        result=server._compose_reply('dúvida','Evento','Neutro',None,False,known={'answer':''})
        self.assertTrue(result.strip())

    def test_fallback_nao_copia_promessas_da_base(self):
        for text in ['vamos enviar mais atendentes','a equipe já está indo repor','o pessoal está a caminho']:
            result=server._compose_reply('falta gelo','Bar','Urgente',None,False,known={'answer':text})
            self.assertNotEqual(text,result)
            self.assertIn('equipe',result)

    def test_resposta_oficial_sem_travessao(self):
        result=server._compose_reply('horário','Evento','Neutro',None,False,known={'answer':'Abre sábado — confira a programação.'})
        self.assertNotIn('—',result)

    def test_falha_persistencia_nao_confirma_chamado(self):
        store=FakeStore();store.create_feedback=mock.Mock(side_effect=RuntimeError('offline'))
        worker.process_inbox(store,_message(content='sem gelo no bar'))
        self.assertIsNotNone(store.failed)
        self.assertEqual([],store.responses)

    def test_setor_herdado_chega_ao_gerador(self):
        store=FakeStore();store.setor_recente={'id':'s','name':'Bar Tropical'}
        with mock.patch.object(worker,'_compose_reply',return_value='Recebido') as reply:
            worker.process_inbox(store,_message(content='sem gelo no bar'))
        self.assertEqual('Bar Tropical',reply.call_args.args[3]['name'])

    def test_saida_drena_antes_da_proxima_mensagem(self):
        events=[];store=mock.Mock();store.healthcheck.return_value=True
        store.pending_inbox.return_value=[{'id':'a'},{'id':'b'}]
        store.pending_outbox.return_value=[{'id':'r'}]
        def inbox(s,m):
            events.append(m['id'])
            if m['id']=='b':worker._running=False
        def outbox(*a):events.append('enviado')
        with mock.patch.object(worker,'EventStore',return_value=store),mock.patch.object(worker,'MetaWhatsAppClient'),mock.patch.object(worker,'process_inbox',side_effect=inbox),mock.patch.object(worker,'process_outbox',side_effect=outbox),mock.patch.object(worker,'_running',True):
            worker.run()
        self.assertLess(events.index('enviado'),events.index('b'))

    def test_carga_local_2000_mensagens(self):
        cases=[('sos','Critico'),('falta gelo','Urgente'),('show incrível','Positivo'),('qual a senha do wifi?','Neutro')]
        old=logging.root.manager.disable;logging.disable(logging.CRITICAL)
        try:
            for i in range(2000):
                text,urgency=cases[i%len(cases)];store=FakeStore(per_minute=100000)
                worker.process_inbox(store,_message(id=f'load-{i}',content=text))
                self.assertIsNone(store.failed)
                self.assertEqual(urgency,store.feedback['urgency'])
                self.assertEqual('processed',store.finished)
                self.assertEqual(1,len(store.responses))
        finally:logging.disable(old)

    def test_recuperacao_agua_no_corpo_da_ficha(self):
        ficha={'question':'Está quente', 'answer':'Água potável gratuita na pista.', 'active':True}
        self.assertEqual(ficha,server.recuperar_ficha_por_resposta('Tem água grátis?',[ficha]))
        self.assertIsNone(server.recuperar_ficha_por_resposta('Tem água grátis?',[dict(ficha,active=False)]))
        self.assertIsNone(server.recuperar_ficha_por_resposta('Tem água grátis?',[ficha,dict(ficha)]))
        self.assertIsNone(server.recuperar_ficha_por_resposta('Tem estacionamento?',[ficha]))

    def test_falha_ia_usa_base_e_nao_agradecimento_generico(self):
        with mock.patch.object(server,'generate_ai_response',side_effect=TimeoutError):
            result=server._compose_reply('pergunta','Evento','Neutro',None,False,known={'answer':'Resposta oficial.'})
        self.assertEqual('Resposta oficial.',result)

    def test_saida_ia_sem_confirmacao_recebe_confirmacao(self):
        with mock.patch.object(server,'generate_ai_response',return_value='Essa eu não sei responder.'):
            result=server._compose_reply('wifi','Evento','Neutro',None,False,known=None)
        self.assertIn('chamado já foi enviado',result)

    def test_saida_ia_promessa_e_rejeitada(self):
        client=mock.Mock()
        client.chat.completions.create.return_value.choices=[mock.Mock(message=mock.Mock(content='Vão enviar mais atendentes para o bar.'))]
        with mock.patch.dict(os.environ,{'OPENAI_API_KEY':'teste'}),mock.patch.object(server,'_openai_chat_client',return_value=client):
            self.assertIsNone(server.generate_ai_response('fila enorme','Bar','Urgente'))

    def test_ia_json_invalido_cai_em_reserva(self):
        client=mock.Mock()
        client.chat.completions.create.return_value.choices=[mock.Mock(message=mock.Mock(content='não é JSON'))]
        with mock.patch.object(server,'_openai_chat_client',return_value=client):
            self.assertEqual('Critico',server.triar_mensagem('socorro')['urgencia'])

    def test_pergunta_sobre_show_nao_vira_elogio_sem_ia(self):
        for text in ['Que horas começa o show?', 'Quem toca no show?', 'Qual o palco do show?', 'Quando começa o show?']:
            self.assertEqual('Neutro',server.classificar_sentimento(text))
        self.assertEqual('Positivo',server.classificar_sentimento('o show está incrível'))
        self.assertEqual('Critico',server.classificar_sentimento('tem gente sendo esmagada'))
        self.assertEqual('Critico',server.classificar_sentimento('tem fumaça no gerador'))

    def test_emergencia_nao_depende_de_resposta_da_ia(self):
        with mock.patch.object(server,'generate_ai_response',side_effect=AssertionError('não chamar IA')) as generate:
            result=server._compose_reply('socorro','Saúde','Critico',None,False,known=None)
        generate.assert_not_called()
        self.assertIn('prioridade máxima',result)
        self.assertIn('localização',result)
        self.assertNotIn('Fique no local',result)
