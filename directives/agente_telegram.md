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

## O que ele não faz, de propósito

**Não muda código em produção.** Uma correção de código pedida e aplicada de dentro
do Telegram sairia sem teste, sem revisão e sem deploy controlado, no meio do
festival. O agente diagnostica e diz o que precisa mudar; a mudança é feita com
Claude Code, testada, e sobe pelo Coolify. Se um problema aparecer com frequência,
o caminho é transformá-lo em correção do catálogo, com teste.

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
