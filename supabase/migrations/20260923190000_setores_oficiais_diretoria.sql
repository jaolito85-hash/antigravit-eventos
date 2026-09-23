-- Setores oficiais da Tropicadelia 2026, lista da diretoria de 23/09/2026.
-- Gerado por scripts/calibrar_planta.py em 23/09/2026.
--
-- As coordenadas são porcentagem sobre a arte oficial
-- (static/planta-tropicadelia-oficial.jpg) e foram marcadas clicando uma a
-- uma sobre a imagem, não estimadas.
--
-- ATENÇÃO: 2 setor(es) ainda sem posição na planta. Eles entram
-- no banco e recebem chamado pelo QR, mas não acendem pino no mapa:
--   DESCANSO-TROPICAL-PISTA
--   DESCANSO-NY-TROPICAL-PISTA

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
        (
            'WC-FEM-HYPE-PISTA',
            'Sanitários Femininos Hype • Pista',
            '{"zone": "Pista", "group": "Sanitários", "team": "limpeza_higienizacao", "cta": "Falta papel, sabonete ou a fila travou? Avise a equipe.", "priority": "normal", "coord": {"x": 45.7, "y": 23.9}}'
        ),
        (
            'WC-MASC-HYPE-PISTA',
            'Sanitários Masculinos Hype • Pista',
            '{"zone": "Pista", "group": "Sanitários", "team": "limpeza_higienizacao", "cta": "Falta papel, sabonete ou a fila travou? Avise a equipe.", "priority": "normal", "coord": {"x": 47.3, "y": 18.6}}'
        ),
        (
            'WC-FEM-HYPE-LOUNGE',
            'Sanitários Femininos Hype • Tropical Lounge',
            '{"zone": "Tropical Lounge", "group": "Sanitários", "team": "limpeza_higienizacao", "cta": "Falta papel, sabonete ou a fila travou? Avise a equipe.", "priority": "normal", "coord": {"x": 68.2, "y": 16.7}}'
        ),
        (
            'WC-MASC-HYPE-LOUNGE',
            'Sanitários Masculinos Hype • Tropical Lounge',
            '{"zone": "Tropical Lounge", "group": "Sanitários", "team": "limpeza_higienizacao", "cta": "Falta papel, sabonete ou a fila travou? Avise a equipe.", "priority": "normal", "coord": {"x": 66.9, "y": 15.6}}'
        ),
        (
            'WC-FEM-HYPE-BACKSTAGE',
            'Sanitários Femininos Hype • Backstage Hype',
            '{"zone": "Backstage Hype", "group": "Sanitários", "team": "limpeza_higienizacao", "cta": "Falta papel, sabonete ou a fila travou? Avise a equipe.", "priority": "normal", "coord": {"x": 56.6, "y": 33.0}}'
        ),
        (
            'WC-MASC-HYPE-BACKSTAGE',
            'Sanitários Masculinos Hype • Backstage Hype',
            '{"zone": "Backstage Hype", "group": "Sanitários", "team": "limpeza_higienizacao", "cta": "Falta papel, sabonete ou a fila travou? Avise a equipe.", "priority": "normal", "coord": {"x": 58.1, "y": 33.6}}'
        ),
        (
            'WC-FEM-TROPICAL-PISTA',
            'Sanitários Femininos Tropical • Pista',
            '{"zone": "Pista", "group": "Sanitários", "team": "limpeza_higienizacao", "cta": "Falta papel, sabonete ou a fila travou? Avise a equipe.", "priority": "normal", "coord": {"x": 17.6, "y": 63.2}}'
        ),
        (
            'WC-MASC-TROPICAL-PISTA',
            'Sanitários Masculinos Tropical • Pista',
            '{"zone": "Pista", "group": "Sanitários", "team": "limpeza_higienizacao", "cta": "Falta papel, sabonete ou a fila travou? Avise a equipe.", "priority": "normal", "coord": {"x": 17.1, "y": 70.0}}'
        ),
        (
            'WC-FEM-TROPICAL-LOUNGE',
            'Sanitários Femininos Tropical • Tropical Lounge',
            '{"zone": "Tropical Lounge", "group": "Sanitários", "team": "limpeza_higienizacao", "cta": "Falta papel, sabonete ou a fila travou? Avise a equipe.", "priority": "normal", "coord": {"x": 51.8, "y": 76.5}}'
        ),
        (
            'WC-MASC-TROPICAL-LOUNGE',
            'Sanitários Masculinos Tropical • Tropical Lounge',
            '{"zone": "Tropical Lounge", "group": "Sanitários", "team": "limpeza_higienizacao", "cta": "Falta papel, sabonete ou a fila travou? Avise a equipe.", "priority": "normal", "coord": {"x": 45.7, "y": 70.5}}'
        ),
        (
            'WC-FEM-FEIRINHA-PISTA',
            'Sanitários Femininos Feirinha • Pista',
            '{"zone": "Pista", "group": "Sanitários", "team": "limpeza_higienizacao", "cta": "Falta papel, sabonete ou a fila travou? Avise a equipe.", "priority": "normal", "coord": {"x": 33.1, "y": 40.2}}'
        ),
        (
            'WC-MASC-FEIRINHA-PISTA',
            'Sanitários Masculinos Feirinha • Pista',
            '{"zone": "Pista", "group": "Sanitários", "team": "limpeza_higienizacao", "cta": "Falta papel, sabonete ou a fila travou? Avise a equipe.", "priority": "normal", "coord": {"x": 31.1, "y": 39.3}}'
        ),
        (
            'WC-FEM-OPENFOOD-LOUNGE',
            'Sanitários Femininos Open Food • Tropical Lounge',
            '{"zone": "Tropical Lounge", "group": "Sanitários", "team": "limpeza_higienizacao", "cta": "Falta papel, sabonete ou a fila travou? Avise a equipe.", "priority": "normal", "coord": {"x": 41.5, "y": 43.1}}'
        ),
        (
            'WC-MASC-OPENFOOD-LOUNGE',
            'Sanitários Masculinos Open Food • Tropical Lounge',
            '{"zone": "Tropical Lounge", "group": "Sanitários", "team": "limpeza_higienizacao", "cta": "Falta papel, sabonete ou a fila travou? Avise a equipe.", "priority": "normal", "coord": {"x": 39.2, "y": 46.0}}'
        ),
        (
            'BAR-HYPE-PISTA',
            'Bar Hype • Pista',
            '{"zone": "Pista", "group": "Bares", "team": "bar_insumos", "cta": "Acabou o gelo, a bebida ou a fila travou? Avise na hora.", "priority": "normal", "coord": {"x": 55.6, "y": 26.3}}'
        ),
        (
            'BAR-HYPE-LOUNGE',
            'Bar Hype • Tropical Lounge',
            '{"zone": "Tropical Lounge", "group": "Bares", "team": "bar_insumos", "cta": "Acabou o gelo, a bebida ou a fila travou? Avise na hora.", "priority": "normal", "coord": {"x": 59.3, "y": 15.5}}'
        ),
        (
            'BAR-COCOLEVE-HYPE-LOUNGE',
            'Bar Coco Leve Hype • Tropical Lounge',
            '{"zone": "Tropical Lounge", "group": "Bares", "team": "bar_insumos", "cta": "Acabou o gelo, a bebida ou a fila travou? Avise na hora.", "priority": "normal", "coord": {"x": 55.7, "y": 13.2}}'
        ),
        (
            'BAR-REDBULL-HYPE-LOUNGE',
            'Bar Red Bull Hype • Tropical Lounge',
            '{"zone": "Tropical Lounge", "group": "Bares", "team": "bar_insumos", "cta": "Acabou o gelo, a bebida ou a fila travou? Avise na hora.", "priority": "normal", "coord": {"x": 37.4, "y": 67.7}}'
        ),
        (
            'BAR-HYPE-BACKSTAGE',
            'Bar Hype • Backstage Hype',
            '{"zone": "Backstage Hype", "group": "Bares", "team": "bar_insumos", "cta": "Acabou o gelo, a bebida ou a fila travou? Avise na hora.", "priority": "normal", "coord": {"x": 66.1, "y": 21.2}}'
        ),
        (
            'BAR-COCOLEVE-HYPE-BACKSTAGE',
            'Bar Coco Leve Hype • Backstage Hype',
            '{"zone": "Backstage Hype", "group": "Bares", "team": "bar_insumos", "cta": "Acabou o gelo, a bebida ou a fila travou? Avise na hora.", "priority": "normal", "coord": {"x": 65.9, "y": 19.2}}'
        ),
        (
            'BAR-REDBULL-HYPE-BACKSTAGE',
            'Bar Red Bull Hype • Backstage Hype',
            '{"zone": "Backstage Hype", "group": "Bares", "team": "bar_insumos", "cta": "Acabou o gelo, a bebida ou a fila travou? Avise na hora.", "priority": "normal", "coord": {"x": 66.6, "y": 19.4}}'
        ),
        (
            'BAR-LAB-PISTA',
            'Bar LAB • Pista',
            '{"zone": "Pista", "group": "Bares", "team": "bar_insumos", "cta": "Acabou o gelo, a bebida ou a fila travou? Avise na hora.", "priority": "normal", "coord": {"x": 20.8, "y": 37.6}}'
        ),
        (
            'BAR-REDBULL-LAB-PISTA',
            'Bar Red Bull LAB • Pista',
            '{"zone": "Pista", "group": "Bares", "team": "bar_insumos", "cta": "Acabou o gelo, a bebida ou a fila travou? Avise na hora.", "priority": "normal", "coord": {"x": 18.6, "y": 36.6}}'
        ),
        (
            'BAR-TROPICAL-PISTA-01',
            'Bar Tropical 01 • Pista',
            '{"zone": "Pista", "group": "Bares", "team": "bar_insumos", "cta": "Acabou o gelo, a bebida ou a fila travou? Avise na hora.", "priority": "normal", "coord": {"x": 29.2, "y": 64.9}}'
        ),
        (
            'BAR-TROPICAL-PISTA-02',
            'Bar Tropical 02 • Pista',
            '{"zone": "Pista", "group": "Bares", "team": "bar_insumos", "cta": "Acabou o gelo, a bebida ou a fila travou? Avise na hora.", "priority": "normal", "coord": {"x": 24.2, "y": 75.3}}'
        ),
        (
            'BAR-TROPICAL-PISTA-03',
            'Bar Tropical 03 • Pista',
            '{"zone": "Pista", "group": "Bares", "team": "bar_insumos", "cta": "Acabou o gelo, a bebida ou a fila travou? Avise na hora.", "priority": "normal", "coord": {"x": 26.8, "y": 92.3}}'
        ),
        (
            'BAR-BUD-TROPICAL-PISTA',
            'Bar Budweiser Tropical • Pista',
            '{"zone": "Pista", "group": "Bares", "team": "bar_insumos", "cta": "Acabou o gelo, a bebida ou a fila travou? Avise na hora.", "priority": "normal", "coord": {"x": 27.5, "y": 72.4}}'
        ),
        (
            'BAR-REDBULL-TROPICAL-PISTA',
            'Bar Red Bull Tropical • Pista',
            '{"zone": "Pista", "group": "Bares", "team": "bar_insumos", "cta": "Acabou o gelo, a bebida ou a fila travou? Avise na hora.", "priority": "normal", "coord": {"x": 25.1, "y": 63.1}}'
        ),
        (
            'BAR-DRINK-TROPICAL-LOUNGE-01',
            'Bar Drinks Tropical 01 • Tropical Lounge',
            '{"zone": "Tropical Lounge", "group": "Bares", "team": "bar_insumos", "cta": "Acabou o gelo, a bebida ou a fila travou? Avise na hora.", "priority": "normal", "coord": {"x": 38.3, "y": 57.2}}'
        ),
        (
            'BAR-DRINK-TROPICAL-LOUNGE-02',
            'Bar Drinks Tropical 02 • Tropical Lounge',
            '{"zone": "Tropical Lounge", "group": "Bares", "team": "bar_insumos", "cta": "Acabou o gelo, a bebida ou a fila travou? Avise na hora.", "priority": "normal", "coord": {"x": 43.2, "y": 58.8}}'
        ),
        (
            'BAR-BUD-TROPICAL-LOUNGE',
            'Bar Budweiser Tropical • Tropical Lounge',
            '{"zone": "Tropical Lounge", "group": "Bares", "team": "bar_insumos", "cta": "Acabou o gelo, a bebida ou a fila travou? Avise na hora.", "priority": "normal", "coord": {"x": 47.0, "y": 62.9}}'
        ),
        (
            'BAR-GERAL-TROPICAL-LOUNGE',
            'Bar Geral Tropical • Tropical Lounge',
            '{"zone": "Tropical Lounge", "group": "Bares", "team": "bar_insumos", "cta": "Acabou o gelo, a bebida ou a fila travou? Avise na hora.", "priority": "normal", "coord": {"x": 35.8, "y": 92.5}}'
        ),
        (
            'OPENFOOD-HYPE-LOUNGE',
            'Open Food Hype • Tropical Lounge',
            '{"zone": "Tropical Lounge", "group": "Alimentação", "team": "gastronomia_lounge", "cta": "Demora, prato frio ou item em falta? Conte para a gente.", "priority": "normal", "coord": {"x": 69.8, "y": 25.7}}'
        ),
        (
            'OPENFOOD-HYPE-BACKSTAGE',
            'Open Food Hype • Backstage Hype',
            '{"zone": "Backstage Hype", "group": "Alimentação", "team": "gastronomia_lounge", "cta": "Demora, prato frio ou item em falta? Conte para a gente.", "priority": "normal", "coord": {"x": 62.9, "y": 29.2}}'
        ),
        (
            'OPENFOOD-TROPICAL-LOUNGE-01',
            'Open Food Tropical 01 • Tropical Lounge',
            '{"zone": "Tropical Lounge", "group": "Alimentação", "team": "gastronomia_lounge", "cta": "Demora, prato frio ou item em falta? Conte para a gente.", "priority": "normal", "coord": {"x": 47.0, "y": 40.1}}'
        ),
        (
            'OPENFOOD-TROPICAL-LOUNGE-02',
            'Open Food Tropical 02 • Tropical Lounge',
            '{"zone": "Tropical Lounge", "group": "Alimentação", "team": "gastronomia_lounge", "cta": "Demora, prato frio ou item em falta? Conte para a gente.", "priority": "normal", "coord": {"x": 56.5, "y": 42.6}}'
        ),
        (
            'PRACA-CENTRAL-PISTA',
            'Praça de Alimentação Central • Pista',
            '{"zone": "Pista", "group": "Alimentação", "team": "operacao_praca", "cta": "Demora, preço ou comida fria? Queremos saber agora.", "priority": "normal", "coord": {"x": 22.9, "y": 49.6}}'
        ),
        (
            'PRACA-LAB-PISTA',
            'Praça de Alimentação LAB • Pista',
            '{"zone": "Pista", "group": "Alimentação", "team": "operacao_praca", "cta": "Demora, preço ou comida fria? Queremos saber agora.", "priority": "normal", "coord": {"x": 10.9, "y": 46.8}}'
        ),
        (
            'AMB-CENTRAL-PISTA',
            'Ambulatório Central • Pista',
            '{"zone": "Pista", "group": "Saúde", "team": "saude_emergencia", "cta": "Emergência de saúde? Fale agora que acionamos a equipe.", "priority": "normal", "coord": {"x": 15.8, "y": 57.4}}'
        ),
        (
            'AMB-TROPICAL-LOUNGE',
            'Ambulatório Tropical • Tropical Lounge',
            '{"zone": "Tropical Lounge", "group": "Saúde", "team": "saude_emergencia", "cta": "Emergência de saúde? Fale agora que acionamos a equipe.", "priority": "normal", "coord": {"x": 53.1, "y": 46.0}}'
        ),
        (
            'CAIXA-HYPE-PISTA',
            'Caixa Hype • Pista',
            '{"zone": "Pista", "group": "Caixas", "team": "operacao_caixas", "cta": "Fila no caixa ou problema no pagamento? Avise aqui.", "priority": "normal", "coord": {"x": 54.3, "y": 25.7}}'
        ),
        (
            'CAIXA-LAB-PISTA',
            'Caixa LAB • Pista',
            '{"zone": "Pista", "group": "Caixas", "team": "operacao_caixas", "cta": "Fila no caixa ou problema no pagamento? Avise aqui.", "priority": "normal", "coord": {"x": 18.7, "y": 42.8}}'
        ),
        (
            'CAIXA-TROPICAL-PISTA',
            'Caixa Tropical • Pista',
            '{"zone": "Pista", "group": "Caixas", "team": "operacao_caixas", "cta": "Fila no caixa ou problema no pagamento? Avise aqui.", "priority": "normal", "coord": {"x": 27.1, "y": 64.7}}'
        ),
        (
            'CAIXA-PRACA-CENTRAL-PISTA',
            'Caixa Praça Central • Pista',
            '{"zone": "Pista", "group": "Caixas", "team": "operacao_caixas", "cta": "Fila no caixa ou problema no pagamento? Avise aqui.", "priority": "normal", "coord": {"x": 22.9, "y": 50.4}}'
        ),
        (
            'CAIXA-PRACA-LAB-PISTA',
            'Caixa Praça LAB • Pista',
            '{"zone": "Pista", "group": "Caixas", "team": "operacao_caixas", "cta": "Fila no caixa ou problema no pagamento? Avise aqui.", "priority": "normal", "coord": {"x": 10.7, "y": 48.1}}'
        ),
        (
            'LED-TROPICAL',
            'Telão Tropical',
            '{"group": "Telões", "team": "producao_artistica", "cta": "Imagem travada, som ou telão apagado? Avise a produção.", "priority": "normal", "coord": {"x": 36.4, "y": 78.1}}'
        ),
        (
            'LED-HYPE',
            'Telão Hype',
            '{"group": "Telões", "team": "producao_artistica", "cta": "Imagem travada, som ou telão apagado? Avise a produção.", "priority": "normal", "coord": {"x": 60.4, "y": 22.2}}'
        ),
        (
            'LED-LAB',
            'Telão LAB',
            '{"group": "Telões", "team": "producao_artistica", "cta": "Imagem travada, som ou telão apagado? Avise a produção.", "priority": "normal", "coord": {"x": 9.6, "y": 38.8}}'
        ),
        (
            'LED-NY-LOUNGE',
            'Telão NY Lounge • Tropical Lounge',
            '{"zone": "Tropical Lounge", "group": "Telões", "team": "producao_artistica", "cta": "Imagem travada, som ou telão apagado? Avise a produção.", "priority": "normal", "coord": {"x": 22.7, "y": 70.6}}'
        ),
        (
            'LED-JOHN-ROGER',
            'Telão John Roger',
            '{"group": "Telões", "team": "producao_artistica", "cta": "Imagem travada, som ou telão apagado? Avise a produção.", "priority": "normal", "coord": {"x": 24.6, "y": 57.6}}'
        ),
        (
            'LED-DESCANSO',
            'Telão',
            '{"group": "Telões", "team": "producao_artistica", "cta": "Imagem travada, som ou telão apagado? Avise a produção.", "priority": "normal", "coord": {"x": 24.2, "y": 86.6}}'
        ),
        (
            'AVANCO-CENTRAL-PISTA',
            'Avanço de Pulseira Central • Pista',
            '{"zone": "Pista", "group": "Atendimento ao Público", "team": "sac_atendimento", "cta": "Quer trocar ou fazer upgrade da pulseira? Fale com a gente.", "priority": "normal", "coord": {"x": 33.9, "y": 45.1}}'
        ),
        (
            'PCD-CENTRAL-PISTA',
            'Apoio PCD Central • Pista',
            '{"zone": "Pista", "group": "Acessibilidade", "team": "acessibilidade", "cta": "Precisa de apoio ou acessibilidade? Fale direto com a equipe.", "priority": "normal", "coord": {"x": 18.3, "y": 56.4}}'
        ),
        (
            'FEIRINHA-CENTRAL-PISTA',
            'Feirinha Central • Pista',
            '{"zone": "Pista", "group": "Lojas e Feirinha", "team": "experiencia_marcas", "cta": "Como está a experiência na feirinha? Conte para a gente.", "priority": "normal", "coord": {"x": 26.7, "y": 45.4}}'
        ),
        (
            'LOCKER-CENTRAL-PISTA',
            'Lockers Central • Pista',
            '{"zone": "Pista", "group": "Atendimento ao Público", "team": "atendimento_lockers", "cta": "Dúvida de disponibilidade ou problema no locker? Fale aqui.", "priority": "normal", "coord": {"x": 28.8, "y": 36.1}}'
        ),
        (
            'LOCKER-CENTRAL-LOUNGE',
            'Lockers Central • Tropical Lounge',
            '{"zone": "Tropical Lounge", "group": "Atendimento ao Público", "team": "atendimento_lockers", "cta": "Dúvida de disponibilidade ou problema no locker? Fale aqui.", "priority": "normal", "coord": {"x": 55.0, "y": 49.7}}'
        ),
        (
            'GARRA-TROPICAL-PISTA',
            'Garra Tropical • Pista',
            '{"zone": "Pista", "group": "Ativações e Lazer", "team": "experiencia_marcas", "cta": "Fila grande ou tudo tranquilo na ativação? Avise aqui.", "priority": "normal", "coord": {"x": 21.4, "y": 63.9}}'
        ),
        (
            'DESCANSO-TROPICAL-PISTA',
            'Área de Descanso Tropical • Pista',
            '{"zone": "Pista", "group": "Ativações e Lazer", "team": "bem_estar", "cta": "Precisa de um lugar para sentar ou de água? Fale com a gente.", "priority": "normal"}'
        ),
        (
            'DESCANSO-NY-TROPICAL-PISTA',
            'Área de Descanso NY Lounge Tropical • Pista',
            '{"zone": "Pista", "group": "Ativações e Lazer", "team": "bem_estar", "cta": "Precisa de um lugar para sentar ou de água? Fale com a gente.", "priority": "normal"}'
        ),
        (
            'DESCANSO-TROPICAL-LOUNGE',
            'Área de Descanso Tropical • Tropical Lounge',
            '{"zone": "Tropical Lounge", "group": "Ativações e Lazer", "team": "bem_estar", "cta": "Precisa de um lugar para sentar ou de água? Fale com a gente.", "priority": "normal", "coord": {"x": 40.0, "y": 67.4}}'
        ),
        (
            'DESCANSO-DELEGA-HYPE-BACKSTAGE',
            'Área de Descanso Delegacia Hype • Backstage Hype',
            '{"zone": "Backstage Hype", "group": "Ativações e Lazer", "team": "bem_estar", "cta": "Precisa de um lugar para sentar ou de água? Fale com a gente.", "priority": "normal", "coord": {"x": 63.5, "y": 24.1}}'
        ),
        (
            'ACESSO-OPENFOOD-LOUNGE',
            'Acesso Open Food • Tropical Lounge',
            '{"zone": "Tropical Lounge", "group": "Entradas e Acessos", "team": "portaria_ingressos", "cta": "Fila na catraca ou problema com a pulseira? Avise aqui.", "priority": "normal", "coord": {"x": 42.1, "y": 40.1}}'
        ),
        (
            'ACESSO-CENTRAL-LOUNGE',
            'Acesso Central • Tropical Lounge',
            '{"zone": "Tropical Lounge", "group": "Entradas e Acessos", "team": "portaria_ingressos", "cta": "Fila na catraca ou problema com a pulseira? Avise aqui.", "priority": "normal", "coord": {"x": 36.5, "y": 50.4}}'
        ),
        (
            'ACESSO-LOJINHA-LOUNGE',
            'Acesso Lojinha • Tropical Lounge',
            '{"zone": "Tropical Lounge", "group": "Entradas e Acessos", "team": "portaria_ingressos", "cta": "Fila na catraca ou problema com a pulseira? Avise aqui.", "priority": "normal", "coord": {"x": 30.3, "y": 61.9}}'
        ),
        (
            'ACESSO-HYPE-BACKSTAGE',
            'Acesso Hype • Backstage Hype',
            '{"zone": "Backstage Hype", "group": "Entradas e Acessos", "team": "portaria_vip", "cta": "Fila na catraca ou problema com a pulseira? Avise aqui.", "priority": "normal", "coord": {"x": 62.6, "y": 34.3}}'
        )
) as v(code, name, metadata)
where e.slug = 'tropicadelia-2026'
on conflict (event_id, code) do update
set name = excluded.name,
    metadata = excluded.metadata,
    active = true,
    updated_at = now();

-- Os setores da planta anterior saem do mapa sem serem apagados: chamado de
-- teste aponta para esses códigos e apagar quebraria o histórico.
update public.event_sectors s
set active = false,
    updated_at = now()
from public.events e
where s.event_id = e.id
  and e.slug = 'tropicadelia-2026'
  and s.code not in ('WC-FEM-HYPE-PISTA', 'WC-MASC-HYPE-PISTA', 'WC-FEM-HYPE-LOUNGE', 'WC-MASC-HYPE-LOUNGE', 'WC-FEM-HYPE-BACKSTAGE', 'WC-MASC-HYPE-BACKSTAGE', 'WC-FEM-TROPICAL-PISTA', 'WC-MASC-TROPICAL-PISTA', 'WC-FEM-TROPICAL-LOUNGE', 'WC-MASC-TROPICAL-LOUNGE', 'WC-FEM-FEIRINHA-PISTA', 'WC-MASC-FEIRINHA-PISTA', 'WC-FEM-OPENFOOD-LOUNGE', 'WC-MASC-OPENFOOD-LOUNGE', 'BAR-HYPE-PISTA', 'BAR-HYPE-LOUNGE', 'BAR-COCOLEVE-HYPE-LOUNGE', 'BAR-REDBULL-HYPE-LOUNGE', 'BAR-HYPE-BACKSTAGE', 'BAR-COCOLEVE-HYPE-BACKSTAGE', 'BAR-REDBULL-HYPE-BACKSTAGE', 'BAR-LAB-PISTA', 'BAR-REDBULL-LAB-PISTA', 'BAR-TROPICAL-PISTA-01', 'BAR-TROPICAL-PISTA-02', 'BAR-TROPICAL-PISTA-03', 'BAR-BUD-TROPICAL-PISTA', 'BAR-REDBULL-TROPICAL-PISTA', 'BAR-DRINK-TROPICAL-LOUNGE-01', 'BAR-DRINK-TROPICAL-LOUNGE-02', 'BAR-BUD-TROPICAL-LOUNGE', 'BAR-GERAL-TROPICAL-LOUNGE', 'OPENFOOD-HYPE-LOUNGE', 'OPENFOOD-HYPE-BACKSTAGE', 'OPENFOOD-TROPICAL-LOUNGE-01', 'OPENFOOD-TROPICAL-LOUNGE-02', 'PRACA-CENTRAL-PISTA', 'PRACA-LAB-PISTA', 'AMB-CENTRAL-PISTA', 'AMB-TROPICAL-LOUNGE', 'CAIXA-HYPE-PISTA', 'CAIXA-LAB-PISTA', 'CAIXA-TROPICAL-PISTA', 'CAIXA-PRACA-CENTRAL-PISTA', 'CAIXA-PRACA-LAB-PISTA', 'LED-TROPICAL', 'LED-HYPE', 'LED-LAB', 'LED-NY-LOUNGE', 'LED-JOHN-ROGER', 'LED-DESCANSO', 'AVANCO-CENTRAL-PISTA', 'PCD-CENTRAL-PISTA', 'FEIRINHA-CENTRAL-PISTA', 'LOCKER-CENTRAL-PISTA', 'LOCKER-CENTRAL-LOUNGE', 'GARRA-TROPICAL-PISTA', 'DESCANSO-TROPICAL-PISTA', 'DESCANSO-NY-TROPICAL-PISTA', 'DESCANSO-TROPICAL-LOUNGE', 'DESCANSO-DELEGA-HYPE-BACKSTAGE', 'ACESSO-OPENFOOD-LOUNGE', 'ACESSO-CENTRAL-LOUNGE', 'ACESSO-LOJINHA-LOUNGE', 'ACESSO-HYPE-BACKSTAGE');
