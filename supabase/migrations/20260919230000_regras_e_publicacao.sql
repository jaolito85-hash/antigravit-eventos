-- Regras de negocio do Tuca e o fluxo de rascunho e publicacao.
--
-- Ate aqui o que a producao cadastrava ia para o ar direto, sem revisao e sem
-- volta. Agora as tabelas de cadastro (bot_knowledge, bot_rules, bot_settings)
-- passam a ser o RASCUNHO, e o bot le uma FOTOGRAFIA publicada, guardada em
-- bot_config_version. Publicar tira a foto; reverter marca uma foto antiga
-- como a que vale.
--
-- Motivo: quem abastece a base durante o festival precisa poder errar sem
-- derrubar a resposta que chega no WhatsApp do participante.

-- ---------------------------------------------------------------------------
-- Regras de negocio, uma linha por regra para poder desligar so a problematica
-- ---------------------------------------------------------------------------

create table public.bot_rules (
    id uuid primary key default gen_random_uuid(),
    event_id uuid not null references public.events(id) on delete cascade,
    title text not null,
    body text not null,
    priority smallint not null default 50,
    active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint bot_rules_title_length check (char_length(title) between 3 and 120),
    constraint bot_rules_body_length check (char_length(body) between 3 and 1000),
    constraint bot_rules_priority_valid check (priority between 0 and 100)
);

comment on table public.bot_rules is
    'Regras de comportamento que valem mais que a criatividade da IA. Entram no prompt do Tuca em ordem de prioridade.';

create index bot_rules_active_idx
    on public.bot_rules (event_id, active, priority desc);

create trigger bot_rules_set_updated_at
before update on public.bot_rules
for each row execute function private.set_updated_at();

alter table public.bot_rules enable row level security;
alter table public.bot_rules force row level security;

create policy bot_rules_member_select
on public.bot_rules
for select
to authenticated
using ((select private.is_event_member(event_id)));

-- ---------------------------------------------------------------------------
-- Link do app oficial: era para ser configuravel desde a reuniao com os socios
-- ---------------------------------------------------------------------------

alter table public.bot_settings
    add column app_url text;

comment on column public.bot_settings.app_url is
    'Link do app oficial do festival. E o fallback universal do Tuca: o que ele nao sabe, manda para ca.';

alter table public.bot_settings
    add constraint bot_settings_app_url_length
    check (app_url is null or char_length(app_url) <= 300);

-- ---------------------------------------------------------------------------
-- Versoes publicadas: o que o bot realmente le
-- ---------------------------------------------------------------------------

create table public.bot_config_version (
    id uuid primary key default gen_random_uuid(),
    event_id uuid not null references public.events(id) on delete cascade,
    payload jsonb not null,
    author text,
    note text,
    is_live boolean not null default false,
    created_at timestamptz not null default now(),
    constraint bot_config_version_note_length check (note is null or char_length(note) <= 200),
    constraint bot_config_version_author_length check (author is null or char_length(author) <= 80)
);

comment on table public.bot_config_version is
    'Fotografia da configuracao do bot no momento em que alguem publicou. A linha com is_live verdadeiro e a que esta no ar.';

-- So pode existir uma versao no ar por evento. O indice parcial garante isso
-- no banco, entao uma corrida entre duas publicacoes nao deixa o bot sem rumo.
create unique index bot_config_version_live_idx
    on public.bot_config_version (event_id)
    where is_live;

create index bot_config_version_history_idx
    on public.bot_config_version (event_id, created_at desc);

alter table public.bot_config_version enable row level security;
alter table public.bot_config_version force row level security;

create policy bot_config_version_member_select
on public.bot_config_version
for select
to authenticated
using ((select private.is_event_member(event_id)));

-- ---------------------------------------------------------------------------
-- Regras acordadas com os socios em 19/09/2026
-- ---------------------------------------------------------------------------

insert into public.bot_rules (event_id, title, body, priority)
select e.id, v.title, v.body, v.priority
from public.events e
cross join (
    values
        (
            'Nunca inventar',
            'Se você não sabe a resposta, diga que não sabe e mande o link do app oficial do festival, onde estão as informações completas. O link é o destino de tudo que você não souber. Nunca chute horário, nome de atração, preço ou local.',
            100
        ),
        (
            'Nunca prometer solução sem certeza',
            'O padrão é dizer que o chamado foi enviado para a equipe, nunca que o problema será resolvido. A única exceção é falta de insumo, como acabou o gelo ou acabou a cerveja: nesses casos a equipe resolve sempre, então você pode dizer que o pessoal já está a caminho.',
            95
        ),
        (
            'Emergência e saúde',
            'Primeiro acalme a pessoa, depois peça a localização dela. Se ela não clicar no link de localização, peça mais informação por texto ou áudio. Assim que receber, confirme que a equipe foi acionada.',
            90
        ),
        (
            'Rota e caminho nunca em texto solto',
            'Nunca descreva o trajeto passo a passo. Dê a referência aproximada e mande o app oficial. Exemplo do formato: "Fica pertinho do palco Hype! A rota completa e o local exato você encontra no app oficial."',
            85
        ),
        (
            'Áudio que não dá para entender',
            'Quando o áudio vier vazio ou incompreensível, peça com gentileza para a pessoa mandar em texto. Não tente adivinhar o que ela quis dizer.',
            60
        ),
        (
            'Lojinha oficial',
            'Quando fizer sentido na conversa, lembre do copo oficial e dos produtos do festival. Nunca force e nunca repita se a pessoa não demonstrar interesse.',
            40
        )
) as v(title, body, priority)
where e.slug = 'tropicadelia-2026';

-- ---------------------------------------------------------------------------
-- Primeira publicacao: sem ela o bot subiria sem base nenhuma
-- ---------------------------------------------------------------------------

insert into public.bot_config_version (event_id, payload, author, note, is_live)
select
    e.id,
    jsonb_build_object(
        'knowledge', coalesce((
            select jsonb_agg(
                jsonb_build_object(
                    'id', k.id,
                    'question', k.question,
                    'answer', k.answer,
                    'keywords', k.keywords,
                    'priority', k.priority,
                    'active', k.active
                )
                order by k.priority desc
            )
            from public.bot_knowledge k
            where k.event_id = e.id and k.active
        ), '[]'::jsonb),
        'rules', coalesce((
            select jsonb_agg(
                jsonb_build_object(
                    'id', r.id,
                    'title', r.title,
                    'body', r.body,
                    'priority', r.priority,
                    'active', r.active
                )
                order by r.priority desc
            )
            from public.bot_rules r
            where r.event_id = e.id and r.active
        ), '[]'::jsonb),
        'settings', coalesce((
            select jsonb_build_object(
                'persona', s.persona,
                'welcome', s.welcome,
                'appUrl', s.app_url
            )
            from public.bot_settings s
            where s.event_id = e.id
        ), jsonb_build_object('persona', null, 'welcome', null, 'appUrl', null))
    ),
    'migracao',
    'Primeira versão, tirada do que já estava cadastrado',
    true
from public.events e
where e.slug = 'tropicadelia-2026';
