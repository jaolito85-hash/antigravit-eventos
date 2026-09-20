-- Alertas do agente de operacao no Telegram.
--
-- O agente varre o sistema de meia em meia hora. Cada problema que ele
-- encontra vira uma linha aqui, para nao repetir o mesmo aviso a cada
-- varredura e para guardar quem confirmou a correcao e o que ela fez.
-- Nenhum dado do participante entra nesta tabela: so o diagnostico.

create table public.agent_alerts (
    id uuid primary key default gen_random_uuid(),
    event_id uuid not null references public.events(id) on delete cascade,
    chave text not null,
    gravidade text not null default 'atencao',
    titulo text not null,
    detalhe text,
    acao text,
    status text not null default 'aberto',
    telegram_chat_id text,
    telegram_message_id text,
    resultado text,
    decidido_por text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    resolved_at timestamptz,
    constraint agent_alerts_gravidade_valid check (gravidade in ('critico', 'atencao')),
    constraint agent_alerts_status_valid check (status in ('aberto', 'corrigido', 'ignorado', 'resolvido')),
    constraint agent_alerts_chave_length check (char_length(chave) between 1 and 120),
    constraint agent_alerts_titulo_length check (char_length(titulo) between 1 and 300),
    constraint agent_alerts_detalhe_length check (detalhe is null or char_length(detalhe) <= 4000),
    constraint agent_alerts_resultado_length check (resultado is null or char_length(resultado) <= 2000),
    constraint agent_alerts_decidido_por_length check (decidido_por is null or char_length(decidido_por) <= 120)
);

comment on table public.agent_alerts is
    'Problemas encontrados pelo agente de operacao e o que a equipe decidiu no Telegram.';

-- Um problema aberto por chave: e assim que o agente sabe que ja avisou.
create unique index agent_alerts_aberto_unique
    on public.agent_alerts (event_id, chave)
    where status = 'aberto';

create index agent_alerts_recentes_idx
    on public.agent_alerts (event_id, created_at desc);

create trigger agent_alerts_set_updated_at
before update on public.agent_alerts
for each row execute function private.set_updated_at();

-- Mesma postura das outras tabelas operacionais: nada de acesso anonimo,
-- leitura apenas para membros do evento e escrita exclusiva da service_role.
alter table public.agent_alerts enable row level security;
alter table public.agent_alerts force row level security;

create policy agent_alerts_member_select
on public.agent_alerts
for select
to authenticated
using ((select private.is_event_member(event_id)));
