-- Migração de setores físicos e pontos de escuta da Planta Tropicadelia 2026.
-- Mapeia cada ponto identificado na planta oficial para roteamento determinístico
-- via QR Code (#SETOR:CODIGO) e posicionamento visual no dashboard.

-- Garante que o evento base 'tropicadelia-2026' existe antes de vincular os setores
insert into public.events (
    slug,
    name,
    venue,
    starts_at,
    ends_at,
    retention_until,
    metadata
)
values (
    'tropicadelia-2026',
    'Tropicadelia 2026',
    'Parque de Exposições Governador Ney Braga, Londrina-PR',
    '2026-09-26 15:30:00-03'::timestamptz,
    '2026-09-27 04:00:00-03'::timestamptz,
    '2026-10-27 04:00:00-03'::timestamptz,
    '{"pilot": true}'::jsonb
)
on conflict (slug) do update
set name = excluded.name,
    venue = excluded.venue,
    updated_at = now();

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
        -- Palcos e Áreas de Show
        (
            'PALCO-PRINCIPAL',
            'Palco Principal • Pista',
            '{"zone": "Sul", "category": "Estrutura & Espaço", "team": "producao_artistica", "priority": "normal", "coord": {"x": 37, "y": 83}, "cta": "Curtiu o show? Dê sua nota para a estrutura e o som."}'
        ),
        (
            'PALCO-PRINCIPAL-PCD',
            'Plataforma PCD • Palco Principal',
            '{"zone": "Sul", "category": "Segurança & Organização", "team": "acessibilidade", "priority": "critico", "coord": {"x": 26, "y": 87}, "cta": "Precisa de apoio ou acessibilidade? Fale direto com a equipe."}'
        ),
        (
            'PALCO-PRINCIPAL-HOUSEMIX',
            'House Mix • Palco Principal',
            '{"zone": "Sul", "category": "Estrutura & Espaço", "team": "engenharia_som", "priority": "normal", "coord": {"x": 32, "y": 84}, "cta": "Qualidade do som ou visão de palco? Relate aqui."}'
        ),
        (
            'PALCO-HYPE',
            'Palco Hype • Arena Coberta',
            '{"zone": "Norte", "category": "Estrutura & Espaço", "team": "producao_artistica", "priority": "normal", "coord": {"x": 64, "y": 28}, "cta": "Espaço, ventilação ou som na Arena? Avise a coordenação."}'
        ),
        (
            'PALCO-HYPE-OPENFOOD',
            'Open Food • Palco Hype',
            '{"zone": "Norte", "category": "Alimentação & Bebidas", "team": "gastronomia_vip", "priority": "urgente", "coord": {"x": 66, "y": 31}, "cta": "Reposição ou fila no Open Food? Avise nossa operação."}'
        ),
        (
            'PALCO-3',
            'Palco 3 • Oeste',
            '{"zone": "Oeste", "category": "Estrutura & Espaço", "team": "producao_artistica", "priority": "normal", "coord": {"x": 10, "y": 44}, "cta": "Como está sua experiência no Palco 3? Avalie agora."}'
        ),

        -- Sanitários (Baterias de WC)
        (
            'WC-FEM-PRINCIPAL',
            'Sanitários Femininos • Palco Principal',
            '{"zone": "Sul", "category": "Estrutura & Espaço", "team": "limpeza_higienizacao", "priority": "urgente", "coord": {"x": 51, "y": 80}, "cta": "Falta papel, sabonete ou fila travada? Avise nossa equipe."}'
        ),
        (
            'WC-MASC-CENTRAL',
            'Sanitários Masculinos • Central',
            '{"zone": "Centro", "category": "Estrutura & Espaço", "team": "limpeza_higienizacao", "priority": "urgente", "coord": {"x": 40, "y": 52}, "cta": "Manutenção ou limpeza necessária? Relate em 1 toque."}'
        ),
        (
            'WC-PISTA-NORTE',
            'Sanitários Pista • Arena Hype',
            '{"zone": "Norte", "category": "Estrutura & Espaço", "team": "limpeza_higienizacao", "priority": "urgente", "coord": {"x": 46, "y": 26}, "cta": "Limpeza necessária no WC Arena? Acione o ChatBob."}'
        ),
        (
            'WC-PALCO-3',
            'Sanitários • Palco 3 / Feirinha',
            '{"zone": "Oeste", "category": "Estrutura & Espaço", "team": "limpeza_higienizacao", "priority": "urgente", "coord": {"x": 35, "y": 48}, "cta": "Banheiro precisando de apoio? Avise a equipe volante."}'
        ),

        -- Bares e Alimentação
        (
            'PRACA-ALIMENTACAO',
            'Praça de Alimentação • Gramado Central',
            '{"zone": "Centro", "category": "Alimentação & Bebidas", "team": "operacao_praca", "priority": "normal", "coord": {"x": 23, "y": 57}, "cta": "Mesas cheias, fila ou falta de opções? Conta pra gente."}'
        ),
        (
            'ALAMEDA-FOODTRUCKS',
            'Alameda Gastronômica • Burger, Pizza e Salgados',
            '{"zone": "Leste", "category": "Alimentação & Bebidas", "team": "operacao_praca", "priority": "normal", "coord": {"x": 58, "y": 44}, "cta": "Atendimento e qualidade dos alimentos? Deixe seu feedback."}'
        ),
        (
            'BAR-CELEIRO-P1',
            'Bar Celeiro • Principal',
            '{"zone": "Centro", "category": "Alimentação & Bebidas", "team": "bar_insumos", "priority": "urgente", "coord": {"x": 47, "y": 64}, "cta": "Falta produto, gelo ou fila parada? Avise o suporte do bar."}'
        ),
        (
            'BAR-CELEIRO-P2',
            'Bar Celeiro • Ponto 2',
            '{"zone": "Centro", "category": "Alimentação & Bebidas", "team": "bar_insumos", "priority": "urgente", "coord": {"x": 49, "y": 66}, "cta": "Fila travada ou reposição de fichas? Acione o CCO."}'
        ),
        (
            'DESTILADOS-P1',
            'Bar Destilados • Ala 1',
            '{"zone": "Centro", "category": "Alimentação & Bebidas", "team": "bar_insumos", "priority": "urgente", "coord": {"x": 37, "y": 62}, "cta": "Falta insumo de drink? Avise para reposição imediata."}'
        ),
        (
            'DESTILADOS-P2',
            'Bar Destilados • Ala 2',
            '{"zone": "Centro", "category": "Alimentação & Bebidas", "team": "bar_insumos", "priority": "urgente", "coord": {"x": 41, "y": 64}, "cta": "Fila ou lentidão no balcão de destilados? Avise a operação."}'
        ),
        (
            'BAR-05-PALCO-3',
            'Bar 05 • Palco 3',
            '{"zone": "Oeste", "category": "Alimentação & Bebidas", "team": "bar_insumos", "priority": "urgente", "coord": {"x": 19, "y": 44}, "cta": "Atendimento Bar 05 travou? Avise a coordenação de bebidas."}'
        ),
        (
            'BAR-06-PALCO-HYPE',
            'Bar 06 • Palco Hype',
            '{"zone": "Norte", "category": "Alimentação & Bebidas", "team": "bar_insumos", "priority": "urgente", "coord": {"x": 58, "y": 33}, "cta": "Fila ou falta de produto no Bar 06? Fale com o ChatBob."}'
        ),

        -- Serviços, Conveniência e Segurança
        (
            'CCO-ACHADOS-PERDIDOS',
            'CCO • Central de Controle & Achados e Perdidos',
            '{"zone": "Centro", "category": "Segurança & Organização", "team": "seguranca_patrimonial", "priority": "urgente", "coord": {"x": 28, "y": 48}, "cta": "Perdeu ou encontrou um objeto? Registre aqui."}'
        ),
        (
            'LOCKERS-CENTRAL',
            'Guarda-Volumes • Lockers Centrais',
            '{"zone": "Centro", "category": "Estrutura & Espaço", "team": "atendimento_lockers", "priority": "normal", "coord": {"x": 56, "y": 56}, "cta": "Dúvidas sobre o armário ou cadeado? Peça ajuda aqui."}'
        ),
        (
            'DESCANSO-BAMBOO',
            'Lounge Bamboo Pallet • Área de Descanso',
            '{"zone": "Sul", "category": "Experiência Geral", "team": "bem_estar", "priority": "normal", "coord": {"x": 37, "y": 94}, "cta": "Descansando? Veja a programação dos próximos palcos!"}'
        ),
        (
            'FEIRINHA-TATTOO',
            'Espaço Feirinha & Estúdio Tattoo',
            '{"zone": "Oeste", "category": "Experiência Geral", "team": "experiencia_marcas", "priority": "normal", "coord": {"x": 30, "y": 51}, "cta": "Curtiu a feira e a tattoo? Dê sua nota para a experiência."}'
        ),

        -- Acessos e Portarias
        (
            'ACESSO-CREDENCIAMENTO',
            'Portaria Principal • Credenciamento',
            '{"zone": "Leste", "category": "Credenciamento & Ingressos", "team": "portaria_ingressos", "priority": "urgente", "coord": {"x": 95, "y": 54}, "cta": "Dificuldade na validação do ingresso ou fila? Chame o ChatBob."}'
        ),
        (
            'ACESSO-EXCURSOES',
            'Entrada de Excursões • Desembarque',
            '{"zone": "Leste", "category": "Credenciamento & Ingressos", "team": "portaria_ingressos", "priority": "urgente", "coord": {"x": 86, "y": 48}, "cta": "Chegando de excursão? Tire dúvidas sobre o acesso."}'
        ),
        (
            'ACESSO-LOUNGE-BACKSTAGE',
            'Acesso Exclusivo • Lounge & Backstage',
            '{"zone": "Leste", "category": "Credenciamento & Ingressos", "team": "portaria_vip", "priority": "urgente", "coord": {"x": 80, "y": 31}, "cta": "Acesso VIP ou Backstage com lentidão? Avise a recepção."}'
        ),
        (
            'ACESSO-PCD',
            'Portão de Acesso Exclusivo • PCD',
            '{"zone": "Oeste", "category": "Segurança & Organização", "team": "acessibilidade", "priority": "critico", "coord": {"x": 9, "y": 63}, "cta": "Chegando com necessidade especial? Solicite recepção assistida."}'
        )
) as v(code, name, metadata)
where e.slug = 'tropicadelia-2026'
on conflict (event_id, code) do update
set name = excluded.name,
    active = true,
    metadata = excluded.metadata,
    updated_at = now();
