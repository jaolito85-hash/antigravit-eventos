-- Índices para o volume do festival (26/09/2026).
--
-- Toda mensagem faz de 6 a 10 consultas "desta pessoa, desde tal hora"
-- (limite de mensagens, cota de áudio, conversa, placa escaneada, chamado
-- aberto). Nenhuma tabela tinha índice por pessoa: com 200 linhas a
-- varredura inteira não pesa, com dezenas de milhares de mensagens pesa em
-- cada uma delas. Os avisos de entrega da Meta (enviada, entregue, lida)
-- procuram a mensagem só pelo ID da Meta, e o índice existente começava
-- pelo provedor.

create index if not exists message_inbox_sender_created_idx
    on public.message_inbox (event_id, sender_hash, created_at desc);

-- Contagem de inundação: mensagens do evento no último minuto.
create index if not exists message_inbox_event_created_idx
    on public.message_inbox (event_id, created_at desc);

-- Conversa do painel e memória do Tuca: o que foi enviado a esta pessoa.
create index if not exists outbound_messages_recipient_created_idx
    on public.outbound_messages (event_id, recipient, created_at desc);

-- Aviso de entrega da Meta: três por mensagem enviada.
create index if not exists outbound_messages_provider_message_idx
    on public.outbound_messages (provider_message_id)
    where provider_message_id is not null;

-- Chamado aberto recente desta pessoa (complemento de incidente, localização).
create index if not exists feedbacks_sender_created_idx
    on public.feedbacks (event_id, sender_hash, created_at desc);

-- Lista do painel e do telão, relida a cada 5 s por tela aberta.
create index if not exists feedbacks_event_updated_idx
    on public.feedbacks (event_id, updated_at desc);
