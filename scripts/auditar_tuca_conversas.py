"""Ensaio de conversa e moderação real; persistência e WhatsApp simulados."""
import json,logging,sys
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
import server,worker,protecao
from test_worker import FakeStore,_message
config=json.loads((ROOT/'out/auditoria-tuca-config.json').read_text(encoding='utf-8'))
sectors=json.loads((ROOT/'out/auditoria-tuca-setores.json').read_text(encoding='utf-8'))
logging.disable(logging.CRITICAL)
class ConversationStore(FakeStore):
 def __init__(self):super().__init__();self.history=[];self.cards=[]
 def claim_inbox(self,message):
  self.feedback=None;self.responses=[];self.failed=None;self.count=sum(x['direction']=='in' for x in self.history)+1
  self.history.append({'direction':'in','content':message['content']});return True
 def conversation_thread(self,*args,**kwargs):return {'messages':self.history[-8:]}
 def marcar_setor_do_inbox(self,mid,sid):super().marcar_setor_do_inbox(mid,sid);self.setor_recente=self.sector_by_code('PALCO')
 def enqueue_text(self,message,content,feedback_id=None):super().enqueue_text(message,content,feedback_id);self.history.append({'direction':'out','content':content})
 def create_feedback(self,**kwargs):self.cards.append(kwargs);return super().create_feedback(**kwargs)
 def attach_location(self,*args,**kwargs):
  if not self.cards:return None
  self.cards[-1]['coords']=args[1:3];return {'id':42,'urgency':self.cards[-1]['urgency']}
results=[]
with patch.object(server,'_bot_config',return_value=config),patch.object(server,'_fichas_ativas',return_value=config['knowledge']),patch.object(server,'_setores_ativos',return_value=sectors),patch.object(worker,'_setores_ativos',return_value=sectors),patch.object(server,'EVENT_STORE') as es:
 es.event_window.return_value=('2026-09-26T17:30:00+00:00','2026-09-27T07:20:00+00:00')
 store=ConversationStore()
 for i,text in enumerate(['Oi','#SETOR:PALCO','o som está baixo','cadê você?','sos','-23.3312,-51.1925','Obrigado pela ajuda!']):
  worker.process_inbox(store,_message(id=f'conversation-{i}',content=text,message_type='location' if i==5 else 'text'))
  results.append({'message':text,'reply':store.responses,'urgency':(store.feedback or {}).get('urgency'),'sector':(store.feedback or {}).get('region'),'failed':bool(store.failed)})
 moderation=[]
 for text in ['um cara está me assediando','uma pessoa desmaiou','tem uma criança perdida aqui','o bar tá uma merda, sem cerveja','não consigo respirar','bom dia tem briga','show maravilhoso','quero transar com a atendente do bar']:
  moderation.append({'message':text,'result':protecao.moderar_texto(text)})
 report={'conversation':results,'cards':len(store.cards),'location_attached':bool(store.cards[-1].get('coords')),'moderation':moderation}
(ROOT/'out/auditoria-tuca-conversas.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=True))
