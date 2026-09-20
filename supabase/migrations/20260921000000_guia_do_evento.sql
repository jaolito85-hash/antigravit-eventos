-- Guia do evento: line-up, comida, open bar e ativacoes viram fichas da mesma
-- base de perguntas, com tipo, "vale para" e banner opcional. Assim rascunho,
-- publicar, restaurar e a escolha por IA continuam valendo sem tabela nova.

alter table public.bot_knowledge
    add column kind text not null default 'faq',
    add column scope text,
    add column image_url text;

alter table public.bot_knowledge
    add constraint bot_knowledge_kind_valid
        check (kind in ('faq', 'lineup', 'food', 'bar', 'activation')),
    add constraint bot_knowledge_scope_length
        check (scope is null or char_length(scope) <= 120),
    add constraint bot_knowledge_image_url_length
        check (image_url is null or char_length(image_url) <= 500);

comment on column public.bot_knowledge.kind is
    'faq = pergunta comum; lineup, food, bar e activation = guia do evento.';
comment on column public.bot_knowledge.image_url is
    'Banner publico que o Tuca envia como imagem junto da resposta.';

-- Cardapio e line-up nao cabem em 1500 caracteres.
alter table public.bot_knowledge
    drop constraint bot_knowledge_answer_length,
    add constraint bot_knowledge_answer_length
        check (char_length(answer) between 1 and 4000);

-- O bot passa a mandar imagem (banner) junto da resposta em texto.
alter table public.outbound_messages
    add column media_url text,
    add constraint outbound_media_url_length
        check (media_url is null or char_length(media_url) <= 500);

-- Bucket publico dos banners: a Meta busca a imagem pela URL na hora do envio.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('banners', 'banners', true, 5242880, array['image/jpeg', 'image/png', 'image/webp'])
on conflict (id) do nothing;

create policy banners_leitura_publica
on storage.objects
for select
to public
using (bucket_id = 'banners');
