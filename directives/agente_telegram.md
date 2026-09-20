# Diretiva: Agente de Operação no Telegram

## Objetivo

Dar à equipe da Tropicadelia um lugar para perguntar como o festival está, ver
os erros e julgar as respostas do Tuca sem abrir o painel, e ser avisada em
minutos quando algo grave acontece, com a correção a um botão de distância.

## O que ele faz

```
[Equipe no grupo do Telegram]
        │  pergunta em português, ou /comando
        ▼
[telegram_agent.py]  só chats de TELEGRAM_CHAT_IDS
        │  comando  → texto pronto, sem IA
        │  pergunta → IA escolhe leituras do monitor.py e conta o resultado
        ▼
[monitor.py]  lê feedbacks, message_inbox, outbound_messages, /health, Meta, OpenAI
        │
        ├─ a cada MONITOR_INTERVAL_MIN (30): varrer() → alerta novo no grupo
        │       problema com correção no catálogo vem com botão ✅
        │       quem aperta confirma, a correção roda na hora, o alerta registra quem
        │
        └─ a cada MONITOR_VIGIA_SEG (60): chamado crítico novo → 🚨 no grupo
```

Os alertas ficam em `agent_alerts` (migration `20260920120000_agente_alertas.sql`).
Um problema aberto por chave: é assim que o agente sabe que já avisou e não repete
a cada meia hora. Quando o problema some, ele avisa que resolveu e fecha.

## O que a varredura procura

| Chave | Gravidade | Correção no botão |
|---|---|---|
| `app_fora` (health check falhou) | crítico | não: é Coolify ou variável |
| `worker_parado` (mensagens prontas há mais de 3 min sem ninguém pegar) | crítico | não: reiniciar o worker no Coolify |
| `presas_processando` (em `processing` há mais de 10 min, worker caiu no meio) | atenção | devolver para a fila |
| `mensagens_esgotadas` (falharam todas as tentativas nas últimas 24h) | atenção | dar nova chance |
| `fila_acumulada` (30 ou mais pendentes) | atenção | não: acompanhar, subir worker |
| `respostas_nao_entregues` (canceladas nas últimas 24h) | atenção, crítico com 5 ou mais | reenviar só as que a Meta nem aceitou |
| `criticos_sem_atendimento` (crítico aberto há mais de 10 min) | crítico | não: alguém assume no painel |
| `meta_credenciais` (Graph API recusou o token) | crítico | não: token novo no Coolify |
| `ia_fora` (OpenAI não responde) | atenção | não: o Tuca segue nos textos fixos |

Os limites em minutos ficam em `MONITOR_*` no ambiente. O catálogo de correções
é `CORRECOES` em `monitor.py`. Só existe o que está lá, e cada correção é um único
update idempotente no banco.

## Correção de código: o agente da nuvem e o botão de aprovar

O agente do Telegram não escreve código. Quem escreve é o Guardião do Tuca, uma
rotina do Claude Code na nuvem (modelo Opus), com o prompt em
`directives/prompt_agente_nuvem.md`. O caminho inteiro, sem computador ligado:

```
varredura acha problema investigável (app_fora, worker_parado, mensagens_esgotadas,
respostas_nao_entregues, ia_fora)
        │
        ▼
agente do Telegram abre issue no GitHub com a label tuca-alerta
(diagnóstico + últimas falhas, sem dado pessoal) e avisa o grupo
        │
        ▼
a issue dispara a rotina na nuvem (webhook), que também roda de hora em hora
por garantia. Ela investiga, corrige na branch tuca/<chave>-<issue>, roda os
testes e abre o PR com a label tuca-agente. Ou comenta e fecha, se não for código.
        │
        ▼
agente do Telegram vê o PR (vigia a cada minuto) e manda no grupo o resumo
escrito para leigo, com [✅ Aprovar e subir] [❌ Rejeitar]
        │
        ▼
aprovar = squash merge na main, com o nome de quem apertou no commit
        │
        ▼
Coolify reconstrói e reinicia. O agente vigia o /health e avisa
"🟢 Versão nova no ar" quando o started_at muda (ou reclama depois de 20 min).
```

Decisão registrada com o Joao em 20/09/2026: a aprovação humana no Telegram fica.
O agente da nuvem nunca faz merge sozinho. É um toque no celular, e é o que
separa um bug do agente de um festival inteiro sem resposta.

Precisa de `GITHUB_TOKEN` no serviço `agente` (token fine-grained só deste
repositório, com Issues, Pull requests e Contents em leitura e escrita). Sem ele,
o agente do Telegram continua avisando e corrigindo o catálogo, mas não abre issue
nem aprova PR.

## O que ele não faz, de propósito

**Não corrige código sem alguém aprovar.** Nem o Telegram nem a nuvem fazem merge
por conta própria. Se um problema aparecer com frequência e a correção for sempre a
mesma, o caminho é transformá-lo em correção do catálogo, com teste.

**Não mexe no cadastro do bot.** Texto de resposta, regra e tom são da tela Testar
e Configurar, com rascunho e publicação. O agente só lê.

**Não vê dado pessoal.** Nenhuma leitura devolve telefone, nome ou hash do
participante. O grupo do Telegram é uma superfície a mais, e a LGPD vale nela.

## Como colocar no ar

1. No Telegram, fale com o @BotFather: `/newbot`, escolha nome e usuário. Guarde o token.
2. Ainda no BotFather, `/setprivacy` → Disable, para o bot ler perguntas livres no
   grupo. Sem isso ele só recebe comandos e menções.
3. Crie o grupo da equipe e adicione o bot.
4. Preencha `TELEGRAM_BOT_TOKEN` no Coolify e faça o deploy. O serviço `agente` sobe.
5. No grupo, mande `/id`. O bot responde com o id (negativo). Coloque em
   `TELEGRAM_CHAT_IDS` no Coolify e faça deploy de novo.
6. O bot avisa "Agente do Tuca no ar" no grupo. Mande `/saude` para conferir.
7. Para a correção de código: no GitHub, Settings → Developer settings →
   Fine-grained tokens → só o repositório `antigravit-eventos`, permissões
   Issues, Pull requests e Contents em Read and write. Coloque em `GITHUB_TOKEN`
   no Coolify. Mande `/prs` no grupo para conferir.

Sem `TELEGRAM_BOT_TOKEN` o serviço fica parado em silêncio, sem derrubar o resto.

## Comandos

`/resumo [horas]`, `/criticos`, `/chamados [urgencia]`, `/respostas`, `/erros`,
`/saude`, `/verificar`, `/alertas`, `/limpar`, `/id`. Tudo isso funciona sem IA.
Pergunta livre usa `OPENAI_MODEL` com as leituras como ferramentas; se a OpenAI
estiver fora, o agente responde com a lista de comandos.

## Diagnóstico

- O bot não responde no grupo: confira `TELEGRAM_CHAT_IDS` (o id do grupo muda
  quando ele vira supergrupo) e o modo privacidade no BotFather.
- Alerta repetido: a tabela `agent_alerts` não existe ou o service role não
  escreve nela. Sem registro o agente avisa sem botão e sem dedupe.
- `/saude` mostra Meta ⚪: o serviço `agente` está sem `META_ACCESS_TOKEN`.
- Horário errado nas mensagens: falta `tzdata` na imagem; o fallback é UTC-3 fixo.
