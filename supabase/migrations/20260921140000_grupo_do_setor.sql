-- Agrupa os 36 setores por tipo de lugar, para o relatório fechar contas.
--
-- O setor responde "onde exatamente" e acende o pino no mapa. O grupo responde
-- "que espécie de lugar", que é o que o organizador lê no fim do evento:
-- "287 chamados em Sanitários" não cabe em nenhum dos 36 nomes nem em nenhuma
-- das 6 categorias, porque banheiro não é assunto, é tipo de lugar.
--
-- O mapeamento mora aqui e não no código: desativar um setor tem que sumir
-- com ele da conta sem ninguém lembrar de editar duas listas.

update public.event_sectors s
set metadata = s.metadata || jsonb_build_object('group', g.nome)
from (
    values
        ('WC-FEM-PALCO', 'Sanitários'),
        ('WC-MASC-PALCO', 'Sanitários'),
        ('WC-PISTA-NORTE-1', 'Sanitários'),
        ('WC-PISTA-NORTE-2', 'Sanitários'),
        ('WC-PISTA-OESTE-1', 'Sanitários'),
        ('WC-PISTA-OESTE-2', 'Sanitários'),
        ('WC-PISTA-CENTRAL', 'Sanitários'),
        ('WC-LOUNGE-BOSQUE', 'Sanitários'),
        ('WC-BACKSTAGE-HYPE', 'Sanitários'),

        ('BAR-BUDWEISER-PISTA', 'Bares'),
        ('BAR-BUDWEISER-LOUNGE', 'Bares'),
        ('BAR-COCO-LEVE', 'Bares'),
        ('BAR-DESTILADOS-1', 'Bares'),
        ('BAR-DESTILADOS-2', 'Bares'),

        ('PRACA-ALIMENTACAO', 'Alimentação'),
        ('ALAMEDA-GASTRONOMICA', 'Alimentação'),
        ('OPEN-FOOD-1', 'Alimentação'),
        ('OPEN-FOOD-2', 'Alimentação'),

        ('ATIVACAO-WHITEHORSE', 'Ativações e Lazer'),
        ('ATIVACAO-REDBULL', 'Ativações e Lazer'),
        ('FEIRINHA-TATTOO', 'Ativações e Lazer'),
        ('NY-LOUNGE', 'Ativações e Lazer'),
        ('AREA-DESCANSO', 'Ativações e Lazer'),

        ('SAC-ACHADOS-PERDIDOS', 'Atendimento ao Público'),
        ('UPGRADE-PULSEIRA', 'Atendimento ao Público'),
        ('LOCKERS', 'Atendimento ao Público'),
        ('LOJINHA-OFICIAL', 'Atendimento ao Público'),

        ('ACESSO-CATRACAS-SUL', 'Entradas e Acessos'),
        ('ACESSO-LOUNGE-BACKSTAGE', 'Entradas e Acessos'),
        ('SAIDA-LOUNGE-EXCURSOES', 'Entradas e Acessos'),

        ('PALCO-TROPICAL', 'Palcos'),
        ('PALCO-HYPE', 'Palcos'),

        ('AMBULATORIO-PISTA', 'Saúde'),
        ('AMBULATORIO-LOUNGE', 'Saúde'),

        ('PCD-RETIRADA-PULSEIRA', 'Acessibilidade'),
        ('PCD-PLATAFORMA-TROPICAL', 'Acessibilidade')
) as g(code, nome)
where s.code = g.code
  and s.event_id = (select id from public.events where slug = 'tropicadelia-2026');

-- Setor sem grupo não quebra nada, só fica fora do corte por tipo de lugar.
-- Este aviso existe para quem adicionar setor novo na planta lembrar do campo.
do $$
declare
    sem_grupo int;
begin
    select count(*) into sem_grupo
    from public.event_sectors s
    join public.events e on e.id = s.event_id
    where e.slug = 'tropicadelia-2026'
      and s.active
      and s.metadata->>'group' is null;

    if sem_grupo > 0 then
        raise warning 'Setores ativos sem grupo: %. Eles ficam fora do relatório por tipo de lugar.', sem_grupo;
    end if;
end $$;
