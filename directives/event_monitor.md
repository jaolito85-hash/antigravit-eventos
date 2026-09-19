# Diretiva: Escuta Ativa do Evento

## Objetivo

Receber mensagens dos frequentadores pelo WhatsApp oficial, responder em segundos,
classificar por urgência e vincular cada relato ao setor físico da planta, para que
a sala de controle veja o festival respirando em tempo real.

## Fluxo real do sistema

```
[Frequentador escaneia o QR do setor]
        │  mensagem ja vem preenchida: #SETOR:WC-FEM-PRINCIPAL
        ▼
[Meta WhatsApp Cloud API]
        │  POST assinado com HMAC-SHA256
        ▼
[server.py /webhook]  valida assinatura, normaliza e persiste em message_inbox
        │  responde 200 na hora, sem processar nada pesado
        ▼
[worker.py]  fila idempotente, um registro por mensagem
        │  1. transcreve audio (Whisper) quando for o caso
        │  2. classifica urgencia, categoria e regiao
        │  3. resolve o setor pelo codigo do QR
        │  4. cria o feedback e enfileira a resposta
        ▼
[outbound_messages] → worker envia pela Graph API e registra a entrega
        │
        ▼
[Dashboard, Mapa ao Vivo e Telão]  atualizam a cada 5 segundos
```

## Contratos que não podem quebrar

**A tag do setor.** A primeira linha da mensagem precisa ser `#SETOR:CODIGO`, com o
código exatamente como está em `event_sectors.code`. É isso que liga o relato ao pin
da planta. Quem gera essa tag é a tela `/qrcode`, nunca a mão.

**O webhook responde rápido.** `/webhook` só valida e grava. Se ele falhar, devolve
503 de propósito, porque a Meta reentrega; devolver 200 perderia a mensagem.

**Nada de PII na tela nem no log.** O telefone é pseudonimizado com HMAC-SHA256
(`PII_HASH_SECRET`) antes de qualquer gravação. As APIs do dashboard passam por
`public_feedback()`, que remove remetente, nome e identificadores.

**A IA é opcional.** Toda chamada de IA tem fallback determinístico. Se a OpenAI
cair, a classificação usa palavras-chave e a resposta usa o texto fixo. Ninguém
fica sem resposta por causa disso.

## Como cada tipo de mensagem é tratado

| Chega | O que o worker faz |
|---|---|
| Só a tag do QR (`#SETOR:X`) | Responde com o nome do setor e o convite cadastrado em `metadata.cta`. Não cria card. |
| Texto com relato | Classifica, cria o feedback, responde com jeito de gente citando o setor. |
| Áudio | Baixa da Graph API em duas etapas, transcreve com Whisper e segue o fluxo de texto. Resposta começa com "Ouvi seu áudio". |
| Foto, vídeo, documento | Pede texto ou áudio. Não cria card. |
| Menos de 3 caracteres ou só emoji | Convida a contar o que aconteceu. Não cria card. |
| Quarta mensagem do mesmo número em 10 min | Pede para aguardar. Limite compartilhado via banco, não memória. |
| Saudação, agradecimento ou despedida, sem conteúdo do evento | A IA marca como `conversa`. O bot responde no tom dele e **não abre chamado**, para a fila de trabalho não encher de "oi, tudo bem". |
| Cumprimento junto com conteúdo, como "bom dia, faltou cerveja" | A IA marca como `relato`. Abre chamado normalmente. |
| Qualquer mensagem, com a conversa assumida por um operador | Registra o chamado normalmente e **não envia nada**. Quem responde é a pessoa, pelo painel. O limite de mensagens também não se aplica. |

## Chamados: uma tela só

Existiu uma aba Atendimento separada, com uma linha por pessoa. Foi removida:
era uma segunda lista das mesmas mensagens e confundia mais do que ajudava.

Tudo vive em **Chamados**, a fila de trabalho. Uma linha por mensagem
recebida, com o número do chamado, a mensagem completa, as atualizações que a
pessoa mandou depois e a resposta que saiu, com o estado de entrega. A equipe
resolve item por item, da maior urgência para a menor.

O que a aba resolvia de verdade virou duas coisas dentro dessa tela:

- O filtro **Só em atendimento humano**, para achar quem está na mão da equipe.
- O selo **equipe atende** no cartão, para ninguém responder por cima de uma
  conversa que outra pessoa já assumiu.

O botão **Conversar com quem enviou**, dentro do chamado, abre a conversa
completa daquela pessoa e é por ali que se assume ou devolve o atendimento.

**Estado de entrega da resposta.** O chamado mostra o que aconteceu com o
texto enviado: na fila, enviada, entregue, lida, falhou ou não entregue. É por
aí que se descobre que o token da Meta venceu, sem precisar abrir log.

## Atendimento humano (handon e handoff)

Todo chamado tem o botão **Conversar**, tanto no dashboard quanto no telão. O
telão não é tela de leitura: pin, KPI,
macrozona, fluxo ao vivo e o próprio alerta crítico abrem o chamado ou a conversa,
e o status pode ser trocado dali. Em qualquer um desses caminhos o operador pode:

- **Assumir atendimento (handon):** a conversa passa para o modo `human`. O
  participante recebe um aviso de que a equipe entrou, e o ChatBob para de
  responder aquela pessoa. O chamado continua entrando no dashboard e no mapa,
  só a resposta automática deixa de sair.
- **Devolver ao ChatBob (handoff):** volta para o modo `bot` e o automático
  reassume na mensagem seguinte.

O estado vive em `conversation_handoff`, uma linha por conversa, identificada
pelo hash HMAC do remetente. O telefone nunca sai do servidor: o painel fala
com a conversa pelo hash e quem resolve o número é o `EventStore` ao enfileirar
o envio.

Dois limites que o painel avisa na tela:

- Conversa sem mensagem recebida pelo WhatsApp não tem número para responder.
  É o caso dos registros de demonstração, que nascem direto em `feedbacks`.
- A Meta só entrega texto livre até 24 horas depois da última mensagem do
  participante. Fora dessa janela o envio pode falhar até a pessoa escrever
  de novo.

## Base de perguntas e respostas

A tela `/chatbob` tem duas metades. Na esquerda, uma caixa de conversa onde a
produção fala com o bot e vê o que ele entendeu, sem gravar nada e sem enviar
mensagem para ninguém. Na direita, a configuração.

**Como o bot usa a base.** O casamento é determinístico de propósito, para o
operador conseguir prever a resposta. Em três níveis, do mais forte ao mais
fraco:

1. Um gatilho cadastrado aparece na mensagem (`que horas` em "que horas abre?").
2. Todas as palavras de um gatilho de duas ou mais palavras aparecem soltas
   (`como pago` em "como eu pago a cerveja").
3. Metade das palavras da própria pergunta aparece na mensagem.

Achada a resposta oficial, ela vai para a IA como informação obrigatória a
transmitir, e a IA escolhe o jeito de dizer. Se a IA estiver fora, o texto
cadastrado vai como está: melhor soar formal que deixar a pergunta sem a
informação certa.

**Elogio não consulta a base.** Sem isso, um "show incrível" voltaria com o
horário do line-up. Crítico também não: ele tem protocolo fixo.

O campo de tom de voz entra em toda resposta gerada pela IA e serve para o
jeito de falar, não para informação. Informação vai nas perguntas e respostas,
que é onde o operador controla o conteúdo.

## Conversa ou relato: quem decide é a IA

A mesma chamada de IA que define a urgência também diz se a mensagem é
`conversa` ou `relato`. Isso é julgamento de linguagem, e lista de palavras em
português não cobre a gíria de festival: "qual foi", "tmj", "eaew mano" e
"cêis tão aí" não estão em lista nenhuma, mas a IA entende.

Duas regras que precisam ficar de pé:

- **Elogio é sempre relato**, nunca conversa, porque conta na satisfação do
  evento e no relatório. "show incrível" abre chamado com urgência Positivo.
- **Na dúvida, relato.** Perder um chamado é pior que ter um card a mais.

Com a OpenAI fora, o tipo sai do vocabulário de cortesia em `_is_greeting` e a
urgência das palavras-chave. É pior, e é de propósito: ninguém fica sem
resposta por causa de uma indisponibilidade.

## Níveis de urgência

- **Critico**: emergência médica, violência, risco de vida. A resposta é sempre o
  protocolo fixo, nunca texto criativo de IA, e orienta procurar a equipe mais
  próxima. No telão, toma a tela inteira com alarme.
- **Urgente**: estrutura quebrada, falta de insumo, fila travada, sujeira grave.
- **Positivo**: elogio.
- **Neutro**: pergunta, dúvida, informação.

## Camadas do sistema

- **Directive** (o que fazer): este arquivo.
- **Orchestration** (decisões): o agente.
- **Execution** (o trabalho): `server.py` recebe, `worker.py` processa,
  `event_store.py` persiste, `meta_whatsapp.py` fala com a Meta.

## Ferramentas de operação

| Precisa | Use |
|---|---|
| Ver se está tudo de pé | `GET /health`, tem que vir 200 com `configuration: ok` |
| Conferir setores e volume no banco | `python execution/seed_demo_tropicadelia.py --status` |
| Encher o telão para um ensaio | `python execution/seed_demo_tropicadelia.py` |
| Limpar só a massa de teste | `python execution/seed_demo_tropicadelia.py --clear` |
| Validar as migrações | `python scripts/validate_migrations.py` |
| Conferir o schema no Supabase | `python scripts/verify_supabase_db.py` |
| Gerar as placas dos setores | Tela `/qrcode` |
| Testar o bot sem celular | Tela `/chatbob`, caixa de conversa |
| Ensinar uma resposta ao bot | Tela `/chatbob`, perguntas e respostas |
| Roteiro de ensaio e diagnóstico | `docs/ENSAIO_SABADO.md` |

## Histórico

A primeira versão deste sistema recebia mensagens pela Evolution API (WhatsApp não
oficial), processava tudo dentro do webhook e guardava em `events.json` local. Essa
camada foi removida em setembro de 2026: hoje o canal é a API oficial da Meta, o
processamento é assíncrono em fila e o estado vive no Supabase com RLS.
