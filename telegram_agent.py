"""Agente de operação do Tuca no Telegram.

O que ele faz, em três frentes:

1. Conversa: a equipe pergunta em português ("como está o festival?",
   "o Tuca está respondendo bem?", "quais erros hoje?") e a IA escolhe qual
   leitura do `monitor.py` chamar. Os números vêm sempre do banco, nunca da IA.
   Comandos com barra funcionam sem IA nenhuma.

2. Varredura: de meia em meia hora ele roda `Monitor.varrer()` e avisa o grupo
   de cada problema novo. Um problema só é avisado uma vez, enquanto estiver
   aberto (tabela `agent_alerts`). Quando some, ele avisa que resolveu.

3. Correção com confirmação: se o problema tem uma correção no catálogo
   `CORRECOES`, a mensagem vem com o botão. Quem apertar confirma, e a correção
   roda na hora, em produção. Só existe o que está no catálogo: nada de código
   novo sai daqui. Mudança de código continua sendo trabalho de gente com
   revisão e deploy.

Também vigia chamados críticos novos a cada minuto, porque meia hora é tempo
demais para uma briga ou um mal-estar no festival.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

import requests
from dotenv import load_dotenv

from event_store import EventStore
from monitor import CORRECOES, Achado, Monitor, RegistroDeAlertas, agora, hora_local, iso

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("telegram_agent")

_running = True


def _stop(_signum: int, _frame: Any) -> None:
    global _running
    _running = False


# ----------------------------------------------------------------------
# Telegram: só o que o agente usa, via requests, sem biblioteca extra
# ----------------------------------------------------------------------
LIMITE_MENSAGEM = 3900


def escapar(texto: Any) -> str:
    return (
        str(texto if texto is not None else "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


class Telegram:
    """Cliente mínimo da Bot API."""

    def __init__(self, token: str) -> None:
        self._base = f"https://api.telegram.org/bot{token}"

    def _chamar(self, metodo: str, espera: int = 20, **dados: Any) -> Any:
        # O nome é "espera" e não "timeout" porque getUpdates manda um campo
        # "timeout" para o Telegram; se os dois se chamassem igual, o Python
        # recusava a chamada e o agente morria no primeiro ciclo.
        try:
            resposta = requests.post(f"{self._base}/{metodo}", json=dados, timeout=espera)
            corpo = resposta.json()
        except Exception as exc:  # noqa: BLE001 - rede oscila; o agente segue
            logger.error("Telegram %s falhou | erro=%s", metodo, type(exc).__name__)
            return None
        if not corpo.get("ok"):
            logger.error("Telegram %s recusou | %s", metodo, str(corpo.get("description"))[:200])
            return None
        return corpo.get("result")

    def get_me(self) -> dict[str, Any]:
        return self._chamar("getMe") or {}

    def get_updates(self, offset: int | None) -> list[dict[str, Any]]:
        dados: dict[str, Any] = {"timeout": 25, "allowed_updates": ["message", "callback_query"]}
        if offset is not None:
            dados["offset"] = offset
        return self._chamar("getUpdates", espera=35, **dados) or []

    def enviar(
        self,
        chat_id: Any,
        texto: str,
        botoes: list[list[dict[str, str]]] | None = None,
        html: bool = True,
        responder_a: int | None = None,
    ) -> dict[str, Any] | None:
        ultimo = None
        partes = _fatiar(texto)
        for indice, pedaco in enumerate(partes):
            dados: dict[str, Any] = {"chat_id": chat_id, "text": pedaco, "disable_web_page_preview": True}
            if html:
                dados["parse_mode"] = "HTML"
            if responder_a:
                dados["reply_to_message_id"] = responder_a
                dados["allow_sending_without_reply"] = True
            # Os botões vão só no último pedaço, para ficarem embaixo do texto.
            if botoes and indice == len(partes) - 1:
                dados["reply_markup"] = {"inline_keyboard": botoes}
            ultimo = self._chamar("sendMessage", **dados)
        return ultimo

    def editar(self, chat_id: Any, message_id: Any, texto: str, botoes: list[list[dict[str, str]]] | None = None) -> None:
        dados: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": texto[:4096],
            "parse_mode": "HTML",
            "reply_markup": {"inline_keyboard": botoes or []},
        }
        self._chamar("editMessageText", **dados)

    def responder_callback(self, callback_id: str, texto: str = "") -> None:
        self._chamar("answerCallbackQuery", callback_query_id=callback_id, text=texto[:200])

    def digitando(self, chat_id: Any) -> None:
        self._chamar("sendChatAction", chat_id=chat_id, action="typing")


def _fatiar(texto: str) -> list[str]:
    if len(texto) <= LIMITE_MENSAGEM:
        return [texto]
    partes, atual = [], ""
    for linha in texto.split("\n"):
        if len(atual) + len(linha) + 1 > LIMITE_MENSAGEM:
            partes.append(atual)
            atual = ""
        atual += linha + "\n"
    if atual.strip():
        partes.append(atual)
    return partes


# ----------------------------------------------------------------------
# GitHub: a ponte com o agente da nuvem
# ----------------------------------------------------------------------
LABEL_ISSUE = "tuca-alerta"   # problema que o agente da nuvem investiga
LABEL_PR = "tuca-agente"      # correção pronta, esperando aprovação no Telegram


class GitHub:
    """O que o agente precisa da API do GitHub: issue, PRs, merge, fechar."""

    def __init__(self, token: str, repo: str) -> None:
        self._repo = repo
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _chamar(self, metodo: str, caminho: str, **dados: Any) -> Any:
        url = f"https://api.github.com/repos/{self._repo}{caminho}"
        try:
            resposta = requests.request(metodo, url, headers=self._headers, json=dados or None, timeout=20)
        except Exception as exc:  # noqa: BLE001
            logger.error("GitHub %s %s falhou | erro=%s", metodo, caminho, type(exc).__name__)
            return None
        if resposta.status_code >= 300:
            logger.error("GitHub %s %s recusou | http=%s", metodo, caminho, resposta.status_code)
            return {"_erro": resposta.status_code, "_mensagem": str((resposta.json() or {}).get("message", ""))[:200] if resposta.content else ""}
        return resposta.json() if resposta.content else {}

    def criar_issue(self, titulo: str, corpo: str) -> int | None:
        dados = self._chamar("POST", "/issues", title=titulo[:250], body=corpo[:60000], labels=[LABEL_ISSUE])
        return int(dados["number"]) if dados and "number" in dados else None

    def prs_abertos(self) -> list[dict[str, Any]]:
        dados = self._chamar("GET", f"/pulls?state=open&per_page=30")
        if not isinstance(dados, list):
            return []
        return [
            {
                "numero": int(pr["number"]),
                "titulo": str(pr.get("title") or ""),
                "corpo": str(pr.get("body") or ""),
                "branch": str((pr.get("head") or {}).get("ref") or ""),
                "url": str(pr.get("html_url") or ""),
            }
            for pr in dados
            if any(lb.get("name") == LABEL_PR for lb in pr.get("labels") or [])
        ]

    def merge(self, numero: int, mensagem: str) -> tuple[bool, str]:
        dados = self._chamar("PUT", f"/pulls/{numero}/merge", merge_method="squash", commit_title=mensagem[:200])
        if dados and dados.get("merged"):
            return True, str(dados.get("sha") or "")[:10]
        if dados and "_erro" in dados:
            return False, f"GitHub recusou o merge (HTTP {dados['_erro']}): {dados.get('_mensagem') or 'sem detalhe'}"
        return False, "GitHub não respondeu ao merge."

    def fechar_pr(self, numero: int, comentario: str) -> bool:
        self._chamar("POST", f"/issues/{numero}/comments", body=comentario[:5000])
        dados = self._chamar("PATCH", f"/pulls/{numero}", state="closed")
        return bool(dados and dados.get("state") == "closed")


def corpo_da_issue(achado: Achado, erros: dict[str, Any] | None) -> str:
    """Issue que o agente da nuvem lê. Diagnóstico e contexto, nunca dado pessoal."""

    partes = [
        f"**Gravidade:** {achado.gravidade}",
        f"**Chave da varredura:** `{achado.chave}`",
        f"**Quando:** {hora_local(iso(agora()))} (São Paulo)",
        "",
        "## O que o agente do Telegram viu",
        achado.detalhe,
    ]
    if achado.acao:
        partes += ["", f"Correção do catálogo disponível no Telegram: `{achado.acao}`. Ela trata o sintoma; esta issue é para a causa."]
    if erros:
        partes += ["", "## Falhas recentes registradas no banco", "```json", json.dumps(erros, ensure_ascii=False, indent=1, default=str)[:6000], "```"]
    partes += [
        "",
        "## Contrato",
        "Leia `directives/prompt_agente_nuvem.md`. Se for bug ou configuração no código, abra um PR com a label "
        f"`{LABEL_PR}` referenciando esta issue, com os testes passando. Se não for coisa de código, comente o diagnóstico e feche a issue.",
    ]
    return "\n".join(partes)


# ----------------------------------------------------------------------
# Textos prontos (comandos sem IA)
# ----------------------------------------------------------------------
AJUDA = (
    "<b>Tuca Operação</b>\n"
    "Pergunte em português o que quiser saber sobre o festival, ou use:\n\n"
    "/resumo [horas]: números das últimas horas\n"
    "/criticos: chamados críticos e urgentes em aberto\n"
    "/chamados [urgencia]: últimos chamados\n"
    "/respostas: como o Tuca respondeu por último\n"
    "/erros: falhas de processamento e de entrega\n"
    "/saude: app, worker, Meta e IA\n"
    "/verificar: varredura completa agora\n"
    "/alertas: últimos alertas e o que foi decidido\n"
    "/prs: correções de código prontas, esperando aprovação\n"
    "/aprovar N e /rejeitar N: decide o PR número N (ou use os botões)\n"
    "/limpar: esquece a conversa com a IA\n"
    "/id: mostra o id deste chat"
)


def _seg(valor: Any) -> str:
    try:
        v = float(valor)
    except (TypeError, ValueError):
        return "?"
    return f"{v:.0f}s" if v < 120 else f"{v / 60:.1f} min"


def texto_resumo(r: dict[str, Any]) -> str:
    urg = ", ".join(f"{k} {v}" for k, v in r["por_urgencia"].items()) or "nenhum"
    cat = "\n".join(f"  {escapar(k)}: {v}" for k, v in list(r["por_categoria"].items())[:6]) or "  nenhuma"
    setores = "\n".join(f"  {escapar(k)}: {v}" for k, v in r["por_setor"].items()) or "  nenhum"
    ent = ", ".join(f"{k} {v}" for k, v in r["entregas"].items()) or "nenhuma"
    proc = ", ".join(f"{k} {v}" for k, v in r["processamento"].items()) or "nenhuma"
    t = r["tempo_resposta_seg"]
    tempo = (
        f"mediana {_seg(t['mediana'])}, p90 {_seg(t['p90'])}, pior {_seg(t['maximo'])} ({t['amostras']} respostas)"
        if t.get("amostras") else "sem amostra ainda"
    )
    return (
        f"<b>Resumo das últimas {r['janela_horas']}h</b>\n"
        f"Mensagens recebidas: {r['mensagens_recebidas']} ({r['audios']} áudios)\n"
        f"Processamento: {proc}\n"
        f"Chamados abertos pelo público: {r['chamados']}\n"
        f"Urgência: {urg}\n"
        f"Status: {', '.join(f'{k} {v}' for k, v in r['por_status'].items()) or 'nenhum'}\n"
        f"Categorias:\n{cat}\n"
        f"Setores com mais relatos:\n{setores}\n"
        f"Respostas do Tuca: {r['respostas_enviadas']} ({ent})\n"
        f"Tempo até responder: {tempo}"
    )


def texto_chamados(lista: list[dict[str, Any]], titulo: str) -> str:
    if not lista:
        return f"<b>{titulo}</b>\nNenhum chamado nesse filtro."
    linhas = [
        f"<b>#{c['id']}</b> {escapar(c['urgencia'])} · {escapar(c['setor'])} · {c['quando']} · {escapar(c['status'])}\n"
        f"{escapar(c['mensagem'][:220])}"
        for c in lista
    ]
    return f"<b>{titulo}</b>\n\n" + "\n\n".join(linhas)


def texto_respostas(pares: list[dict[str, Any]]) -> str:
    if not pares:
        return "O Tuca ainda não respondeu nenhum chamado."
    blocos = []
    for p in pares:
        resp = "\n".join(
            f"  ↳ <i>{escapar(r['quem'])}</i> ({escapar(r['entrega'])}): {escapar(r['texto'][:300])}"
            for r in p["respostas"]
        ) or "  ↳ sem resposta enviada"
        blocos.append(
            f"<b>#{p['id']}</b> {escapar(p['urgencia'])} · {escapar(p['setor'])} · {p['quando']}\n"
            f"Público: {escapar(p['mensagem'][:220])}\n{resp}"
        )
    return "<b>Últimas respostas do Tuca</b>\n\n" + "\n\n".join(blocos)


def texto_erros(e: dict[str, Any]) -> str:
    proc = e["processamento_falhou"]
    ent = e["entrega_falhou"]
    if not proc and not ent:
        return f"Nenhuma falha nas últimas {e['janela_horas']}h. Tudo processado e entregue."
    partes = [f"<b>Falhas das últimas {e['janela_horas']}h</b>"]
    if proc:
        partes.append(f"\n<b>Processamento</b> ({len(proc)}):")
        partes += [
            f"  {p['quando']} · {escapar(p['tipo'])} · {p['tentativas']} tent.{' · esgotou' if p['esgotou'] else ''} · {escapar(p['erro'])}"
            for p in proc
        ]
    if ent:
        partes.append(f"\n<b>Entrega</b> ({len(ent)}):")
        partes += [
            f"  {p['quando']} · chamado #{p['chamado']} · {escapar(p['estado'])} · "
            f"{'Meta aceitou e recusou depois' if p['meta_aceitou'] else 'Meta não aceitou'} · {escapar(p['erro'])}"
            for p in ent
        ]
    return "\n".join(partes)


def _bolinha(ok: Any) -> str:
    return "🟢" if ok else ("⚪" if ok is None else "🔴")


def texto_saude(s: dict[str, Any]) -> str:
    app, w, meta, ia = s["app"], s["worker"], s["meta"], s["ia"]
    app_txt = (
        f"HTTP {app.get('http')} · status {escapar(app.get('status'))} · banco {escapar(app.get('banco'))}"
        + (f" · no ar desde {app['no_ar_desde']}" if app.get("no_ar_desde") else "")
        if "http" in app else f"sem resposta ({escapar(app.get('erro'))})"
    )
    w_txt = (
        f"{w['esperando_worker']} esperando (máx {w['espera_max_min']} min) · "
        f"{w['presas_processando']} presas · {w['pendentes_total']} pendentes no total"
    )
    return (
        f"<b>Saúde do Tuca</b> ({s['verificado_em']})\n"
        f"{_bolinha(app.get('ok'))} App: {app_txt}\n"
        f"{_bolinha(w.get('ok'))} Worker: {w_txt}\n"
        f"{_bolinha(meta.get('ok'))} Meta: {escapar(meta.get('detalhe'))}\n"
        f"{_bolinha(ia.get('ok'))} IA: {escapar(ia.get('modelo') or '')} {escapar(ia.get('detalhe') or 'ok')}"
    )


def texto_alerta(achado: Achado) -> str:
    icone = "🚨" if achado.gravidade == "critico" else "⚠️"
    texto = f"{icone} <b>{escapar(achado.titulo)}</b>\n{escapar(achado.detalhe)}"
    if achado.acao and achado.acao in CORRECOES:
        texto += f"\n\n<i>Correção disponível: {escapar(CORRECOES[achado.acao][0].lower())}. Confirme no botão.</i>"
    return texto


def botoes_alerta(alerta_id: str, acao: str | None) -> list[list[dict[str, str]]]:
    linha = []
    if acao and acao in CORRECOES:
        linha.append({"text": f"✅ {CORRECOES[acao][0]}", "callback_data": f"fix:{alerta_id}"})
    linha.append({"text": "🙈 Ignorar", "callback_data": f"ign:{alerta_id}"})
    return [linha]


def texto_alertas(lista: list[dict[str, Any]]) -> str:
    if not lista:
        return "Nenhum alerta registrado ainda."
    rotulo = {"aberto": "🔴 aberto", "corrigido": "✅ corrigido", "ignorado": "🙈 ignorado", "resolvido": "🟢 resolveu sozinho"}
    linhas = []
    for a in lista:
        quem = f" por {escapar(a['decidido_por'])}" if a.get("decidido_por") else ""
        res = f"\n  {escapar(a['resultado'])}" if a.get("resultado") else ""
        linhas.append(f"{hora_local(a['created_at'])} · {rotulo.get(a['status'], a['status'])}{quem} · <b>{escapar(a['titulo'])}</b>{res}")
    return "<b>Últimos alertas</b>\n" + "\n".join(linhas)


# ----------------------------------------------------------------------
# IA: escolhe leituras do monitor e conta o resultado
# ----------------------------------------------------------------------
FERRAMENTAS = [
    {"type": "function", "function": {
        "name": "resumo",
        "description": "Números da operação: mensagens recebidas, chamados por urgência, categoria e setor, entregas e tempo de resposta do Tuca.",
        "parameters": {"type": "object", "properties": {"horas": {"type": "integer", "description": "Janela em horas, padrão 24"}}},
    }},
    {"type": "function", "function": {
        "name": "chamados",
        "description": "Lista chamados recentes do público, com id, urgência, setor, status e a mensagem.",
        "parameters": {"type": "object", "properties": {
            "urgencia": {"type": "string", "description": "critico, urgente, neutro ou positivo"},
            "status": {"type": "string", "enum": ["aberto", "em_andamento", "resolvido"]},
            "setor": {"type": "string", "description": "parte do nome ou código do setor"},
            "limite": {"type": "integer"},
            "horas": {"type": "integer"},
        }},
    }},
    {"type": "function", "function": {
        "name": "respostas_do_tuca",
        "description": "Últimos chamados com a resposta que o Tuca mandou e o estado de entrega. Use para avaliar a qualidade das respostas.",
        "parameters": {"type": "object", "properties": {"limite": {"type": "integer"}}},
    }},
    {"type": "function", "function": {
        "name": "erros",
        "description": "Falhas de processamento de mensagens e de entrega de respostas, com o erro registrado.",
        "parameters": {"type": "object", "properties": {"horas": {"type": "integer"}, "limite": {"type": "integer"}}},
    }},
    {"type": "function", "function": {
        "name": "saude",
        "description": "Estado do app, do worker, das credenciais da Meta e da IA.",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "verificar_agora",
        "description": "Roda a varredura completa de problemas agora. Problemas novos são avisados no grupo com botão de correção.",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "alertas_recentes",
        "description": "Últimos alertas da varredura e o que a equipe decidiu sobre cada um.",
        "parameters": {"type": "object", "properties": {"limite": {"type": "integer"}}},
    }},
]

SISTEMA = (
    "Você é o assistente de operação do Tuca, o bot de WhatsApp do festival Tropicadelia 2026. "
    "Você conversa com a equipe de produção pelo Telegram.\n\n"
    "Regras:\n"
    "- Todo número, chamado ou erro vem das ferramentas. Nunca invente nem estime; se não tiver o dado, diga.\n"
    "- Responda curto e direto, em português do Brasil, texto puro sem markdown, sem asteriscos e sem travessão.\n"
    "- Cite chamados como #id. Horários já vêm no fuso de São Paulo.\n"
    "- Ao avaliar respostas do Tuca, julgue clareza, tom e se a resposta combina com a mensagem e a urgência. Aponte o que melhoraria.\n"
    "- Você não altera nada por conta própria. As únicas correções possíveis são as dos alertas da varredura, confirmadas pelo botão no Telegram. "
    "Mudança de texto do bot é feita na tela Testar e Configurar do painel, e mudança de código é feita pelo desenvolvedor.\n"
    "- Nunca peça nem repita telefone ou nome de participante: esses dados não existem para você."
)


class Cerebro:
    """Conversa com a OpenAI usando as leituras do monitor como ferramentas."""

    def __init__(self, agente: "AgenteTelegram") -> None:
        self.agente = agente
        self._historico: dict[Any, deque[dict[str, Any]]] = {}
        self.modelo = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")

    def _cliente(self) -> Any:
        chave = os.getenv("OPENAI_API_KEY")
        if not chave:
            return None
        from openai import OpenAI

        return OpenAI(api_key=chave, timeout=float(os.getenv("AGENT_OPENAI_TIMEOUT", "60")))

    def esquecer(self, chat_id: Any) -> None:
        self._historico.pop(chat_id, None)

    def _kwargs(self, mensagens: list[dict[str, Any]]) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"model": self.modelo, "messages": mensagens, "tools": FERRAMENTAS, "tool_choice": "auto"}
        if self.modelo.lower().startswith(("gpt-5", "gpt-6", "o1", "o3", "o4")):
            kwargs["max_completion_tokens"] = 1200
            kwargs["reasoning_effort"] = os.getenv("AGENT_REASONING_EFFORT", "low")
        else:
            kwargs["max_tokens"] = 1200
            kwargs["temperature"] = 0.2
        return kwargs

    def executar_ferramenta(self, nome: str, argumentos: dict[str, Any], chat_id: Any) -> Any:
        m = self.agente.monitor
        if nome == "resumo":
            return m.resumo(argumentos.get("horas") or 24)
        if nome == "chamados":
            return m.chamados(
                urgencia=argumentos.get("urgencia"), status=argumentos.get("status"),
                setor=argumentos.get("setor"), limite=argumentos.get("limite") or 10,
                horas=argumentos.get("horas") or 48,
            )
        if nome == "respostas_do_tuca":
            return m.respostas_do_tuca(argumentos.get("limite") or 10)
        if nome == "erros":
            return m.erros(argumentos.get("horas"), argumentos.get("limite") or 10)
        if nome == "saude":
            return m.saude()
        if nome == "verificar_agora":
            achados = self.agente.executar_varredura()
            return {"problemas": [a.as_dict() for a in achados], "aviso": "problemas novos foram enviados ao grupo com botão"}
        if nome == "alertas_recentes":
            return self.agente.registro.recentes(argumentos.get("limite") or 10)
        return {"erro": f"ferramenta desconhecida: {nome}"}

    def responder(self, chat_id: Any, pergunta: str) -> str | None:
        """Devolve a resposta da IA, ou None se ela estiver fora do ar."""

        cliente = self._cliente()
        if cliente is None:
            return None
        historico = self._historico.setdefault(chat_id, deque(maxlen=16))
        mensagens: list[dict[str, Any]] = [{"role": "system", "content": SISTEMA + f"\nAgora: {hora_local(iso(agora()))}."}]
        mensagens += list(historico)
        mensagens.append({"role": "user", "content": pergunta[:4000]})

        try:
            for _ in range(6):
                resposta = cliente.chat.completions.create(**self._kwargs(mensagens))
                escolha = resposta.choices[0].message
                chamadas = getattr(escolha, "tool_calls", None) or []
                if not chamadas:
                    texto = (escolha.content or "").strip()
                    historico.append({"role": "user", "content": pergunta[:4000]})
                    historico.append({"role": "assistant", "content": texto[:4000]})
                    return texto or "Não consegui montar uma resposta. Tente /resumo ou /saude."
                mensagens.append({
                    "role": "assistant",
                    "content": escolha.content or "",
                    "tool_calls": [
                        {"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": c.function.arguments or "{}"}}
                        for c in chamadas
                    ],
                })
                for chamada in chamadas:
                    try:
                        argumentos = json.loads(chamada.function.arguments or "{}")
                    except ValueError:
                        argumentos = {}
                    try:
                        resultado = self.executar_ferramenta(chamada.function.name, argumentos, chat_id)
                    except Exception as exc:  # noqa: BLE001 - a IA recebe o erro e explica
                        logger.error("Ferramenta %s falhou | erro=%s", chamada.function.name, type(exc).__name__)
                        resultado = {"erro": f"leitura falhou: {type(exc).__name__}"}
                    mensagens.append({
                        "role": "tool",
                        "tool_call_id": chamada.id,
                        "content": json.dumps(resultado, ensure_ascii=False, default=str)[:14000],
                    })
            return "Precisei de muitas leituras e parei. Pergunte algo mais específico."
        except Exception as exc:  # noqa: BLE001 - IA fora não pode calar o agente
            logger.error("IA do agente falhou | erro=%s", type(exc).__name__)
            return None


# ----------------------------------------------------------------------
# O agente
# ----------------------------------------------------------------------
def nome_de(usuario: dict[str, Any] | None) -> str:
    if not usuario:
        return "alguém"
    nome = " ".join(p for p in (usuario.get("first_name"), usuario.get("last_name")) if p).strip()
    return nome or (usuario.get("username") or "alguém")


class AgenteTelegram:
    def __init__(
        self,
        telegram: Telegram,
        monitor: Monitor,
        registro: RegistroDeAlertas,
        chats_permitidos: set[str],
        chat_alertas: str | None,
        github: GitHub | None = None,
    ) -> None:
        self.tg = telegram
        self.monitor = monitor
        self.registro = registro
        self.chats_permitidos = chats_permitidos
        self.chat_alertas = chat_alertas
        self.github = github
        self.cerebro = Cerebro(self)
        self.username = ""
        self._lock = threading.Lock()
        self._criticos_vistos: deque[int] = deque(maxlen=500)
        self._vigia_desde = agora()
        self._prs_vistos: set[int] = set()
        # Depois de um merge, vigia o /health até o started_at mudar: é a
        # prova de que o Coolify subiu a versão nova.
        self._deploy_esperado: dict[str, Any] | None = None

    # --- autorização ---
    def permitido(self, chat_id: Any) -> bool:
        return str(chat_id) in self.chats_permitidos

    # --- updates ---
    def tratar_update(self, update: dict[str, Any]) -> None:
        try:
            if "callback_query" in update:
                self._tratar_callback(update["callback_query"])
            elif "message" in update:
                self._tratar_mensagem(update["message"])
        except Exception as exc:  # noqa: BLE001 - um update ruim não derruba o laço
            logger.error("Falha ao tratar update | erro=%s", type(exc).__name__)

    def _tratar_mensagem(self, msg: dict[str, Any]) -> None:
        chat_id = msg.get("chat", {}).get("id")
        texto = (msg.get("text") or "").strip()
        if not texto:
            return
        comando, argumento = self._parse_comando(texto)

        if comando == "id":
            tipo = msg.get("chat", {}).get("type")
            self.tg.enviar(chat_id, f"Id deste chat: <code>{chat_id}</code> ({escapar(tipo)})")
            return
        if not self.permitido(chat_id):
            logger.warning("Mensagem de chat não autorizado ignorada")
            return

        if comando:
            self._tratar_comando(chat_id, comando, argumento)
            return

        # Texto livre: no grupo, só se falarem com o bot (menção ou resposta)
        # ou se o modo privacidade estiver desligado no BotFather.
        pergunta = texto.replace(f"@{self.username}", "").strip() if self.username else texto
        if not pergunta:
            return
        self.tg.digitando(chat_id)
        resposta = self.cerebro.responder(chat_id, pergunta)
        if resposta is None:
            self.tg.enviar(
                chat_id,
                "A IA está fora do ar agora, mas os comandos funcionam sem ela:\n" + AJUDA,
            )
            return
        self.tg.enviar(chat_id, resposta, html=False, responder_a=msg.get("message_id") if str(chat_id).startswith("-") else None)

    def _parse_comando(self, texto: str) -> tuple[str | None, str]:
        if not texto.startswith("/"):
            return None, ""
        cabeca, _, resto = texto[1:].partition(" ")
        comando = cabeca.split("@", 1)[0].lower()
        return comando, resto.strip()

    def _tratar_comando(self, chat_id: Any, comando: str, argumento: str) -> None:
        m = self.monitor
        if comando in {"start", "ajuda", "help"}:
            self.tg.enviar(chat_id, AJUDA)
        elif comando == "resumo":
            horas = int(argumento) if argumento.isdigit() else 24
            self.tg.enviar(chat_id, texto_resumo(m.resumo(horas)))
        elif comando == "criticos":
            lista = m.chamados(urgencia="urgente", status="aberto", limite=15)
            self.tg.enviar(chat_id, texto_chamados(lista, "Críticos e urgentes em aberto"))
        elif comando == "chamados":
            lista = m.chamados(urgencia=argumento or None, limite=10)
            self.tg.enviar(chat_id, texto_chamados(lista, "Últimos chamados"))
        elif comando == "respostas":
            self.tg.enviar(chat_id, texto_respostas(m.respostas_do_tuca(8)))
        elif comando == "erros":
            self.tg.enviar(chat_id, texto_erros(m.erros()))
        elif comando == "saude":
            self.tg.digitando(chat_id)
            self.tg.enviar(chat_id, texto_saude(m.saude()))
        elif comando == "verificar":
            self.tg.digitando(chat_id)
            achados = self.executar_varredura()
            if not achados:
                self.tg.enviar(chat_id, "✅ Varredura completa: nenhum problema encontrado.")
            else:
                linhas = "\n".join(f"{'🚨' if a.gravidade == 'critico' else '⚠️'} {escapar(a.titulo)}" for a in achados)
                self.tg.enviar(chat_id, f"Varredura completa: {len(achados)} problema(s).\n{linhas}\nOs novos foram enviados com detalhe e botão.")
        elif comando == "alertas":
            self.tg.enviar(chat_id, texto_alertas(self.registro.recentes(10)))
        elif comando == "prs":
            if not self.github:
                self.tg.enviar(chat_id, "Sem GITHUB_TOKEN no agente: não consigo ver os PRs.")
            else:
                prs = self.github.prs_abertos()
                if not prs:
                    self.tg.enviar(chat_id, "Nenhuma correção de código esperando aprovação.")
                else:
                    linhas = "\n".join(f"PR #{p['numero']}: {escapar(p['titulo'])}" for p in prs)
                    self.tg.enviar(chat_id, f"<b>Correções prontas</b>\n{linhas}\n\nAprove com /aprovar N ou pelo botão da mensagem.")
        elif comando in {"aprovar", "rejeitar"}:
            if not argumento.isdigit():
                self.tg.enviar(chat_id, f"Diga o número: /{comando} 12")
            elif comando == "aprovar":
                self._aprovar_pr(int(argumento), "comando", chat_id)
            else:
                self._rejeitar_pr(int(argumento), "comando", chat_id)
        elif comando == "limpar":
            self.cerebro.esquecer(chat_id)
            self.tg.enviar(chat_id, "Conversa esquecida.")
        else:
            self.tg.enviar(chat_id, "Não conheço esse comando.\n\n" + AJUDA)

    # --- botões ---
    def _tratar_callback(self, cb: dict[str, Any]) -> None:
        cb_id = cb.get("id", "")
        msg = cb.get("message") or {}
        chat_id = msg.get("chat", {}).get("id")
        dados = cb.get("data") or ""
        quem = nome_de(cb.get("from"))
        if not self.permitido(chat_id):
            self.tg.responder_callback(cb_id, "Chat não autorizado.")
            return
        acao, _, alerta_id = dados.partition(":")
        if acao in {"pr_ok", "pr_no"}:
            if not alerta_id.isdigit():
                self.tg.responder_callback(cb_id, "PR inválido.")
                return
            self.tg.responder_callback(cb_id, "Aprovando..." if acao == "pr_ok" else "Rejeitando...")
            if acao == "pr_ok":
                self._aprovar_pr(int(alerta_id), quem, chat_id, msg.get("message_id"))
            else:
                self._rejeitar_pr(int(alerta_id), quem, chat_id, msg.get("message_id"))
            return
        alerta = self.registro.por_id(alerta_id) if alerta_id else None
        if not alerta:
            self.tg.responder_callback(cb_id, "Alerta não encontrado.")
            return
        original = texto_alerta(Achado(alerta["chave"], alerta["gravidade"], alerta["titulo"], alerta.get("detalhe") or "", alerta.get("acao")))

        if acao in {"fix", "ign"} and alerta.get("status") != "aberto":
            self.tg.responder_callback(cb_id, f"Já tratado: {alerta.get('status')} por {alerta.get('decidido_por') or 'ninguém'}.")
            return

        if acao == "fix":
            with self._lock:
                resultado = self.monitor.corrigir(str(alerta.get("acao") or ""))
                self.registro.fechar(alerta_id, "corrigido", resultado, quem)
            self.tg.responder_callback(cb_id, "Correção aplicada.")
            self.tg.editar(
                chat_id, msg.get("message_id"),
                f"{original}\n\n✅ <b>Corrigido por {escapar(quem)}</b> às {hora_local(iso(agora()))}\n{escapar(resultado)}",
                [[{"text": "🔎 Verificar de novo", "callback_data": f"chk:{alerta_id}"}]],
            )
        elif acao == "ign":
            self.registro.fechar(alerta_id, "ignorado", None, quem)
            self.tg.responder_callback(cb_id, "Ignorado por 6h.")
            self.tg.editar(chat_id, msg.get("message_id"), f"{original}\n\n🙈 <b>Ignorado por {escapar(quem)}</b>. Volto a avisar se continuar depois de 6h.")
        elif acao == "chk":
            self.tg.responder_callback(cb_id, "Verificando...")
            achados = {a.chave: a for a in self.executar_varredura()}
            if alerta["chave"] in achados:
                self.tg.enviar(chat_id, f"⚠️ Ainda aparece: {escapar(achados[alerta['chave']].titulo)}. Mandei o alerta novo com detalhe.", responder_a=msg.get("message_id"))
            else:
                self.tg.enviar(chat_id, f"✅ Confirmado: <b>{escapar(alerta['titulo'])}</b> não aparece mais.", responder_a=msg.get("message_id"))
        else:
            self.tg.responder_callback(cb_id, "Botão desconhecido.")

    # --- varredura e alertas ---
    def executar_varredura(self) -> list[Achado]:
        """Varre, avisa o que é novo, fecha o que sumiu. Devolve tudo que está errado agora."""

        with self._lock:
            achados = self.monitor.varrer()
            chaves = {a.chave for a in achados}
            try:
                abertos = {a["chave"]: a for a in self.registro.abertos()}
                ignorados = self.registro.ignorados_recentes()
            except Exception as exc:  # noqa: BLE001 - sem registro, avisa mesmo assim
                logger.error("Registro de alertas indisponível | erro=%s", type(exc).__name__)
                abertos, ignorados = {}, set()

            for achado in achados:
                if achado.chave in abertos or achado.chave in ignorados:
                    continue
                self._avisar(achado)

            for chave, alerta in abertos.items():
                # Anúncio de PR não é achado da varredura: fecha só por decisão.
                if chave in chaves or chave.startswith("pr:"):
                    continue
                try:
                    self.registro.fechar(str(alerta["id"]), "resolvido", "Sumiu na varredura seguinte.")
                except Exception as exc:  # noqa: BLE001
                    logger.error("Não fechou alerta | erro=%s", type(exc).__name__)
                if self.chat_alertas:
                    self.tg.enviar(self.chat_alertas, f"🟢 Resolvido: <b>{escapar(alerta['titulo'])}</b> não aparece mais.")
        return achados

    def _avisar(self, achado: Achado) -> None:
        if not self.chat_alertas:
            logger.warning("Sem chat de alertas configurado; achado %s só no log", achado.chave)
            return
        try:
            alerta = self.registro.abrir(achado)
        except Exception as exc:  # noqa: BLE001 - registro fora: avisa sem botão, sem dedupe
            logger.error("Não registrou alerta | erro=%s", type(exc).__name__)
            self.tg.enviar(self.chat_alertas, texto_alerta(achado))
            return
        alerta_id = str(alerta.get("id") or "")
        texto = texto_alerta(achado)
        numero = self._abrir_issue(achado, alerta_id)
        if numero:
            texto += f"\n\n🛰 <i>Issue #{numero} aberta para o agente da nuvem investigar. Se for coisa de código, a correção chega aqui como PR para você aprovar.</i>"
        enviado = self.tg.enviar(self.chat_alertas, texto, botoes_alerta(alerta_id, achado.acao))
        if enviado and alerta_id:
            try:
                self.registro.anotar_mensagem(alerta_id, self.chat_alertas, enviado.get("message_id"))
            except Exception:  # noqa: BLE001
                pass

    def _abrir_issue(self, achado: Achado, alerta_id: str) -> int | None:
        """Problema que pode ser bug vira issue para o agente da nuvem. Uma por alerta."""

        if not self.github or not achado.investigar:
            return None
        try:
            erros = self.monitor.erros(6, 10)
        except Exception:  # noqa: BLE001 - a issue sai mesmo sem o anexo
            erros = None
        numero = self.github.criar_issue(f"[Tuca] {achado.titulo}", corpo_da_issue(achado, erros))
        if numero and alerta_id:
            try:
                self.registro.anotar_issue(alerta_id, numero)
            except Exception:  # noqa: BLE001
                pass
        return numero

    def vigiar_criticos(self) -> None:
        """Chamado crítico novo é avisado em um minuto, não em meia hora."""

        if not self.chat_alertas:
            return
        desde = self._vigia_desde
        self._vigia_desde = agora()
        for c in self.monitor.criticos_desde(desde):
            if c["id"] in self._criticos_vistos:
                continue
            self._criticos_vistos.append(c["id"])
            self.tg.enviar(
                self.chat_alertas,
                f"🚨 <b>Chamado crítico #{c['id']}</b> · {escapar(c['setor'])} · {c['quando']}\n"
                f"{escapar(c['mensagem'][:400])}\n<i>Alguém precisa assumir no painel.</i>",
            )

    # --- correções de código: PR aprovado no Telegram ---
    def vigiar_prs(self) -> None:
        """PR com a label do agente da nuvem é anunciado uma vez, com botão."""

        if not self.github or not self.chat_alertas:
            return
        for pr in self.github.prs_abertos():
            numero = pr["numero"]
            if numero in self._prs_vistos:
                continue
            self._prs_vistos.add(numero)
            try:
                if self.registro.por_chave(f"pr:{numero}"):
                    continue  # já anunciado antes de um reinício do agente
            except Exception:  # noqa: BLE001
                pass
            self._anunciar_pr(pr)

    def _anunciar_pr(self, pr: dict[str, Any]) -> None:
        numero = pr["numero"]
        achado = Achado(f"pr:{numero}", "atencao", f"Correção pronta: PR #{numero}", pr["titulo"])
        try:
            self.registro.abrir(achado)
        except Exception as exc:  # noqa: BLE001
            logger.error("Não registrou anúncio do PR | erro=%s", type(exc).__name__)
        corpo = pr["corpo"].strip()
        texto = (
            f"🛠 <b>Correção de código pronta: PR #{numero}</b>\n"
            f"<b>{escapar(pr['titulo'])}</b>\n\n"
            f"{escapar(corpo[:1200])}{'...' if len(corpo) > 1200 else ''}\n\n"
            f"{escapar(pr['url'])}\n\n"
            "<i>Aprovar faz o merge na main e o Coolify sobe a versão nova em alguns minutos. Eu confirmo aqui quando estiver no ar.</i>"
        )
        botoes = [[
            {"text": "✅ Aprovar e subir", "callback_data": f"pr_ok:{numero}"},
            {"text": "❌ Rejeitar", "callback_data": f"pr_no:{numero}"},
        ]]
        self.tg.enviar(self.chat_alertas, texto, botoes)

    def _fechar_anuncio(self, numero: int, status: str, resultado: str, quem: str) -> None:
        try:
            alerta = self.registro.por_chave(f"pr:{numero}")
            if alerta and alerta.get("status") == "aberto":
                self.registro.fechar(str(alerta["id"]), status, resultado, quem)
        except Exception as exc:  # noqa: BLE001
            logger.error("Não fechou anúncio do PR | erro=%s", type(exc).__name__)

    def _aprovar_pr(self, numero: int, quem: str, chat_id: Any, message_id: Any = None) -> None:
        if not self.github:
            self.tg.enviar(chat_id, "Sem GITHUB_TOKEN no agente: não consigo fazer o merge.")
            return
        with self._lock:
            ok, detalhe = self.github.merge(numero, f"fix: PR #{numero} aprovado no Telegram por {quem}")
        if not ok:
            self.tg.enviar(chat_id, f"❌ Não consegui subir o PR #{numero}: {escapar(detalhe)}", responder_a=message_id)
            return
        self._fechar_anuncio(numero, "corrigido", f"Merge {detalhe} aprovado no Telegram", quem)
        app = self.monitor._checar_app()
        self._deploy_esperado = {"pr": numero, "started_at": app.get("no_ar_desde"), "desde": time.monotonic()}
        self.tg.enviar(
            chat_id,
            f"✅ <b>PR #{numero} aprovado por {escapar(quem)}</b> e mergeado na main ({escapar(detalhe)}).\n"
            "O Coolify está subindo a versão nova. Aviso quando o /health mudar.",
            responder_a=message_id,
        )
        if message_id:
            self.tg.editar(chat_id, message_id, f"🛠 <b>PR #{numero}</b> aprovado por {escapar(quem)} às {hora_local(iso(agora()))}.")

    def _rejeitar_pr(self, numero: int, quem: str, chat_id: Any, message_id: Any = None) -> None:
        if not self.github:
            self.tg.enviar(chat_id, "Sem GITHUB_TOKEN no agente: não consigo fechar o PR.")
            return
        fechou = self.github.fechar_pr(numero, f"Rejeitado no Telegram por {quem}. Não vai para produção.")
        self._fechar_anuncio(numero, "ignorado", "Rejeitado no Telegram", quem)
        texto = f"❌ PR #{numero} rejeitado por {escapar(quem)}." + ("" if fechou else " Não consegui fechar no GitHub; feche por lá.")
        self.tg.enviar(chat_id, texto, responder_a=message_id)
        if message_id:
            self.tg.editar(chat_id, message_id, f"🛠 <b>PR #{numero}</b> rejeitado por {escapar(quem)} às {hora_local(iso(agora()))}.")

    def vigiar_deploy(self) -> None:
        """Confirma no grupo quando a versão aprovada está no ar."""

        esperado = self._deploy_esperado
        if not esperado or not self.chat_alertas:
            return
        app = self.monitor._checar_app()
        if app.get("ok") and app.get("no_ar_desde") and app.get("no_ar_desde") != esperado.get("started_at"):
            self._deploy_esperado = None
            self.tg.enviar(self.chat_alertas, f"🟢 <b>Versão nova no ar</b> (PR #{esperado['pr']}). App reiniciado às {app['no_ar_desde']}.")
        elif time.monotonic() - esperado["desde"] > 20 * 60:
            self._deploy_esperado = None
            self.tg.enviar(self.chat_alertas, f"⚠️ Passaram 20 min e o /health não mudou depois do PR #{esperado['pr']}. Confira o deploy no Coolify.")

    # --- laços ---
    def laco_agendado(self) -> None:
        intervalo = max(1, int(os.getenv("MONITOR_INTERVAL_MIN", "30"))) * 60
        vigia = int(os.getenv("MONITOR_VIGIA_SEG", "60"))
        proxima_varredura = time.monotonic() + 60
        proxima_vigia = time.monotonic() + 20
        while _running:
            agora_m = time.monotonic()
            if agora_m >= proxima_varredura:
                proxima_varredura = agora_m + intervalo
                try:
                    achados = self.executar_varredura()
                    logger.info("Varredura concluída | problemas=%d", len(achados))
                except Exception as exc:  # noqa: BLE001
                    logger.error("Varredura falhou | erro=%s", type(exc).__name__)
            if vigia > 0 and agora_m >= proxima_vigia:
                proxima_vigia = agora_m + vigia
                for vigia_fn in (self.vigiar_criticos, self.vigiar_prs, self.vigiar_deploy):
                    try:
                        vigia_fn()
                    except Exception as exc:  # noqa: BLE001
                        logger.error("%s falhou | erro=%s", vigia_fn.__name__, type(exc).__name__)
            time.sleep(5)

    def laco_telegram(self) -> None:
        # Este laço é o processo inteiro. Se ele morrer, o Docker reinicia o
        # container, e o Coolify para o app todo depois de dez reinícios: o
        # agente de operação derrubaria o Tuca. Por isso nada aqui escapa.
        offset: int | None = None
        while _running:
            try:
                updates = self.tg.get_updates(offset)
                if not updates:
                    time.sleep(2)
                    continue
                for update in updates:
                    offset = int(update.get("update_id", 0)) + 1
                    self.tratar_update(update)
            except Exception as exc:  # noqa: BLE001 - o laço nunca pode morrer
                logger.error("Laço do Telegram falhou | erro=%s", type(exc).__name__)
                time.sleep(10)


def main() -> None:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN ausente: o agente fica parado até o deploy com a variável")
        while _running:
            time.sleep(3600)
        return

    chats = {c.strip() for c in os.getenv("TELEGRAM_CHAT_IDS", "").split(",") if c.strip()}
    chat_alertas = os.getenv("TELEGRAM_ALERT_CHAT_ID", "").strip() or (sorted(chats)[0] if chats else None)
    if not chats:
        logger.warning("TELEGRAM_CHAT_IDS vazio: só o comando /id responde, use-o para descobrir o id do grupo")

    store = EventStore()
    # Sem banco o agente não morre: espera. Morrer em loop faria o Coolify
    # parar o app inteiro depois de dez reinícios.
    while _running and not store.healthcheck():
        logger.error("Agente sem acesso ao evento no Supabase; tento de novo em 60s")
        time.sleep(60)
    if not _running:
        return

    telegram = Telegram(token)
    eu = telegram.get_me()
    github = None
    if os.getenv("GITHUB_TOKEN", "").strip():
        github = GitHub(os.getenv("GITHUB_TOKEN", "").strip(), os.getenv("GITHUB_REPO", "jaolito85-hash/antigravit-eventos"))
    else:
        logger.warning("GITHUB_TOKEN vazio: sem issue para a nuvem e sem aprovação de PR pelo Telegram")
    agente = AgenteTelegram(telegram, Monitor(store), RegistroDeAlertas(store), chats, chat_alertas, github)
    agente.username = str(eu.get("username") or "")
    logger.info("Agente do Telegram iniciado | bot=@%s | chats=%d", agente.username, len(chats))

    if chat_alertas:
        intervalo = os.getenv("MONITOR_INTERVAL_MIN", "30")
        telegram.enviar(chat_alertas, f"🟢 Agente do Tuca no ar. Varredura a cada {intervalo} min, chamados críticos em até 1 min. /ajuda para os comandos.")

    threading.Thread(target=agente.laco_agendado, name="varredura", daemon=True).start()
    agente.laco_telegram()
    logger.info("Agente encerrado")


if __name__ == "__main__":
    main()
