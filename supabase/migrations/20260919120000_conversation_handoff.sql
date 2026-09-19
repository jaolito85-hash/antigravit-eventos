-- Assumir e devolver o atendimento de uma conversa.
--
-- Enquanto o modo for 'human', o worker registra a mensagem no dashboard mas
-- nao responde nada: quem fala com o participante e o operador. O telefone
-- nunca entra aqui, a conversa e identificada pelo hash HMAC do remetente.

create table public.conversation_handoff (
    id uuid primary key default gen_random_uuid(),
    event_id uuid not null references public.events(id) on delete cascade,
    sender_hash text not null,
    mode text not null default 'bot',
    operator text,
    taken_at timestamptz,
    released_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint conversation_handoff_unique unique (event_id, sender_hash),
    constraint conversation_handoff_mode_valid check (mode in ('bot', 'human')),
    constraint conversation_handoff_sender_hash_length check (char_length(sender_hash) between 16 and 128),
    constraint conversation_handoff_operator_length check (operator is null or char_length(operator) <= 120)
);

comment on table public.conversation_handoff is
    'Estado de atendimento por conversa: bot automatico ou operador humano.';

-- O worker consulta por (evento, hash) em cada mensagem recebida.
create index conversation_handoff_lookup_idx
    on public.conversation_handoff (event_id, sender_hash);

-- A tela de conversas lista primeiro quem esta em atendimento humano.
create index conversation_handoff_mode_idx
    on public.conversation_handoff (event_id, mode, updated_at desc);

create trigger conversation_handoff_set_updated_at
before update on public.conversation_handoff
for each row execute function private.set_updated_at();

-- Mesma postura das outras tabelas operacionais: nada de acesso anonimo,
-- leitura apenas para membros do evento e escrita exclusiva da service_role.
alter table public.conversation_handoff enable row level security;
alter table public.conversation_handoff force row level security;

create policy conversation_handoff_member_select
on public.conversation_handoff
for select
to authenticated
using ((select private.is_event_member(event_id)));

-- Marca as respostas escritas pelo operador, para a conversa distinguir
-- quem falou e o relatorio nao contar isso como mensagem do bot.
alter table public.outbound_messages
    add column origin text not null default 'bot';

alter table public.outbound_messages
    add constraint outbound_origin_valid check (origin in ('bot', 'operator'));

comment on column public.outbound_messages.origin is
    'bot para resposta automatica, operator para mensagem escrita no painel.';
