-- Perguntas e respostas oficiais que o ChatBob deve seguir, e o ajuste de tom.
--
-- A resposta cadastrada manda no conteudo. O tom continua vindo da IA, que
-- recebe a resposta oficial como informacao a transmitir; se a IA estiver
-- fora, o texto cadastrado vai como esta.

create table public.bot_knowledge (
    id uuid primary key default gen_random_uuid(),
    event_id uuid not null references public.events(id) on delete cascade,
    question text not null,
    answer text not null,
    keywords text[] not null default '{}',
    priority smallint not null default 0,
    active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint bot_knowledge_question_length check (char_length(question) between 3 and 300),
    constraint bot_knowledge_answer_length check (char_length(answer) between 1 and 1500),
    constraint bot_knowledge_priority_valid check (priority between 0 and 100),
    constraint bot_knowledge_keywords_size check (cardinality(keywords) <= 30)
);

comment on table public.bot_knowledge is
    'Base de perguntas e respostas que o ChatBob usa antes da resposta genérica.';

-- O worker le a base ativa a cada mensagem; o indice cobre essa consulta.
create index bot_knowledge_active_idx
    on public.bot_knowledge (event_id, active, priority desc);

create trigger bot_knowledge_set_updated_at
before update on public.bot_knowledge
for each row execute function private.set_updated_at();

alter table public.bot_knowledge enable row level security;
alter table public.bot_knowledge force row level security;

create policy bot_knowledge_member_select
on public.bot_knowledge
for select
to authenticated
using ((select private.is_event_member(event_id)));

-- Ajustes de identidade do bot, uma linha por evento.
create table public.bot_settings (
    event_id uuid primary key references public.events(id) on delete cascade,
    persona text,
    welcome text,
    updated_at timestamptz not null default now(),
    constraint bot_settings_persona_length check (persona is null or char_length(persona) <= 2000),
    constraint bot_settings_welcome_length check (welcome is null or char_length(welcome) <= 1500)
);

comment on table public.bot_settings is
    'Tom de voz e boas-vindas configurados para o ChatBob do evento.';

create trigger bot_settings_set_updated_at
before update on public.bot_settings
for each row execute function private.set_updated_at();

alter table public.bot_settings enable row level security;
alter table public.bot_settings force row level security;

create policy bot_settings_member_select
on public.bot_settings
for select
to authenticated
using ((select private.is_event_member(event_id)));

-- Perguntas que o publico de festival faz sempre, para a base nao nascer vazia.
insert into public.bot_knowledge (event_id, question, answer, keywords, priority)
select
    e.id,
    v.question,
    v.answer,
    v.keywords::text[],
    v.priority
from public.events e
cross join (
    values
        (
            'Que horas começa e termina o festival?',
            'A Tropicadelia 2026 abre os portões às 15h30 de sábado (26/09) e vai até as 4h da manhã de domingo (27/09).',
            '{"que horas","horario","abre","fecha","termina","comeca","começa","abertura"}',
            90
        ),
        (
            'Onde fica o festival e como chego?',
            'Estamos no Parque de Exposições Governador Ney Braga, em Londrina. A portaria principal fica na Zona Leste do parque, com estacionamento nos bolsões Norte e Leste.',
            '{"onde fica","endereco","endereço","como chego","local","chegar","estacionamento"}',
            80
        ),
        (
            'Posso entrar com garrafa de água ou comida?',
            'Garrafa de água sem tampa e lacrada até 500ml é liberada. Comida e bebida alcoólica de fora não entram. Temos pontos de hidratação gratuitos na praça central.',
            '{"garrafa","agua","água","posso entrar","comida","levar","proibido","permitido"}',
            70
        ),
        (
            'Perdi um objeto, o que faço?',
            'Procure o CCO, nossa Central de Controle, que também cuida dos achados e perdidos. Fica na Zona Centro, perto dos lockers. Me conte o que você perdeu que eu já registro aqui.',
            '{"perdi","achei","achados","perdidos","esqueci","roubaram","sumiu"}',
            75
        ),
        (
            'Tem acessibilidade para cadeirante?',
            'Sim. Temos portão de acesso exclusivo PCD na Zona Oeste, plataforma elevada com vista para o Palco Principal e equipe de acolhimento. Procure qualquer fiscal que nós acompanhamos você.',
            '{"pcd","cadeirante","acessibilidade","deficiente","cadeira de rodas","acessivel","acessível"}',
            85
        ),
        (
            'Como funciona o pagamento nos bares?',
            'Os bares trabalham com cartão e Pix nos totens oficiais do festival. Atenção: o ChatBob nunca pede Pix nem dados de cartão por mensagem.',
            '{"pagamento","pix","cartao","cartão","dinheiro","ficha","como pago"}',
            60
        ),
        (
            'Quem toca e a que horas?',
            'A grade completa está nos telões de cada palco e no perfil oficial da Tropicadelia. Me diga qual palco te interessa que eu passo o horário da próxima atração.',
            '{"line up","lineup","grade","quem toca","atracao","atração","programacao","programação","show de"}',
            65
        )
) as v(question, answer, keywords, priority)
where e.slug = 'tropicadelia-2026';
