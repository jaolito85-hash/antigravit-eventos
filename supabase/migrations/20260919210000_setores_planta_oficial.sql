-- Remapeia os setores para a planta oficial que os sócios entregaram em 19/09/2026.
--
-- A planta anterior foi montada por IA e os sócios confirmaram que não estava
-- correta: nomes como "Zona Centro" e "Zona Oeste" não existem no evento. As
-- zonas reais são as três da legenda da arte: Pista, Tropical Lounge e
-- Backstage Hype.
--
-- As coordenadas são porcentagem sobre a arte oficial completa
-- (static/planta-tropicadelia-oficial.jpg, 2800x2250) e foram conferidas uma a
-- uma desenhando os pinos sobre a imagem, não estimadas no olho.
--
-- Os setores antigos que não existem na planta são desativados, nunca
-- apagados, porque os chamados de teste apontam para eles.

insert into public.event_sectors (event_id, code, name, active, metadata)
select
    e.id,
    v.code,
    v.name,
    true,
    v.metadata::jsonb
from public.events e
cross join (
    values
        -- ---------- PISTA ----------
        (
            'PALCO-TROPICAL',
            'Palco Tropical • Principal',
            '{"zone": "Pista", "category": "Estrutura & Espaço", "team": "producao_artistica", "priority": "normal", "coord": {"x": 39, "y": 78}, "cta": "Som, visão de palco ou aperto na pista? Conte aqui."}'
        ),
        (
            'WC-FEM-PALCO',
            'Sanitários Femininos • Palco Tropical',
            '{"zone": "Pista", "category": "Estrutura & Espaço", "team": "limpeza_higienizacao", "priority": "normal", "coord": {"x": 51, "y": 77}, "cta": "Falta papel, sabonete ou a fila travou? Avise a equipe."}'
        ),
        (
            'WC-MASC-PALCO',
            'Sanitários Masculinos • Palco Tropical',
            '{"zone": "Pista", "category": "Estrutura & Espaço", "team": "limpeza_higienizacao", "priority": "normal", "coord": {"x": 46, "y": 71}, "cta": "Falta papel, sabonete ou a fila travou? Avise a equipe."}'
        ),
        (
            'WC-PISTA-NORTE-1',
            'Sanitários Pista • Acesso Norte 1',
            '{"zone": "Pista", "category": "Estrutura & Espaço", "team": "limpeza_higienizacao", "priority": "normal", "coord": {"x": 47, "y": 19}, "cta": "Falta papel, sabonete ou a fila travou? Avise a equipe."}'
        ),
        (
            'WC-PISTA-NORTE-2',
            'Sanitários Pista • Acesso Norte 2',
            '{"zone": "Pista", "category": "Estrutura & Espaço", "team": "limpeza_higienizacao", "priority": "normal", "coord": {"x": 45, "y": 24}, "cta": "Falta papel, sabonete ou a fila travou? Avise a equipe."}'
        ),
        (
            'WC-PISTA-OESTE-1',
            'Sanitários Pista • Oeste 1',
            '{"zone": "Pista", "category": "Estrutura & Espaço", "team": "limpeza_higienizacao", "priority": "normal", "coord": {"x": 18, "y": 64}, "cta": "Falta papel, sabonete ou a fila travou? Avise a equipe."}'
        ),
        (
            'WC-PISTA-OESTE-2',
            'Sanitários Pista • Oeste 2',
            '{"zone": "Pista", "category": "Estrutura & Espaço", "team": "limpeza_higienizacao", "priority": "normal", "coord": {"x": 18, "y": 69}, "cta": "Falta papel, sabonete ou a fila travou? Avise a equipe."}'
        ),
        (
            'WC-PISTA-CENTRAL',
            'Sanitários Pista • Central',
            '{"zone": "Pista", "category": "Estrutura & Espaço", "team": "limpeza_higienizacao", "priority": "normal", "coord": {"x": 32, "y": 41}, "cta": "Falta papel, sabonete ou a fila travou? Avise a equipe."}'
        ),
        (
            'PRACA-ALIMENTACAO',
            'Praça de Alimentação • Mesas e Food Park',
            '{"zone": "Pista", "category": "Alimentação & Bebidas", "team": "operacao_praca", "priority": "normal", "coord": {"x": 11, "y": 46}, "cta": "Demora, preço ou comida fria? Queremos saber agora."}'
        ),
        (
            'ALAMEDA-GASTRONOMICA',
            'Alameda Gastronômica • Gramado',
            '{"zone": "Pista", "category": "Alimentação & Bebidas", "team": "operacao_praca", "priority": "normal", "coord": {"x": 24, "y": 50}, "cta": "Demora, preço ou comida fria? Queremos saber agora."}'
        ),
        (
            'FEIRINHA-TATTOO',
            'Feirinha & Estúdio Tattoo',
            '{"zone": "Pista", "category": "Experiência Geral", "team": "experiencia_marcas", "priority": "normal", "coord": {"x": 26, "y": 44}, "cta": "Como está a experiência na feirinha? Conte para a gente."}'
        ),
        (
            'ATIVACAO-WHITEHORSE',
            'Ativação White Horse • Pista Oeste',
            '{"zone": "Pista", "category": "Experiência Geral", "team": "experiencia_marcas", "priority": "normal", "coord": {"x": 7, "y": 35}, "cta": "Fila grande ou tudo tranquilo na ativação? Avise aqui."}'
        ),
        (
            'ATIVACAO-REDBULL',
            'Ativação Red Bull • Pista',
            '{"zone": "Pista", "category": "Experiência Geral", "team": "experiencia_marcas", "priority": "normal", "coord": {"x": 25, "y": 64}, "cta": "Fila grande ou tudo tranquilo na ativação? Avise aqui."}'
        ),
        (
            'NY-LOUNGE',
            'NY Lounge • Deck de Convivência',
            '{"zone": "Pista", "category": "Experiência Geral", "team": "experiencia_marcas", "priority": "normal", "coord": {"x": 22, "y": 70}, "cta": "Espaço, limpeza ou atendimento no deck? Fale com a gente."}'
        ),
        (
            'BAR-BUDWEISER-PISTA',
            'Bar Budweiser • Pista',
            '{"zone": "Pista", "category": "Alimentação & Bebidas", "team": "bar_insumos", "priority": "normal", "coord": {"x": 28, "y": 71}, "cta": "Acabou o gelo, a cerveja ou a fila travou? Avise na hora."}'
        ),
        (
            'BAR-COCO-LEVE',
            'Coco Leve • Pista Sul',
            '{"zone": "Pista", "category": "Alimentação & Bebidas", "team": "bar_insumos", "priority": "normal", "coord": {"x": 39, "y": 88}, "cta": "Acabou o gelo, o produto ou a fila travou? Avise na hora."}'
        ),
        (
            'AREA-DESCANSO',
            'Área de Descanso • Pista Sul',
            '{"zone": "Pista", "category": "Experiência Geral", "team": "bem_estar", "priority": "normal", "coord": {"x": 23, "y": 87}, "cta": "Precisa de um lugar para sentar ou de água? Fale com a gente."}'
        ),
        (
            'AMBULATORIO-PISTA',
            'Ambulatório • Pista',
            '{"zone": "Pista", "category": "Segurança & Organização", "team": "saude_emergencia", "priority": "critico", "coord": {"x": 15, "y": 56}, "cta": "Emergência de saúde? Fale agora que acionamos a equipe."}'
        ),
        (
            'PCD-RETIRADA-PULSEIRA',
            'Apoio PCD • Retirada de Pulseira',
            '{"zone": "Pista", "category": "Segurança & Organização", "team": "acessibilidade", "priority": "normal", "coord": {"x": 19, "y": 56}, "cta": "Precisa da pulseira PCD ou de apoio? A equipe te acompanha."}'
        ),
        (
            'PCD-PLATAFORMA-TROPICAL',
            'Plataforma Elevada PCD • Palco Tropical',
            '{"zone": "Pista", "category": "Segurança & Organização", "team": "acessibilidade", "priority": "critico", "coord": {"x": 27, "y": 81}, "cta": "Precisa de apoio ou acessibilidade? Fale direto com a equipe."}'
        ),
        (
            'ACESSO-CATRACAS-SUL',
            'Catracas Sul • Entrada e Saída',
            '{"zone": "Pista", "category": "Credenciamento & Ingressos", "team": "portaria_ingressos", "priority": "normal", "coord": {"x": 33, "y": 93}, "cta": "Fila na catraca ou problema com a pulseira? Avise aqui."}'
        ),
        -- ---------- TROPICAL LOUNGE ----------
        (
            'LOJINHA-OFICIAL',
            'Lojinha Oficial • Copos e Produtos',
            '{"zone": "Tropical Lounge", "category": "Experiência Geral", "team": "lojinha_oficial", "priority": "normal", "coord": {"x": 33, "y": 55}, "cta": "Fila, estoque ou dúvida sobre o copo oficial? Fale aqui."}'
        ),
        (
            'BAR-DESTILADOS-1',
            'Open Bar Destilados • Galpão 1',
            '{"zone": "Tropical Lounge", "category": "Alimentação & Bebidas", "team": "bar_insumos", "priority": "normal", "coord": {"x": 37, "y": 57}, "cta": "Acabou o gelo, a bebida ou a fila travou? Avise na hora."}'
        ),
        (
            'BAR-DESTILADOS-2',
            'Open Bar Destilados • Galpão 2',
            '{"zone": "Tropical Lounge", "category": "Alimentação & Bebidas", "team": "bar_insumos", "priority": "normal", "coord": {"x": 43, "y": 58}, "cta": "Acabou o gelo, a bebida ou a fila travou? Avise na hora."}'
        ),
        (
            'BAR-BUDWEISER-LOUNGE',
            'Bar Budweiser • Tropical Lounge',
            '{"zone": "Tropical Lounge", "category": "Alimentação & Bebidas", "team": "bar_insumos", "priority": "normal", "coord": {"x": 48, "y": 61}, "cta": "Acabou o gelo, a cerveja ou a fila travou? Avise na hora."}'
        ),
        (
            'OPEN-FOOD-1',
            'Open Food • Galpão 1',
            '{"zone": "Tropical Lounge", "category": "Alimentação & Bebidas", "team": "gastronomia_lounge", "priority": "normal", "coord": {"x": 47, "y": 38}, "cta": "Demora, prato frio ou item em falta? Conte para a gente."}'
        ),
        (
            'OPEN-FOOD-2',
            'Open Food • Galpão 2',
            '{"zone": "Tropical Lounge", "category": "Alimentação & Bebidas", "team": "gastronomia_lounge", "priority": "normal", "coord": {"x": 57, "y": 40}, "cta": "Demora, prato frio ou item em falta? Conte para a gente."}'
        ),
        (
            'LOCKERS',
            'Lockers • Guarda-Volumes',
            '{"zone": "Tropical Lounge", "category": "Estrutura & Espaço", "team": "atendimento_lockers", "priority": "normal", "coord": {"x": 54, "y": 49}, "cta": "Dúvida de disponibilidade ou problema no locker? Fale aqui."}'
        ),
        (
            'SAC-ACHADOS-PERDIDOS',
            'SAC • Achados e Perdidos',
            '{"zone": "Tropical Lounge", "category": "Segurança & Organização", "team": "sac_atendimento", "priority": "normal", "coord": {"x": 35, "y": 65}, "cta": "Perdeu algo ou precisa de atendimento? Me conte o que houve."}'
        ),
        (
            'UPGRADE-PULSEIRA',
            'Upgrade de Pulseira • Compra e Retirada',
            '{"zone": "Tropical Lounge", "category": "Credenciamento & Ingressos", "team": "sac_atendimento", "priority": "normal", "coord": {"x": 40, "y": 65}, "cta": "Quer trocar ou fazer upgrade da pulseira? Fale com a gente."}'
        ),
        (
            'AMBULATORIO-LOUNGE',
            'Ambulatório • Tropical Lounge',
            '{"zone": "Tropical Lounge", "category": "Segurança & Organização", "team": "saude_emergencia", "priority": "critico", "coord": {"x": 53, "y": 45}, "cta": "Emergência de saúde? Fale agora que acionamos a equipe."}'
        ),
        (
            'WC-LOUNGE-BOSQUE',
            'Sanitários • Bosque do Lounge',
            '{"zone": "Tropical Lounge", "category": "Estrutura & Espaço", "team": "limpeza_higienizacao", "priority": "normal", "coord": {"x": 39, "y": 45}, "cta": "Falta papel, sabonete ou a fila travou? Avise a equipe."}'
        ),
        (
            'SAIDA-LOUNGE-EXCURSOES',
            'Saída Lounge • Excursões e Ônibus',
            '{"zone": "Tropical Lounge", "category": "Credenciamento & Ingressos", "team": "portaria_ingressos", "priority": "normal", "coord": {"x": 30, "y": 61}, "cta": "Precisa achar seu ônibus ou a saída? A gente te orienta."}'
        ),
        -- ---------- BACKSTAGE HYPE ----------
        (
            'PALCO-HYPE',
            'Palco Hype • Arena',
            '{"zone": "Backstage Hype", "category": "Estrutura & Espaço", "team": "producao_artistica", "priority": "normal", "coord": {"x": 63, "y": 22}, "cta": "Som, ventilação ou espaço na Arena? Avise a coordenação."}'
        ),
        (
            'WC-BACKSTAGE-HYPE',
            'Sanitários • Backstage Hype',
            '{"zone": "Backstage Hype", "category": "Estrutura & Espaço", "team": "limpeza_higienizacao", "priority": "normal", "coord": {"x": 57, "y": 34}, "cta": "Falta papel, sabonete ou a fila travou? Avise a equipe."}'
        ),
        (
            'ACESSO-LOUNGE-BACKSTAGE',
            'Acesso Exclusivo • Lounge e Backstage',
            '{"zone": "Backstage Hype", "category": "Credenciamento & Ingressos", "team": "portaria_vip", "priority": "normal", "coord": {"x": 41, "y": 40}, "cta": "Problema no acesso ou na credencial? Fale com a gente."}'
        )
) as v(code, name, metadata)
where e.slug = 'tropicadelia-2026'
on conflict (event_id, code) do update
set name = excluded.name,
    metadata = excluded.metadata,
    active = true,
    updated_at = now();

-- Os pontos da planta antiga que não existem na oficial saem do mapa, mas as
-- linhas ficam, porque os chamados de teste referenciam esses códigos.
update public.event_sectors s
set active = false,
    updated_at = now()
from public.events e
where s.event_id = e.id
  and e.slug = 'tropicadelia-2026'
  and s.code not in (
    'PALCO-TROPICAL', 'WC-FEM-PALCO', 'WC-MASC-PALCO', 'WC-PISTA-NORTE-1',
    'WC-PISTA-NORTE-2', 'WC-PISTA-OESTE-1', 'WC-PISTA-OESTE-2', 'WC-PISTA-CENTRAL',
    'PRACA-ALIMENTACAO', 'ALAMEDA-GASTRONOMICA', 'FEIRINHA-TATTOO',
    'ATIVACAO-WHITEHORSE', 'ATIVACAO-REDBULL', 'NY-LOUNGE', 'BAR-BUDWEISER-PISTA',
    'BAR-COCO-LEVE', 'AREA-DESCANSO', 'AMBULATORIO-PISTA', 'PCD-RETIRADA-PULSEIRA',
    'PCD-PLATAFORMA-TROPICAL', 'ACESSO-CATRACAS-SUL', 'LOJINHA-OFICIAL',
    'BAR-DESTILADOS-1', 'BAR-DESTILADOS-2', 'BAR-BUDWEISER-LOUNGE', 'OPEN-FOOD-1',
    'OPEN-FOOD-2', 'LOCKERS', 'SAC-ACHADOS-PERDIDOS', 'UPGRADE-PULSEIRA',
    'AMBULATORIO-LOUNGE', 'WC-LOUNGE-BOSQUE', 'SAIDA-LOUNGE-EXCURSOES',
    'PALCO-HYPE', 'WC-BACKSTAGE-HYPE', 'ACESSO-LOUNGE-BACKSTAGE'
  );
