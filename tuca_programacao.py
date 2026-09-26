"""Consulta de agora/próximo baseada nos horários cadastrados, sem aritmética da IA."""
import re
from datetime import datetime, timedelta
from tuca_risco import normal


def schedule_reply(text, history, entries, start, now):
    value = normal(text).strip(' ?!.')
    current = bool(re.search(r'\bquem (?:esta|ta) tocando\b', value) or (re.search(r'\bquem toca\b', value) and re.search(r'\bagora\b', value)))
    upcoming = bool(re.fullmatch(r'(?:e )?depois|quem toca depois|qual (?:e )?o proximo(?: show)?', value))
    if not current and not upcoming:
        return None
    if value in ('depois','e depois') and not any(re.search(r'show|toca|programacao|palco',normal(m.get('content'))) for m in history[:-1]):
        return None
    guides = [e for e in entries if e.get('active',True) and e.get('kind')=='lineup']
    if not guides or start is None:
        return None
    rows={}
    conflicts=False
    for guide in guides:
        stage=None
        for line in str(guide.get('answer') or '').splitlines():
            header=re.match(r'^PALCO\s+([^\(]+)',line.strip(),re.I)
            if header:
                stage=header.group(1).strip().title()
                continue
            match=re.match(r'^(\d{1,2}):(\d{2})(?:\s*(?:às|as|-)\s*(\d{1,2}):(\d{2}))?\s*\|\s*(.+)',line.strip())
            if not stage or not match:
                continue
            h,m,eh,em,name=match.groups()
            if int(h)>23 or int(m)>59 or (eh and (int(eh)>23 or int(em)>59)):
                continue
            begin=start.replace(hour=int(h),minute=int(m),second=0,microsecond=0)
            if int(h)<12 and start.hour>=12:begin+=timedelta(days=1)
            end=None
            if eh:
                end=begin.replace(hour=int(eh),minute=int(em))
                if end<=begin:end+=timedelta(days=1)
            key=(stage,begin)
            item={'stage':stage,'start':begin,'end':end,'name':name.strip()}
            if key in rows and (rows[key]['name']!=item['name'] or rows[key]['end']!=item['end']):
                conflicts=True
            rows[key]=item
    if conflicts:
        return 'Encontrei horários divergentes na programação cadastrada. Confirme a programação com a equipe do festival.'
    if not rows:
        return None
    stages=sorted({key[0] for key in rows})
    explicit=[s for s in stages if normal(s) in value]
    lines=[]
    for stage in explicit or stages:
        shows=sorted([r for r in rows.values() if r['stage']==stage],key=lambda r:r['start'])
        for index,show in enumerate(shows):
            if show['end'] is None and index+1<len(shows):show['end']=shows[index+1]['start']
        shows=[r for r in shows if not re.search(r'abertura|fim do evento',normal(r['name']))]
        playing=next((r for r in shows if r['end'] and r['start']<=now<r['end']),None)
        following=next((r for r in shows if r['start']>now),None)
        chosen=following if upcoming or now<start else playing
        if chosen:
            lines.append(f"Palco {stage}: {chosen['name']}, às {chosen['start'].strftime('%H:%M')}.")
        elif current and following:
            lines.append(f"Palco {stage}: próximo, {following['name']}, às {following['start'].strftime('%H:%M')}.")
        else:
            lines.append(f"Palco {stage}: sem {'próximo show' if upcoming else 'show neste horário'} confirmado na grade.")
    label='Próximos shows previstos' if upcoming or now<start else 'Programação prevista para '+now.strftime('%H:%M')
    return label+':\n'+'\n'.join(lines)


def answer(text, history, entries):
    value=normal(text)
    if not re.search(r'\bagora\b|tocando|depois|proximo',value):
        return None
    if not any(e.get('kind')=='lineup' for e in entries):
        return None
    import server
    snapshot=server._LAB_SNAPSHOT.get()
    window=snapshot['window'] if snapshot is not None else server.EVENT_STORE.event_window()
    start=server._para_hora_local(window[0])
    now=server._para_hora_local(snapshot.get('clock')) if snapshot is not None else None
    now=now or datetime.now(server._FUSO_SAO_PAULO)
    return schedule_reply(text,history,entries,start,now)
