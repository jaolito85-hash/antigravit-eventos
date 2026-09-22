-- A região deixa de ser rótulo genérico e passa a ser o setor da planta.
--
-- As regiões cadastradas aqui ("VIP & Camarotes", "Estacionamento", "Bistrô")
-- vieram de um evento anterior e não existem no Tropicadelia. Pior: nenhuma
-- delas casa com um setor da planta, então todo chamado classificado por
-- região ficava fora do mapa. O pino só acende por sector_id ou pelo nome
-- exato do setor, e "Banheiros" nunca vai ser "Sanitários Femininos • Palco
-- Tropical".
--
-- O painel passa a montar o filtro de regiões a partir de event_sectors, que
-- é a mesma fonte do Mapa ao Vivo. Uma lista só, a que a planta manda.
--
-- As categorias continuam na config: elas são de fato uma lista curta e
-- editável pela produção, e não têm coordenada no mapa.

delete from public.config c
using public.events e
where c.event_id = e.id
  and c.type = 'region'
  and e.slug = 'tropicadelia-2026';

-- Feedbacks antigos guardam a região velha em texto. Não são apagados: são
-- chamados de teste com histórico, e reescrever o passado esconderia que o
-- roteamento mudou. O que muda daqui para a frente é o que entra.
