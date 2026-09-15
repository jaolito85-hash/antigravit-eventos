-- Registros anteriores ao piloto não podem contaminar as métricas reais do
-- Tropicadelia. Eles permanecem preservados em um evento legado arquivado.
insert into public.events (
    slug,
    name,
    status,
    metadata
)
values (
    'legacy-prototype',
    'Dados históricos do protótipo',
    'archived',
    '{"legacy": true, "dashboard_visible": false}'::jsonb
)
on conflict (slug) do nothing;

update public.feedbacks
set event_id = (
        select id
        from public.events
        where slug = 'legacy-prototype'
    ),
    updated_at = now()
where event_id = (
        select id
        from public.events
        where slug = 'tropicadelia-2026'
    )
  and inbox_message_id is null;

-- O protótipo inseria IDs manualmente, deixando a sequence atrás do maior ID.
-- Sem este ajuste, a próxima inserção automática colidiria com dados existentes.
select setval(
    pg_get_serial_sequence('public.feedbacks', 'id'),
    greatest((select coalesce(max(id), 0) from public.feedbacks), 1),
    (select count(*) > 0 from public.feedbacks)
);
