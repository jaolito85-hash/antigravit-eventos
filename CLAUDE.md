# Tuca | Tropicadelia 2026 — Instruções para o Claude Code

## Sobre o Projeto

Tuca é a plataforma de escuta ativa e inteligência operacional em tempo real para
festivais. O frequentador escaneia o QR Code do setor onde está, manda texto ou áudio
pelo WhatsApp oficial, e a sala de controle vê o relato classificado por IA aparecer
no mapa da planta em segundos.

Stack: Flask (Python 3.11), Supabase (PostgreSQL com RLS), Meta WhatsApp Cloud API,
OpenAI (GPT-4o-mini e Whisper), Coolify/Docker.

**Porta:** 5001 | **Domínio:** app.nodedata.com.br | **Evento ativo:** `tropicadelia-2026`

## Estrutura do Repositório

```
server.py          — App Flask: webhook da Meta, APIs do dashboard, telas
worker.py          — Processa a fila: transcreve, classifica e envia respostas
event_store.py     — Persistência no Supabase (inbox, feedbacks, outbox, setores)
meta_whatsapp.py   — Integração com a Graph API (assinatura, parse, envio, mídia)
templates/         — telao.html, data_node.html, relatorio.html, qrcode.html, login.html
static/            — Logo, ícones, planta aérea 3D, manifest PWA
supabase/migrations/ — Schema, RLS e os setores da planta oficial
execution/         — Scripts determinísticos de operação
scripts/           — Verificação de banco e geração de documentos
directives/        — event_monitor.md (SOP principal, leia antes de mexer no fluxo)
docs/ENSAIO_SABADO.md — Roteiro de ensaio e diagnóstico de problemas
AGENTE.md          — Arquitetura de 3 camadas
PRODUCTION_CHECKLIST.md — Regras de qualidade e segurança
```

## Variáveis de Ambiente

O template completo está em `.env.example`. As marcadas com `(*)` são exigidas pelo
`/health`: sem todas elas o endpoint devolve 503 e o Coolify trata o container como
doente.

As três que fazem o bot existir:

- `META_APP_SECRET` — sem ela, toda mensagem recebida cai com 401 na validação da assinatura
- `META_ACCESS_TOKEN` — sem ela, o worker morre no start e não envia resposta nenhuma
- `META_PHONE_NUMBER_ID` — sem ela, o webhook descarta as mensagens recebidas

## Arquitetura de Trabalho

Siga as 3 camadas do `AGENTE.md`:

1. **Directive** (o que fazer) → `directives/event_monitor.md`
2. **Orchestration** (decisões) → você, o agente
3. **Execution** (fazer o trabalho) → scripts em `execution/` e `scripts/`

## Funcionalidades Principais

- Recebimento via webhook oficial da Meta com validação HMAC-SHA256
- Fila idempotente no Supabase: o webhook só persiste, o worker processa
- Transcrição de áudio via OpenAI Whisper
- Classificação de urgência, categoria e região por IA com fallback por palavras-chave
- Roteamento determinístico por setor através da tag `#SETOR:CODIGO` do QR Code
- Telão da sala de controle (`/telao`) com a planta aérea 3D e alerta crítico em tela cheia
- Mapa ao Vivo, dashboard com filtros, exportação CSV/JSON
- Simulador do bot em `/tuca`: a produção conversa com o Tuca no navegador
  e vê a classificação, sem gravar nem enviar mensagem
- Base de perguntas e respostas configurável: o conteúdo é cadastrado pela
  produção e a IA só escolhe o jeito de dizer
- Atendimento humano: pelo botão de conversar dentro do chamado, o operador assume,
  fala direto com o participante e devolve ao bot quando terminar
- Relatório pós-evento com resumo executivo e desempenho por setor
- Autenticação por sessão (ADMIN_USER / ADMIN_PASS)

## Regras que Valem Sempre

### Segurança
- Nunca coloque chaves, tokens ou senhas no código, sempre em `.env`
- Sempre valide a assinatura dos webhooks recebidos (`verify_webhook_signature`)
- Dados de frequentadores são protegidos por LGPD: telefone passa por HMAC-SHA256
  antes de gravar, e as APIs do dashboard passam por `public_feedback()`
- Texto vindo do público é escapado antes de qualquer `innerHTML` nos templates

### Código
- Sempre use try/except em chamadas externas (Supabase, Graph API, OpenAI)
- Sempre configure timeout nas requisições HTTP (mínimo 10s)
- Retorne rápido no webhook e deixe o trabalho pesado para o worker
- Toda chamada de IA precisa de fallback determinístico
- Sempre mascare dados pessoais nos logs

### Estilo
- Python com type hints quando possível
- Docstrings em português
- Comentários explicando o "porquê", não o "o quê"
- Nunca use travessão em texto, copy ou comentário

## Testes

```bash
python -m unittest discover -s tests
```
