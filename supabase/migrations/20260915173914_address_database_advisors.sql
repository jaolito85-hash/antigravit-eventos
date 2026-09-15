-- Policies de bloqueio explícito documentam que as filas são backend-only e
-- evitam que o linter confunda ausência intencional de acesso com omissão.
create policy message_inbox_backend_only
on public.message_inbox
for all
to anon, authenticated
using (false)
with check (false);

create policy outbound_messages_backend_only
on public.outbound_messages
for all
to anon, authenticated
using (false)
with check (false);

-- Índices de cobertura para todas as FKs, especialmente importantes em
-- exclusões/anonimizações ao final do período de retenção do evento.
create index feedback_status_history_changed_by_idx
    on public.feedback_status_history (changed_by)
    where changed_by is not null;

create index feedback_status_history_event_idx
    on public.feedback_status_history (event_id, changed_at desc);

create index feedbacks_linked_from_idx
    on public.feedbacks (linked_from)
    where linked_from is not null;

create index feedbacks_sector_idx
    on public.feedbacks (sector_id, timestamp desc)
    where sector_id is not null;

create index message_inbox_sector_idx
    on public.message_inbox (sector_id, occurred_at desc)
    where sector_id is not null;

create index outbound_messages_event_idx
    on public.outbound_messages (event_id, created_at desc);
