drop index public.feedback_status_history_event_idx;
create index feedback_status_history_event_feedback_idx
    on public.feedback_status_history (event_id, feedback_id, changed_at desc);

create index feedbacks_event_inbox_idx
    on public.feedbacks (event_id, inbox_message_id)
    where inbox_message_id is not null;

drop index public.feedbacks_linked_from_idx;
create index feedbacks_event_linked_from_idx
    on public.feedbacks (event_id, linked_from)
    where linked_from is not null;

drop index public.outbound_messages_event_idx;
create index outbound_messages_event_feedback_idx
    on public.outbound_messages (event_id, feedback_id, created_at desc);
