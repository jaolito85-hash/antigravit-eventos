# Node Data — Eventos — Instruções para o Claude Code

## Sobre o Projeto

Node Data Eventos é a plataforma central de coleta de feedback via WhatsApp, com análise de sentimento por IA, transcrição de áudio e dashboard em tempo real para eventos e monitoramento geral.

Stack: Flask (Python), Supabase, Evolution API, OpenAI, Coolify/Docker.

**Porta:** 5001 | **Domínio:** app.nodedata.com.br

## Estrutura do Repositório

```
server.py          — App Flask principal (1500+ linhas)
Dockerfile         — Container (Gunicorn, 2 workers, 4 threads, timeout 120s)
requirements.txt   — Dependências Python
.env.example       — Template de variáveis de ambiente
templates/         — relatorio.html, login.html, qrcode.html, data_node.html
static/            — Logo, ícones, manifest PWA
execution/         — Scripts SQL e Python determinísticos
directives/        — event_monitor.md (SOP principal)
AGENTE.md          — Arquitetura de 3 camadas
PRODUCTION_CHECKLIST.md — Regras de qualidade e segurança
```

## Variáveis de Ambiente Necessárias

```
SUPABASE_URL=
SUPABASE_KEY=
EVOLUTION_API_URL=
EVOLUTION_API_KEY=
EVOLUTION_INSTANCE_NAME=
OPENAI_API_KEY=
SECRET_KEY=
ADMIN_USER=
ADMIN_PASS=
PORT=5001
FLASK_ENV=production
```

## Arquitetura de Trabalho

Siga a arquitetura de 3 camadas descrita no `AGENTE.md`:
1. **Directive** (o que fazer) → `directives/event_monitor.md`
2. **Orchestration** (decisões) → você, o agente
3. **Execution** (fazer o trabalho) → scripts em `execution/`

## Funcionalidades Principais

- Coleta de feedback via WhatsApp (Evolution API webhook em `/webhook`)
- Transcrição de áudio via OpenAI Whisper
- Classificação de sentimento e categoria por IA
- Dashboard em tempo real com filtros e exportação CSV/JSON
- Geração de relatórios e insights por IA (`/api/ai-pulse`)
- Autenticação por sessão (ADMIN_USER / ADMIN_PASS)
- Fallback para JSON local se Supabase indisponível

## Regras que Valem Sempre

### Segurança
- Nunca coloque chaves, tokens ou senhas no código — sempre em `.env`
- Sempre valide a origem dos webhooks recebidos
- Dados de cidadãos são protegidos por LGPD — nunca exponha em logs

### Código
- Sempre use try/except em chamadas externas (Supabase, Evolution API, OpenAI)
- Sempre configure timeout nas requisições HTTP (mínimo 10s)
- Retorne 200 rápido nos webhooks e processe pesado em background
- Sempre mascare dados pessoais nos logs (telefone, CPF)

### Estilo
- Python com type hints quando possível
- Docstrings em português
- Comentários explicando o "porquê", não o "o quê"
