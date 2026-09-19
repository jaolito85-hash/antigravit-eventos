-- O bot passou a se chamar Tuca, o tucano da Tropicadelia, decidido com os
-- sócios em 19/09/2026.
--
-- Só os comentários do schema precisaram mudar: as perguntas e respostas
-- ativas não citavam o nome antigo, e os setores foram reescritos na migração
-- da planta oficial. As migrações anteriores ficam como estão, porque
-- migração aplicada é histórico e não se reescreve.

comment on table public.bot_knowledge is
    'Base de perguntas e respostas que o Tuca usa antes da resposta genérica.';

comment on table public.bot_settings is
    'Tom de voz e boas-vindas configurados para o Tuca do evento.';
