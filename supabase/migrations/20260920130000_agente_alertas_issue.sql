-- Problema sem correcao no catalogo vira issue no GitHub para o agente da
-- nuvem investigar. O numero fica aqui para nao abrir a mesma issue duas vezes.
alter table public.agent_alerts
    add column if not exists github_issue integer;

comment on column public.agent_alerts.github_issue is
    'Issue aberta no GitHub para o agente da nuvem, quando nao ha correcao no catalogo.';
