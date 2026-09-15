-- Estrutura segura e multi-evento para ingestão e operação via WhatsApp.
-- O navegador nunca acessa filas nem dados pessoais diretamente; o backend usa
-- exclusivamente a service_role e operadores autenticados enxergam só seus eventos.

create schema if not exists private;
revoke all on schema private from public, anon, authenticated;

create table public.events (
    id uuid primary key default gen_random_uuid(),
    slug text not null unique,
    name text not null,
    venue text,
    timezone text not null default 'America/Sao_Paulo',
    starts_at timestamptz,
    ends_at timestamptz,
    status text not null default 'draft',
    retention_until timestamptz,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint events_slug_format check (slug ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'),
    constraint events_name_length check (char_length(name) between 1 and 160),
    constraint events_status_valid check (status in ('draft', 'active', 'completed', 'archived')),
    constraint events_date_order check (ends_at is null or starts_at is null or ends_at > starts_at),
    constraint events_metadata_object check (jsonb_typeof(metadata) = 'object')
);

comment on table public.events is 'Eventos monitorados, incluindo janela operacional e retenção LGPD.';
comment on column public.events.retention_until is 'Data para anonimização ou exclusão dos dados pessoais do evento.';

insert into public.events (
    slug,
    name,
    venue,
    starts_at,
    ends_at,
    retention_until,
    metadata
)
values (
    'tropicadelia-2026',
    'Tropicadelia 2026',
    'Parque de Exposições Governador Ney Braga, Londrina-PR',
    '2026-09-26 15:30:00-03'::timestamptz,
    '2026-09-27 04:00:00-03'::timestamptz,
    '2026-10-27 04:00:00-03'::timestamptz,
    '{"pilot": true}'::jsonb
)
on conflict (slug) do update
set name = excluded.name,
    venue = excluded.venue,
    starts_at = excluded.starts_at,
    ends_at = excluded.ends_at,
    retention_until = excluded.retention_until,
    metadata = public.events.metadata || excluded.metadata,
    updated_at = now();

create table public.event_members (
    event_id uuid not null references public.events(id) on delete cascade,
    user_id uuid not null references auth.users(id) on delete cascade,
    role text not null default 'viewer',
    created_at timestamptz not null default now(),
    primary key (event_id, user_id),
    constraint event_members_role_valid check (role in ('admin', 'operator', 'viewer'))
);

comment on table public.event_members is 'Associação de usuários Supabase Auth aos eventos que podem acessar.';

create table public.event_sectors (
    id uuid primary key default gen_random_uuid(),
    event_id uuid not null references public.events(id) on delete cascade,
    code text not null,
    name text not null,
    active boolean not null default true,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (event_id, code),
    constraint event_sectors_code_format check (code ~ '^[A-Z0-9][A-Z0-9_-]{0,49}$'),
    constraint event_sectors_name_length check (char_length(name) between 1 and 120),
    constraint event_sectors_metadata_object check (jsonb_typeof(metadata) = 'object')
);

comment on table public.event_sectors is 'Setores codificados nos QR codes para localização determinística.';

create table public.message_inbox (
    id uuid primary key default gen_random_uuid(),
    event_id uuid not null references public.events(id) on delete restrict,
    sector_id uuid references public.event_sectors(id) on delete set null,
    provider text not null,
    channel_account_id text not null,
    external_message_id text not null,
    sender text not null,
    sender_hash text,
    sender_name text,
    message_type text not null,
    content text,
    media_id text,
    occurred_at timestamptz,
    processing_status text not null default 'pending',
    attempts smallint not null default 0,
    next_attempt_at timestamptz not null default now(),
    last_error text,
    processed_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (provider, channel_account_id, external_message_id),
    constraint message_inbox_provider_valid check (provider in ('meta', 'evolution', 'manual')),
    constraint message_inbox_type_valid check (message_type in ('text', 'audio', 'image', 'video', 'document', 'location', 'interactive', 'unknown')),
    constraint message_inbox_status_valid check (processing_status in ('pending', 'processing', 'processed', 'failed', 'ignored')),
    constraint message_inbox_attempts_valid check (attempts between 0 and 20),
    constraint message_inbox_sender_length check (char_length(sender) between 1 and 128),
    constraint message_inbox_content_length check (content is null or char_length(content) <= 5000),
    constraint message_inbox_error_length check (last_error is null or char_length(last_error) <= 2000)
);

comment on table public.message_inbox is 'Caixa durável e idempotente de mensagens recebidas dos provedores.';
comment on column public.message_inbox.sender is 'Identificador pessoal restrito ao backend; nunca expor em logs.';

alter table public.config
    add column event_id uuid references public.events(id) on delete cascade;

update public.config
set event_id = (
    select id
    from public.events
    where slug = 'tropicadelia-2026'
);

alter table public.config
    alter column event_id set not null,
    add constraint config_type_valid check (type in ('category', 'region')),
    add constraint config_name_length check (char_length(name) between 1 and 120),
    add constraint config_count_nonnegative check (count is null or count >= 0),
    add constraint config_event_type_name_unique unique (event_id, type, name);

insert into public.config (event_id, type, name, color)
select e.id, values_to_insert.type, values_to_insert.name, values_to_insert.color
from public.events e
cross join (
    values
        ('category', 'Alimentação & Bebidas', '#f59e0b'),
        ('category', 'Estrutura & Espaço', '#ec4899'),
        ('category', 'Experiência Geral', '#10b981'),
        ('category', 'Programação & Atrações', '#a855f7'),
        ('category', 'Credenciamento & Ingressos', '#3b82f6'),
        ('category', 'Segurança & Organização', '#ef4444')
) as values_to_insert(type, name, color)
where e.slug = 'tropicadelia-2026'
on conflict (event_id, type, name) do update
set color = excluded.color;

alter table public.feedbacks
    add column event_id uuid references public.events(id) on delete restrict,
    add column sector_id uuid references public.event_sectors(id) on delete set null,
    add column inbox_message_id uuid references public.message_inbox(id) on delete set null,
    add column sender_hash text,
    add column source text not null default 'meta',
    add column metadata jsonb not null default '{}'::jsonb;

update public.feedbacks
set event_id = (
    select id
    from public.events
    where slug = 'tropicadelia-2026'
);

alter table public.feedbacks
    alter column event_id set not null,
    add constraint feedbacks_inbox_message_unique unique (inbox_message_id),
    add constraint feedbacks_linked_from_fk foreign key (linked_from) references public.feedbacks(id) on delete set null,
    add constraint feedbacks_message_length check (char_length(message) between 1 and 5000),
    add constraint feedbacks_sender_length check (sender is null or char_length(sender) <= 128),
    add constraint feedbacks_name_length check (name is null or char_length(name) <= 200),
    add constraint feedbacks_status_valid check (status in ('aberto', 'em_andamento', 'resolvido')),
    add constraint feedbacks_urgency_valid check (urgency in ('Neutro', 'Positivo', 'Urgente', 'Critico', 'Crítico')),
    add constraint feedbacks_sentiment_valid check (sentiment in ('Neutro', 'Positivo', 'Negativo')),
    add constraint feedbacks_source_valid check (source in ('meta', 'evolution', 'manual')),
    add constraint feedbacks_resolution_consistent check (
        (status = 'resolvido' and resolved_at is not null)
        or (status <> 'resolvido' and resolved_at is null)
    ),
    add constraint feedbacks_metadata_object check (jsonb_typeof(metadata) = 'object');

create table public.outbound_messages (
    id uuid primary key default gen_random_uuid(),
    event_id uuid not null references public.events(id) on delete restrict,
    feedback_id integer references public.feedbacks(id) on delete set null,
    provider text not null default 'meta',
    channel_account_id text not null,
    recipient text not null,
    message_type text not null default 'text',
    content text not null,
    idempotency_key text not null unique,
    provider_message_id text,
    delivery_status text not null default 'queued',
    attempts smallint not null default 0,
    next_attempt_at timestamptz not null default now(),
    last_error text,
    sent_at timestamptz,
    delivered_at timestamptz,
    read_at timestamptz,
    failed_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint outbound_provider_valid check (provider in ('meta', 'evolution')),
    constraint outbound_type_valid check (message_type in ('text', 'template', 'audio', 'image', 'interactive')),
    constraint outbound_status_valid check (delivery_status in ('queued', 'sending', 'sent', 'delivered', 'read', 'failed', 'cancelled')),
    constraint outbound_attempts_valid check (attempts between 0 and 20),
    constraint outbound_recipient_length check (char_length(recipient) between 1 and 128),
    constraint outbound_content_length check (char_length(content) between 1 and 4096),
    constraint outbound_error_length check (last_error is null or char_length(last_error) <= 2000)
);

comment on table public.outbound_messages is 'Fila durável de respostas e seus estados de entrega no WhatsApp.';

create unique index outbound_provider_message_unique
    on public.outbound_messages (provider, provider_message_id)
    where provider_message_id is not null;

create table public.feedback_status_history (
    id bigint generated always as identity primary key,
    feedback_id integer not null references public.feedbacks(id) on delete cascade,
    event_id uuid not null references public.events(id) on delete cascade,
    old_status text,
    new_status text not null,
    changed_by uuid references auth.users(id) on delete set null,
    changed_at timestamptz not null default now(),
    constraint feedback_history_old_status_valid check (old_status is null or old_status in ('aberto', 'em_andamento', 'resolvido')),
    constraint feedback_history_new_status_valid check (new_status in ('aberto', 'em_andamento', 'resolvido'))
);

comment on table public.feedback_status_history is 'Trilha de auditoria imutável das mudanças de status.';

create or replace function private.set_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

create or replace function private.is_event_member(target_event_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select exists (
        select 1
        from public.event_members as membership
        where membership.event_id = target_event_id
          and membership.user_id = (select auth.uid())
    );
$$;

create or replace function private.can_operate_event(target_event_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select exists (
        select 1
        from public.event_members as membership
        where membership.event_id = target_event_id
          and membership.user_id = (select auth.uid())
          and membership.role in ('admin', 'operator')
    );
$$;

create or replace function private.record_feedback_status_change()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    if old.status is distinct from new.status then
        insert into public.feedback_status_history (
            feedback_id,
            event_id,
            old_status,
            new_status,
            changed_by
        )
        values (
            new.id,
            new.event_id,
            old.status,
            new.status,
            (select auth.uid())
        );
    end if;
    return new;
end;
$$;

revoke all on function private.set_updated_at() from public, anon, authenticated;
revoke all on function private.is_event_member(uuid) from public, anon;
revoke all on function private.can_operate_event(uuid) from public, anon;
revoke all on function private.record_feedback_status_change() from public, anon, authenticated;
grant usage on schema private to authenticated, service_role;
grant execute on function private.is_event_member(uuid) to authenticated;
grant execute on function private.can_operate_event(uuid) to authenticated;

create trigger events_set_updated_at
before update on public.events
for each row execute function private.set_updated_at();

create trigger event_sectors_set_updated_at
before update on public.event_sectors
for each row execute function private.set_updated_at();

create trigger feedbacks_set_updated_at
before update on public.feedbacks
for each row execute function private.set_updated_at();

create trigger message_inbox_set_updated_at
before update on public.message_inbox
for each row execute function private.set_updated_at();

create trigger outbound_messages_set_updated_at
before update on public.outbound_messages
for each row execute function private.set_updated_at();

create trigger feedbacks_record_status_change
after update of status on public.feedbacks
for each row execute function private.record_feedback_status_change();

create index event_members_user_id_idx
    on public.event_members (user_id, event_id);

create index event_sectors_event_active_idx
    on public.event_sectors (event_id, active, name);

create index config_event_type_idx
    on public.config (event_id, type, name);

create index feedbacks_event_timestamp_idx
    on public.feedbacks (event_id, timestamp desc);

create index feedbacks_event_status_idx
    on public.feedbacks (event_id, status, updated_at desc);

create index feedbacks_event_category_idx
    on public.feedbacks (event_id, category, timestamp desc);

create index feedbacks_active_sender_idx
    on public.feedbacks (event_id, sender_hash, updated_at desc)
    where status in ('aberto', 'em_andamento');

create index message_inbox_pending_idx
    on public.message_inbox (next_attempt_at, created_at)
    where processing_status in ('pending', 'failed');

create index message_inbox_event_occurred_idx
    on public.message_inbox (event_id, occurred_at desc);

create index outbound_messages_queue_idx
    on public.outbound_messages (next_attempt_at, created_at)
    where delivery_status in ('queued', 'failed');

create index outbound_messages_feedback_idx
    on public.outbound_messages (feedback_id, created_at desc);

create index feedback_status_history_feedback_idx
    on public.feedback_status_history (feedback_id, changed_at desc);

-- Remove o acesso público irrestrito deixado pelo protótipo.
drop policy if exists "Permitir leitura config" on public.config;
drop policy if exists "Allow all on feedbacks" on public.feedbacks;
drop policy if exists "Permitir atualização feedbacks" on public.feedbacks;
drop policy if exists "Permitir inserção feedbacks" on public.feedbacks;
drop policy if exists "Permitir leitura feedbacks" on public.feedbacks;

alter table public.events enable row level security;
alter table public.events force row level security;
alter table public.event_members enable row level security;
alter table public.event_members force row level security;
alter table public.event_sectors enable row level security;
alter table public.event_sectors force row level security;
alter table public.config enable row level security;
alter table public.config force row level security;
alter table public.message_inbox enable row level security;
alter table public.message_inbox force row level security;
alter table public.feedbacks enable row level security;
alter table public.feedbacks force row level security;
alter table public.outbound_messages enable row level security;
alter table public.outbound_messages force row level security;
alter table public.feedback_status_history enable row level security;
alter table public.feedback_status_history force row level security;

create policy events_member_select
on public.events
for select
to authenticated
using ((select private.is_event_member(id)));

create policy event_members_self_select
on public.event_members
for select
to authenticated
using (user_id = (select auth.uid()));

create policy event_sectors_member_select
on public.event_sectors
for select
to authenticated
using ((select private.is_event_member(event_id)));

create policy config_member_select
on public.config
for select
to authenticated
using ((select private.is_event_member(event_id)));

create policy feedbacks_member_select
on public.feedbacks
for select
to authenticated
using ((select private.is_event_member(event_id)));

create policy feedbacks_member_update
on public.feedbacks
for update
to authenticated
using ((select private.can_operate_event(event_id)))
with check ((select private.can_operate_event(event_id)));

create policy feedback_history_member_select
on public.feedback_status_history
for select
to authenticated
using ((select private.is_event_member(event_id)));

revoke all on table public.events from public, anon, authenticated;
revoke all on table public.event_members from public, anon, authenticated;
revoke all on table public.event_sectors from public, anon, authenticated;
revoke all on table public.config from public, anon, authenticated;
revoke all on table public.message_inbox from public, anon, authenticated;
revoke all on table public.feedbacks from public, anon, authenticated;
revoke all on table public.outbound_messages from public, anon, authenticated;
revoke all on table public.feedback_status_history from public, anon, authenticated;

grant select on table public.events to authenticated;
grant select on table public.event_members to authenticated;
grant select on table public.event_sectors to authenticated;
grant select on table public.config to authenticated;
grant select on table public.feedbacks to authenticated;
grant update (status, resolved_at, updated_at) on table public.feedbacks to authenticated;
grant select on table public.feedback_status_history to authenticated;

grant all on table public.events to service_role;
grant all on table public.event_members to service_role;
grant all on table public.event_sectors to service_role;
grant all on table public.config to service_role;
grant all on table public.message_inbox to service_role;
grant all on table public.feedbacks to service_role;
grant all on table public.outbound_messages to service_role;
grant all on table public.feedback_status_history to service_role;
grant usage, select on all sequences in schema public to service_role;
