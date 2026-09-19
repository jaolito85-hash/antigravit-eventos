-- Estrutura para a base de contatos que aceitarem receber novidades.
--
-- Só a estrutura: o Tuca não pede aceite nenhum durante a conversa. A forma
-- de coletar será decidida depois, e esta tabela é onde o aceite vai cair
-- quando isso acontecer.
--
-- Por que tabela separada e não uma coluna em feedbacks: o resto do sistema
-- trabalha com o hash do remetente, e o painel nunca mostra telefone. Aqui o
-- contato fica em claro de propósito, porque é o único lugar que existe para
-- falar com a pessoa depois do evento, e isolar facilita apagar tudo se ela
-- pedir.

create table public.marketing_consent (
    id uuid primary key default gen_random_uuid(),
    event_id uuid not null references public.events(id) on delete cascade,
    sender_hash text not null,
    contact text not null,
    channel text not null default 'whatsapp',
    -- O texto exato que a pessoa aceitou e o que ela respondeu. É isso que
    -- prova o consentimento depois; guardar só a data não prova nada.
    consent_text text not null,
    consent_reply text,
    consented_at timestamptz not null default now(),
    revoked_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint marketing_consent_sender_hash_length check (char_length(sender_hash) between 16 and 128),
    constraint marketing_consent_contact_length check (char_length(contact) between 8 and 20),
    constraint marketing_consent_channel_valid check (channel in ('whatsapp', 'painel', 'importacao')),
    constraint marketing_consent_text_length check (char_length(consent_text) between 10 and 1000),
    constraint marketing_consent_revogacao_posterior check (revoked_at is null or revoked_at >= consented_at),
    constraint marketing_consent_unico_por_pessoa unique (event_id, sender_hash)
);

comment on table public.marketing_consent is
    'Contatos que aceitaram receber novidades, com o texto do aceite e a data. Uma linha por pessoa por evento.';
comment on column public.marketing_consent.contact is
    'Telefone em claro, exclusivo desta tabela. O restante do sistema usa sender_hash.';
comment on column public.marketing_consent.revoked_at is
    'Preenchido quando a pessoa pede para sair. A linha fica, para provar que o pedido foi respeitado.';

-- A consulta real é "quem aceitou e não revogou neste evento".
create index marketing_consent_ativos_idx
    on public.marketing_consent (event_id, consented_at desc)
    where revoked_at is null;

create trigger marketing_consent_set_updated_at
before update on public.marketing_consent
for each row execute function private.set_updated_at();

alter table public.marketing_consent enable row level security;
alter table public.marketing_consent force row level security;

create policy marketing_consent_member_select
on public.marketing_consent
for select
to authenticated
using ((select private.is_event_member(event_id)));
