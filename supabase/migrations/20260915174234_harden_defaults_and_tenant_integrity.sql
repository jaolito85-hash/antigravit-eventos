-- Toda concessão em objetos futuros deve ser explícita. Isso evita que uma nova
-- tabela ou função criada no schema exposto herde acesso amplo por acidente.
alter default privileges for role postgres in schema public
    revoke all on tables from public, anon, authenticated;
alter default privileges for role postgres in schema public
    revoke all on sequences from public, anon, authenticated;
alter default privileges for role postgres in schema public
    revoke all on functions from public, anon, authenticated;

alter default privileges for role supabase_admin in schema public
    revoke all on tables from public, anon, authenticated;
alter default privileges for role supabase_admin in schema public
    revoke all on sequences from public, anon, authenticated;
alter default privileges for role supabase_admin in schema public
    revoke all on functions from public, anon, authenticated;

alter default privileges for role postgres in schema private
    revoke all on tables from public, anon, authenticated;
alter default privileges for role postgres in schema private
    revoke all on sequences from public, anon, authenticated;
alter default privileges for role postgres in schema private
    revoke all on functions from public, anon, authenticated;

-- As chaves compostas fazem o PostgreSQL impedir que um setor, mensagem,
-- feedback relacionado ou histórico pertença a outro evento.
alter table public.event_sectors
    add constraint event_sectors_event_id_id_unique unique (event_id, id);

alter table public.message_inbox
    add constraint message_inbox_event_id_id_unique unique (event_id, id);

alter table public.feedbacks
    add constraint feedbacks_event_id_id_unique unique (event_id, id);

alter table public.feedbacks
    drop constraint feedbacks_sector_id_fkey,
    drop constraint feedbacks_inbox_message_id_fkey,
    drop constraint feedbacks_linked_from_fk,
    add constraint feedbacks_event_sector_fk
        foreign key (event_id, sector_id)
        references public.event_sectors(event_id, id)
        on delete restrict,
    add constraint feedbacks_event_inbox_fk
        foreign key (event_id, inbox_message_id)
        references public.message_inbox(event_id, id)
        on delete restrict,
    add constraint feedbacks_event_linked_from_fk
        foreign key (event_id, linked_from)
        references public.feedbacks(event_id, id)
        on delete restrict;

alter table public.message_inbox
    drop constraint message_inbox_sector_id_fkey,
    add constraint message_inbox_event_sector_fk
        foreign key (event_id, sector_id)
        references public.event_sectors(event_id, id)
        on delete restrict;

alter table public.outbound_messages
    drop constraint outbound_messages_feedback_id_fkey,
    add constraint outbound_messages_event_feedback_fk
        foreign key (event_id, feedback_id)
        references public.feedbacks(event_id, id)
        on delete restrict;

alter table public.feedback_status_history
    drop constraint feedback_status_history_feedback_id_fkey,
    add constraint feedback_history_event_feedback_fk
        foreign key (event_id, feedback_id)
        references public.feedbacks(event_id, id)
        on delete cascade;

drop index public.feedbacks_sector_idx;
create index feedbacks_event_sector_idx
    on public.feedbacks (event_id, sector_id, timestamp desc)
    where sector_id is not null;

drop index public.message_inbox_sector_idx;
create index message_inbox_event_sector_idx
    on public.message_inbox (event_id, sector_id, occurred_at desc)
    where sector_id is not null;
