"""Critérios independentes de aceite sobre os resultados reais da bateria."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
checks=[]

def check(mode,name,condition):
    checks.append({'mode':mode,'check':name,'passed':bool(condition)})

for mode in ('live','fallback'):
    payload=json.loads((ROOT/f'out/auditoria-festa-25-{mode}-final.json').read_text(encoding='utf-8'))
    rows=payload['rows']
    if mode=='live':
        # Mantém a origem de cada rodada e usa o último ensaio de cada cenário.
        for file in ('auditoria-festa-26-categorias.json','auditoria-festa-26-loja.json'):
            followup=json.loads((ROOT/'out'/file).read_text(encoding='utf-8'))
            check(mode,file+': API real sem falhas',bool(followup['api']) and all(a['ok'] for a in followup['api']))
            updated={r['scenario'] for r in followup['rows']}
            rows=[r for r in rows if r['scenario'] not in updated]+followup['rows']
    def scenario(name):return [r for r in rows if r['scenario']==name]
    def reply(row):
        return '\n'.join(m if isinstance(m,str) else m.get('content','') for m in row.get('result',{}).get('messages',[]))
    def last(name):return scenario(name)[-1]
    check(mode,'Todas as mensagens processadas sem exceção',all(not(r.get('error') or r.get('result',{}).get('error')) for r in rows))
    check(mode,'Sem travessão ou instrução editorial nas respostas',all(not any(w in reply(r) for w in ['\u2014','Regra 12:']) for r in rows))
    for name in ('misto_app','misto_app2','crianca','respiracao','seguranca','incendio','qr_invalido'):
        check(mode,name+': crítico registrado',bool(last(name)['cards']) and last(name)['cards'][-1]['urgency']=='Critico')
    check(mode,'Socorro na legenda vira crítico',scenario('midia')[0]['cards'][0]['urgency']=='Critico')
    check(mode,'Emergência, referência e GPS no mesmo incidente',len(last('emergencia')['cards'])==1 and bool(last('emergencia')['cards'][0].get('coords')) and 'palco Hype' in last('emergencia')['cards'][0]['content'])
    check(mode,'Assédio conserva um incidente crítico',len(last('assedio')['cards'])==1 and last('assedio')['cards'][0]['urgency']=='Critico')
    check(mode,'GPS enviado antes é reaproveitado',bool(last('gps_primeiro')['cards'][0].get('coords')))
    check(mode,'Rampa bloqueada é urgente sem local inventado',last('acessibilidade')['cards'][0]['urgency']=='Urgente' and last('acessibilidade')['cards'][0]['region']=='N/A')
    check(mode,'Negação não gera alarme',not last('negacao')['cards'])
    check(mode,'Pergunta sobre Tuca não vira chamado',not last('boas_vindas')['cards'])
    check(mode,'Restrição alimentar recebe explicação, não só imagem','contaminação cruzada' in reply(last('alimentacao')))
    check(mode,'Atendimento humano tem próximo passo','SAC' in reply(last('desconhecido')))
    check(mode,'Água não recebe preço de camiseta','camiseta' not in reply(scenario('bebidas')[0]).lower())
    check(mode,'Preço da seda é respondido em texto após a arte',all(m.get('type')=='text' for m in last('loja')['result']['messages']) and '5' in reply(last('loja')) and '10' in reply(last('loja')))
    check(mode,'Programação atual usa BK e não artista já encerrado','BK' in reply(scenario('programacao')[1]) and 'Kayblack' not in reply(scenario('programacao')[1]))
    check(mode,'Próximo show nunca volta para Luísa às 20h25','Livinho' in reply(scenario('programacao')[2]) and 'Luísa' not in reply(scenario('programacao')[2]))
    check(mode,'Dados pessoais são recusados','Não compartilho' in reply(last('injecao')))
    if mode=='live':
        check(mode,'API real teve respostas bem-sucedidas',bool(payload['api']) and all(a['ok'] for a in payload['api']))
        check(mode,'Moderação real foi usada',bool(payload['moderation']) and all(m['origin']=='ia' for m in payload['moderation']))
    else:
        check(mode,'Emergências persistem após limites e strikes',all(r['cards'] and r['cards'][0]['urgency']=='Critico' and r['result']['messages'] for r in scenario('limites')))
        check(mode,'Reserva não chama API',not payload['api'])

out={'checks':checks,'passed':sum(c['passed'] for c in checks),'total':len(checks)}
(ROOT/'out/auditoria-festa-25-aceite.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(f"Aceite: {out['passed']}/{out['total']}")
for c in checks:
    if not c['passed']:print(c)
raise SystemExit(0 if out['passed']==out['total'] else 1)
