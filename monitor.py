"""Leituras operacionais, varredura de problemas e correções do Tuca.

Este módulo é a parte determinística do agente do Telegram: tudo que ele
responde sobre a operação vem daqui, e toda correção que ele aplica está no
catálogo `CORRECOES`. A IA só escolhe qual leitura chamar e como contar o
resultado; nunca inventa um número nem executa nada fora do catálogo.

Nada aqui devolve telefone, nome ou identificador do participante.
"""

from __future__ import annotations

import logging
import os
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import requests

from event_store import EventStore

logger = logging.getLogger(__name__)

try:
    from zoneinfo import ZoneInfo

    FUSO = ZoneInfo("America/Sao_Paulo")
except Exception:  # noqa: BLE001 - imagem sem tzdata cai no offset fixo
    FUSO = timezone(timedelta(hours=-3))

CRITICOS = {"Critico", "Crítico"}
URGENTES = CRITICOS | {"Urgente"}

# Códigos da Meta que descrevem o participante, não o Tuca: 131047 é a janela
# de 24h fechada, 131026 é número fora do WhatsApp, 131049 e 130472 são a
# Meta segurando a entrega por política própria. Nada disso se corrige em código.
META_ERROS_DO_PARTICIPANTE = ("131047", "131026", "131049", "130472")

# Limites da varredura. Ficam em variável de ambiente para a equipe apertar
# ou afrouxar durante o festival sem redeploy de código.
ESPERA_WORKER_MIN = int(os.getenv("MONITOR_ESPERA_WORKER_MIN", "3"))
PRESA_PROCESSANDO_MIN = int(os.getenv("MONITOR_PRESA_PROCESSANDO_MIN", "10"))
CRITICO_SEM_ATENDIMENTO_MIN = int(os.getenv("MONITOR_CRITICO_SEM_ATENDIMENTO_MIN", "10"))
FILA_ACUMULADA = int(os.getenv("MONITOR_FILA_ACUMULADA", "30"))
JANELA_ERROS_HORAS = int(os.getenv("MONITOR_JANELA_ERROS_HORAS", "24"))


def agora() -> datetime:
    return datetime.now(timezone.utc)


def iso(momento: datetime) -> str:
    return momento.isoformat()


def _parse(valor: Any) -> datetime | None:
    """Converte o timestamptz do Supabase; aceita o 'Z' e a ausência de fuso."""

    if not valor:
        return None
    try:
        texto = str(valor).replace("Z", "+00:00")
        momento = datetime.fromisoformat(texto)
        if momento.tzinfo is None:
            momento = momento.replace(tzinfo=timezone.utc)
        return momento
    except ValueError:
        return None


def hora_local(valor: Any) -> str:
    momento = _parse(valor)
    if not momento:
        return "sem hora"
    return momento.astimezone(FUSO).strftime("%d/%m %H:%M")


def minutos_desde(valor: Any) -> int:
    momento = _parse(valor)
    if not momento:
        return 0
    return max(0, int((agora() - momento).total_seconds() // 60))


def max_tentativas() -> int:
    return int(os.getenv("WORKER_MAX_ATTEMPTS", "8"))


@dataclass
class Achado:
    """Um problema encontrado na varredura."""

    chave: str
    gravidade: str  # "critico" ou "atencao"
    titulo: str
    detalhe: str
    acao: str | None = None
    quantidade: int = 0
    # Vale abrir issue para o agente da nuvem investigar: o problema pode ser
    # bug ou configuração, não coisa que a sala de controle resolve na mão.
    investigar: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class Monitor:
    """Lê o estado do Tuca no Supabase e aplica correções do catálogo."""

    def __init__(self, store: EventStore, health_url: str | None = None) -> None:
        self.store = store
        self.health_url = health_url or os.getenv("APP_HEALTH_URL", "http://web:5001/health")
        self._setores: dict[str, dict[str, Any]] | None = None

    # ------------------------------------------------------------------
    # Apoio
    # ------------------------------------------------------------------
    def _event_id(self) -> str:
        return self.store.event_id()

    def setores(self) -> dict[str, dict[str, Any]]:
        if self._setores is None:
            self._setores = {str(s["id"]): s for s in self.store.list_sectors()}
        return self._setores

    def nome_setor(self, sector_id: Any) -> str:
        setor = self.setores().get(str(sector_id or ""))
        return str(setor["name"]) if setor else "sem setor"

    def _rows(self, query: Any) -> list[dict[str, Any]]:
        response = query.execute()
        return list(response.data or [])

    # ------------------------------------------------------------------
    # Leituras que a equipe pede no Telegram
    # ------------------------------------------------------------------
    def _feedbacks_desde(self, inicio: datetime, limite: int = 5000) -> list[dict[str, Any]]:
        return self._rows(
            self.store.table("feedbacks")
            .select("id,message,category,region,urgency,sentiment,topic,status,created_at,resolved_at,sector_id,inbox_message_id")
            .eq("event_id", self._event_id())
            .gte("created_at", iso(inicio))
            .order("created_at", desc=True)
            .limit(limite)
        )

    def resumo(self, horas: int = 24) -> dict[str, Any]:
        """Números da operação na janela: chamados, fila, entregas e tempo de resposta."""

        horas = max(1, min(int(horas or 24), 24 * 14))
        inicio = agora() - timedelta(hours=horas)
        feedbacks = self._feedbacks_desde(inicio)

        por_urgencia: dict[str, int] = {}
        por_categoria: dict[str, int] = {}
        por_setor: dict[str, int] = {}
        por_status: dict[str, int] = {}
        for f in feedbacks:
            urg = "Crítico" if f.get("urgency") in CRITICOS else str(f.get("urgency") or "Neutro")
            por_urgencia[urg] = por_urgencia.get(urg, 0) + 1
            cat = str(f.get("category") or "Sem categoria")
            por_categoria[cat] = por_categoria.get(cat, 0) + 1
            setor = self.nome_setor(f.get("sector_id"))
            por_setor[setor] = por_setor.get(setor, 0) + 1
            st = str(f.get("status") or "aberto")
            por_status[st] = por_status.get(st, 0) + 1

        entregas = self._rows(
            self.store.table("outbound_messages")
            .select("id,delivery_status,feedback_id,sent_at,created_at,origin")
            .eq("event_id", self._event_id())
            .gte("created_at", iso(inicio))
            .limit(5000)
        )
        por_entrega: dict[str, int] = {}
        for e in entregas:
            st = str(e.get("delivery_status") or "queued")
            por_entrega[st] = por_entrega.get(st, 0) + 1

        recebidas = self._rows(
            self.store.table("message_inbox")
            .select("id,processing_status,message_type,created_at")
            .eq("event_id", self._event_id())
            .gte("created_at", iso(inicio))
            .limit(5000)
        )
        por_processamento: dict[str, int] = {}
        audios = 0
        for r in recebidas:
            st = str(r.get("processing_status") or "pending")
            por_processamento[st] = por_processamento.get(st, 0) + 1
            if r.get("message_type") == "audio":
                audios += 1

        tempos = self._tempos_de_resposta(feedbacks, entregas, recebidas)

        return {
            "janela_horas": horas,
            "mensagens_recebidas": len(recebidas),
            "audios": audios,
            "processamento": por_processamento,
            "chamados": len(feedbacks),
            "por_urgencia": dict(sorted(por_urgencia.items(), key=lambda kv: -kv[1])),
            "por_status": por_status,
            "por_categoria": dict(sorted(por_categoria.items(), key=lambda kv: -kv[1])),
            "por_setor": dict(sorted(por_setor.items(), key=lambda kv: -kv[1])[:10]),
            "respostas_enviadas": len(entregas),
            "entregas": por_entrega,
            "tempo_resposta_seg": tempos,
        }

    @staticmethod
    def _tempos_de_resposta(
        feedbacks: list[dict[str, Any]],
        entregas: list[dict[str, Any]],
        recebidas: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Segundos entre a mensagem chegar e a resposta ser aceita pela Meta."""

        chegada = {str(r["id"]): _parse(r.get("created_at")) for r in recebidas}
        inbox_do_feedback = {int(f["id"]): str(f.get("inbox_message_id") or "") for f in feedbacks}
        amostras: list[float] = []
        for e in entregas:
            if e.get("origin") == "operator" or not e.get("feedback_id") or not e.get("sent_at"):
                continue
            inicio = chegada.get(inbox_do_feedback.get(int(e["feedback_id"]), ""))
            fim = _parse(e.get("sent_at"))
            if inicio and fim and fim >= inicio:
                amostras.append((fim - inicio).total_seconds())
        if not amostras:
            return {"amostras": 0}
        amostras.sort()
        p90 = amostras[min(len(amostras) - 1, int(len(amostras) * 0.9))]
        return {
            "amostras": len(amostras),
            "mediana": round(statistics.median(amostras), 1),
            "p90": round(p90, 1),
            "maximo": round(amostras[-1], 1),
        }

    def chamados(
        self,
        urgencia: str | None = None,
        status: str | None = None,
        setor: str | None = None,
        limite: int = 10,
        horas: int = 48,
    ) -> list[dict[str, Any]]:
        """Chamados recentes, sem nenhum dado pessoal."""

        limite = max(1, min(int(limite or 10), 30))
        inicio = agora() - timedelta(hours=max(1, int(horas or 48)))
        query = (
            self.store.table("feedbacks")
            .select("id,message,category,region,urgency,topic,status,created_at,resolved_at,sector_id")
            .eq("event_id", self._event_id())
            .gte("created_at", iso(inicio))
            .order("created_at", desc=True)
            .limit(300)
        )
        if status:
            query = query.eq("status", status)
        linhas = self._rows(query)

        if urgencia:
            alvo = urgencia.strip().lower()
            if alvo.startswith("crit"):
                linhas = [f for f in linhas if f.get("urgency") in CRITICOS]
            elif alvo.startswith("urg"):
                linhas = [f for f in linhas if f.get("urgency") in URGENTES]
            else:
                linhas = [f for f in linhas if str(f.get("urgency") or "").lower().startswith(alvo)]
        if setor:
            alvo = setor.strip().lower()
            linhas = [
                f for f in linhas
                if alvo in self.nome_setor(f.get("sector_id")).lower()
                or alvo in str(self.setores().get(str(f.get("sector_id") or ""), {}).get("code", "")).lower()
            ]
        return [self._chamado_publico(f) for f in linhas[:limite]]

    def _chamado_publico(self, f: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": f.get("id"),
            "quando": hora_local(f.get("created_at")),
            "ha_minutos": minutos_desde(f.get("created_at")),
            "urgencia": "Crítico" if f.get("urgency") in CRITICOS else f.get("urgency"),
            "categoria": f.get("category"),
            "setor": self.nome_setor(f.get("sector_id")),
            "status": f.get("status"),
            "mensagem": str(f.get("message") or "")[:400],
        }

    def respostas_do_tuca(self, limite: int = 10) -> list[dict[str, Any]]:
        """Pares mensagem do participante e resposta do bot, para julgar a qualidade."""

        limite = max(1, min(int(limite or 10), 25))
        feedbacks = self._rows(
            self.store.table("feedbacks")
            .select("id,message,category,urgency,status,created_at,sector_id")
            .eq("event_id", self._event_id())
            .order("created_at", desc=True)
            .limit(limite)
        )
        if not feedbacks:
            return []
        ids = [int(f["id"]) for f in feedbacks]
        respostas = self._rows(
            self.store.table("outbound_messages")
            .select("feedback_id,content,delivery_status,origin,last_error,created_at")
            .eq("event_id", self._event_id())
            .in_("feedback_id", ids)
            .order("created_at")
        )
        por_feedback: dict[int, list[dict[str, Any]]] = {}
        for r in respostas:
            por_feedback.setdefault(int(r["feedback_id"]), []).append(r)

        pares = []
        for f in feedbacks:
            item = self._chamado_publico(f)
            item["respostas"] = [
                {
                    "quem": "equipe" if r.get("origin") == "operator" else "Tuca",
                    "texto": str(r.get("content") or "")[:600],
                    "entrega": r.get("delivery_status"),
                    "erro": r.get("last_error"),
                }
                for r in por_feedback.get(int(f["id"]), [])
            ]
            pares.append(item)
        return pares

    def erros(self, horas: int | None = None, limite: int = 10) -> dict[str, Any]:
        """Falhas de processamento e de entrega na janela, com o erro registrado."""

        horas = max(1, int(horas or JANELA_ERROS_HORAS))
        limite = max(1, min(int(limite or 10), 30))
        inicio = agora() - timedelta(hours=horas)

        entrada = self._rows(
            self.store.table("message_inbox")
            .select("id,processing_status,attempts,last_error,created_at,updated_at,message_type")
            .eq("event_id", self._event_id())
            .eq("processing_status", "failed")
            .gte("updated_at", iso(inicio))
            .order("updated_at", desc=True)
            .limit(limite)
        )
        saida = self._rows(
            self.store.table("outbound_messages")
            .select("id,delivery_status,attempts,last_error,failed_at,created_at,provider_message_id,feedback_id")
            .eq("event_id", self._event_id())
            .in_("delivery_status", ["failed", "cancelled"])
            .gte("updated_at", iso(inicio))
            .order("updated_at", desc=True)
            .limit(limite)
        )
        return {
            "janela_horas": horas,
            "processamento_falhou": [
                {
                    "quando": hora_local(r.get("updated_at")),
                    "tipo": r.get("message_type"),
                    "tentativas": r.get("attempts"),
                    "esgotou": int(r.get("attempts") or 0) >= max_tentativas(),
                    "erro": r.get("last_error"),
                }
                for r in entrada
            ],
            "entrega_falhou": [
                {
                    "quando": hora_local(r.get("failed_at") or r.get("created_at")),
                    "chamado": r.get("feedback_id"),
                    "estado": r.get("delivery_status"),
                    "tentativas": r.get("attempts"),
                    "meta_aceitou": bool(r.get("provider_message_id")),
                    "erro": r.get("last_error"),
                }
                for r in saida
            ],
        }

    def saude(self) -> dict[str, Any]:
        """Estado das peças: app, banco, worker, Meta e IA."""

        return {
            "app": self._checar_app(),
            "worker": self._estado_worker(),
            "meta": self._checar_meta(),
            "ia": self._checar_ia(),
            "verificado_em": hora_local(iso(agora())),
        }

    # ------------------------------------------------------------------
    # Sinais individuais (cada um isolado para o teste e para a varredura)
    # ------------------------------------------------------------------
    def _checar_app(self) -> dict[str, Any]:
        try:
            resposta = requests.get(self.health_url, timeout=10)
            corpo = resposta.json() if resposta.content else {}
            return {
                "ok": resposta.status_code == 200,
                "http": resposta.status_code,
                "status": corpo.get("status"),
                "banco": corpo.get("database"),
                "configuracao": corpo.get("configuration"),
                "no_ar_desde": hora_local(corpo.get("started_at")) if corpo.get("started_at") else None,
            }
        except Exception as exc:  # noqa: BLE001 - diagnóstico nunca derruba o agente
            return {"ok": False, "erro": type(exc).__name__}

    def _inbox_esperando(self) -> list[dict[str, Any]]:
        """Mensagens prontas para o worker há mais tempo que o tolerável."""

        limite = agora() - timedelta(minutes=ESPERA_WORKER_MIN)
        return self._rows(
            self.store.table("message_inbox")
            .select("id,created_at,next_attempt_at,attempts,processing_status")
            .eq("event_id", self._event_id())
            .in_("processing_status", ["pending", "failed"])
            .lt("attempts", max_tentativas())
            .lte("next_attempt_at", iso(limite))
            .order("next_attempt_at")
            .limit(200)
        )

    def _inbox_pendentes(self) -> int:
        linhas = self._rows(
            self.store.table("message_inbox")
            .select("id")
            .eq("event_id", self._event_id())
            .eq("processing_status", "pending")
            .limit(1000)
        )
        return len(linhas)

    def _inbox_presas(self) -> list[dict[str, Any]]:
        """Mensagens em 'processing' há tempo demais: o worker caiu no meio."""

        limite = agora() - timedelta(minutes=PRESA_PROCESSANDO_MIN)
        return self._rows(
            self.store.table("message_inbox")
            .select("id,updated_at,attempts")
            .eq("event_id", self._event_id())
            .eq("processing_status", "processing")
            .lte("updated_at", iso(limite))
            .limit(200)
        )

    def _inbox_esgotadas(self) -> list[dict[str, Any]]:
        """Mensagens que falharam todas as tentativas nas últimas horas."""

        inicio = agora() - timedelta(hours=JANELA_ERROS_HORAS)
        return self._rows(
            self.store.table("message_inbox")
            .select("id,last_error,updated_at,attempts")
            .eq("event_id", self._event_id())
            .eq("processing_status", "failed")
            .gte("attempts", max_tentativas())
            .gte("updated_at", iso(inicio))
            .limit(200)
        )

    def _saidas_canceladas(self) -> list[dict[str, Any]]:
        inicio = agora() - timedelta(hours=JANELA_ERROS_HORAS)
        return self._rows(
            self.store.table("outbound_messages")
            .select("id,last_error,provider_message_id,failed_at,feedback_id")
            .eq("event_id", self._event_id())
            .eq("delivery_status", "cancelled")
            .gte("updated_at", iso(inicio))
            .limit(200)
        )

    def _criticos_abertos(self, minutos: int | None = None) -> list[dict[str, Any]]:
        limite = agora() - timedelta(minutes=CRITICO_SEM_ATENDIMENTO_MIN if minutos is None else minutos)
        linhas = self._rows(
            self.store.table("feedbacks")
            .select("id,message,topic,urgency,status,created_at,sector_id")
            .eq("event_id", self._event_id())
            .eq("status", "aberto")
            .lte("created_at", iso(limite))
            .order("created_at")
            .limit(200)
        )
        return [f for f in linhas if f.get("urgency") in CRITICOS]

    def criticos_desde(self, momento: datetime) -> list[dict[str, Any]]:
        """Chamados críticos criados depois de um instante (vigia rápida)."""

        linhas = self._rows(
            self.store.table("feedbacks")
            .select("id,message,topic,urgency,status,created_at,sector_id")
            .eq("event_id", self._event_id())
            .gt("created_at", iso(momento))
            .order("created_at")
            .limit(50)
        )
        return [self._chamado_publico(f) for f in linhas if f.get("urgency") in CRITICOS]

    def _estado_worker(self) -> dict[str, Any]:
        esperando = self._inbox_esperando()
        presas = self._inbox_presas()
        mais_antiga = minutos_desde(esperando[0]["next_attempt_at"]) if esperando else 0
        return {
            "ok": not esperando and not presas,
            "esperando_worker": len(esperando),
            "espera_max_min": mais_antiga,
            "presas_processando": len(presas),
            "pendentes_total": self._inbox_pendentes(),
        }

    def _checar_meta(self) -> dict[str, Any]:
        token = os.getenv("META_ACCESS_TOKEN", "")
        numero = os.getenv("META_PHONE_NUMBER_ID", "")
        if not token or not numero:
            return {"ok": None, "detalhe": "sem META_ACCESS_TOKEN ou META_PHONE_NUMBER_ID no agente"}
        try:
            from meta_whatsapp import MetaWhatsAppClient, graph_api_version

            cliente = MetaWhatsAppClient(token, numero, graph_api_version())
            detalhe = cliente.check_credentials()
            return {"ok": detalhe.startswith("ok"), "detalhe": detalhe}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "detalhe": f"Falha ao consultar a Meta: {type(exc).__name__}"}

    def _checar_ia(self) -> dict[str, Any]:
        chave = os.getenv("OPENAI_API_KEY", "")
        modelo = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")
        if not chave:
            return {"ok": None, "detalhe": "sem OPENAI_API_KEY: o Tuca responde com textos fixos"}
        try:
            from openai import OpenAI

            OpenAI(api_key=chave, timeout=10).models.retrieve(modelo)
            return {"ok": True, "modelo": modelo}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "modelo": modelo, "detalhe": type(exc).__name__}

    # ------------------------------------------------------------------
    # Varredura
    # ------------------------------------------------------------------
    def varrer(self) -> list[Achado]:
        """Roda todos os sinais e devolve só o que está errado."""

        achados: list[Achado] = []
        for checagem in (
            self._achado_app,
            self._achado_worker,
            self._achado_presas,
            self._achado_esgotadas,
            self._achado_fila,
            self._achado_nao_entregues,
            self._achado_criticos,
            self._achado_meta,
            self._achado_ia,
        ):
            try:
                achado = checagem()
            except Exception as exc:  # noqa: BLE001 - uma checagem quebrada não cala as outras
                logger.error("Checagem %s falhou | erro=%s", checagem.__name__, type(exc).__name__)
                continue
            if achado:
                achados.append(achado)
        return achados

    def _achado_app(self) -> Achado | None:
        app = self._checar_app()
        if app.get("ok"):
            return None
        return Achado(
            chave="app_fora",
            gravidade="critico",
            titulo="O app não responde ao health check",
            detalhe=(
                f"HTTP {app.get('http')} | status {app.get('status')} | banco {app.get('banco')} "
                f"| configuração {app.get('configuracao')}"
                if "http" in app else f"Sem resposta: {app.get('erro')}"
            ) + "\nSem o app, a Meta não consegue entregar as mensagens do público e o webhook devolve erro. "
            "Confira o serviço web no Coolify e as variáveis exigidas pelo /health.",
            investigar=True,
        )

    def _achado_worker(self) -> Achado | None:
        esperando = self._inbox_esperando()
        if not esperando:
            return None
        mais_antiga = minutos_desde(esperando[0]["next_attempt_at"])
        return Achado(
            chave="worker_parado",
            gravidade="critico",
            titulo="Mensagens esperando e o worker não pega",
            detalhe=(
                f"{len(esperando)} mensagem(ns) prontas há até {mais_antiga} min sem ninguém processar. "
                "O participante mandou e não recebeu resposta. Normalmente é o serviço worker parado: "
                "reinicie-o no Coolify e confira o log de start (credenciais da Meta e Supabase)."
            ),
            quantidade=len(esperando),
            investigar=True,
        )

    def _achado_presas(self) -> Achado | None:
        presas = self._inbox_presas()
        if not presas:
            return None
        return Achado(
            chave="presas_processando",
            gravidade="atencao",
            titulo="Mensagens presas em processamento",
            detalhe=(
                f"{len(presas)} mensagem(ns) ficaram marcadas como 'em processamento' há mais de "
                f"{PRESA_PROCESSANDO_MIN} min. Isso acontece quando o worker reinicia no meio de uma. "
                "Elas não voltam sozinhas para a fila. Posso devolvê-las para o worker processar de novo."
            ),
            acao="destravar_processando",
            quantidade=len(presas),
        )

    def _achado_esgotadas(self) -> Achado | None:
        esgotadas = self._inbox_esgotadas()
        if not esgotadas:
            return None
        erros = sorted({str(r.get("last_error") or "sem detalhe") for r in esgotadas})[:3]
        return Achado(
            chave="mensagens_esgotadas",
            gravidade="atencao",
            titulo="Mensagens que falharam todas as tentativas",
            detalhe=(
                f"{len(esgotadas)} mensagem(ns) do público esgotaram as {max_tentativas()} tentativas "
                f"nas últimas {JANELA_ERROS_HORAS}h e ficaram sem resposta. Erro registrado: {'; '.join(erros)}. "
                "Se a causa já passou (IA ou Meta fora do ar), posso dar uma nova chance a elas."
            ),
            acao="nova_chance_inbox",
            quantidade=len(esgotadas),
            investigar=True,
        )

    def _achado_fila(self) -> Achado | None:
        pendentes = self._inbox_pendentes()
        if pendentes < FILA_ACUMULADA:
            return None
        return Achado(
            chave="fila_acumulada",
            gravidade="atencao",
            titulo="Fila de entrada acumulando",
            detalhe=(
                f"{pendentes} mensagens pendentes de uma vez. O worker está vivo mas não dá conta, "
                "ou a IA está lenta. Acompanhe: se continuar subindo, suba mais um worker no Coolify."
            ),
            quantidade=pendentes,
        )

    def _achado_nao_entregues(self) -> Achado | None:
        canceladas = self._saidas_canceladas()
        if not canceladas:
            return None
        reenviaveis = [c for c in canceladas if not c.get("provider_message_id")]
        recusadas = [c for c in canceladas if c.get("provider_message_id")]
        erros = sorted({str(c.get("last_error") or "sem detalhe") for c in canceladas})[:3]
        # Recusa da Meta por condição do participante (janela de 24h fechada,
        # número fora do WhatsApp) não é bug: não vale acordar a nuvem por isso.
        so_condicao_do_participante = bool(canceladas) and not reenviaveis and all(
            any(codigo in str(c.get("last_error") or "") for codigo in META_ERROS_DO_PARTICIPANTE)
            for c in canceladas
        )
        partes = [f"{len(canceladas)} resposta(s) do Tuca não chegaram ao participante nas últimas {JANELA_ERROS_HORAS}h."]
        if reenviaveis:
            partes.append(f"{len(reenviaveis)} nem foram aceitas pela Meta (posso reenviar).")
        if recusadas:
            partes.append(f"{len(recusadas)} a Meta aceitou e depois recusou (reenviar não resolve; veja o erro).")
        partes.append(f"Erro registrado: {'; '.join(erros)}.")
        return Achado(
            chave="respostas_nao_entregues",
            gravidade="critico" if len(canceladas) >= 5 else "atencao",
            titulo="Respostas do Tuca não entregues",
            detalhe=" ".join(partes),
            acao="reenviar_cancelados" if reenviaveis else None,
            quantidade=len(canceladas),
            investigar=not so_condicao_do_participante,
        )

    def _achado_criticos(self) -> Achado | None:
        criticos = self._criticos_abertos()
        if not criticos:
            return None
        linhas = [
            f"#{f['id']} {self.nome_setor(f.get('sector_id'))} ({minutos_desde(f.get('created_at'))} min): "
            f"{str(f.get('topic') or f.get('message') or '')[:80]}"
            for f in criticos[:5]
        ]
        return Achado(
            chave="criticos_sem_atendimento",
            gravidade="critico",
            titulo="Chamados críticos sem ninguém atender",
            detalhe=(
                f"{len(criticos)} chamado(s) crítico(s) abertos há mais de {CRITICO_SEM_ATENDIMENTO_MIN} min:\n"
                + "\n".join(linhas)
                + "\nAlguém da sala de controle precisa assumir no painel."
            ),
            quantidade=len(criticos),
        )

    def _achado_meta(self) -> Achado | None:
        meta = self._checar_meta()
        if meta.get("ok") is not False:
            return None
        return Achado(
            chave="meta_credenciais",
            gravidade="critico",
            titulo="A Meta recusou as credenciais do WhatsApp",
            detalhe=(
                f"{meta.get('detalhe')}\nSem isso o Tuca não envia resposta nenhuma. "
                "Gere um token novo no usuário do sistema da Meta e atualize META_ACCESS_TOKEN no Coolify."
            ),
        )

    def _achado_ia(self) -> Achado | None:
        ia = self._checar_ia()
        if ia.get("ok") is not False:
            return None
        return Achado(
            chave="ia_fora",
            gravidade="atencao",
            titulo="A IA não está respondendo",
            detalhe=(
                f"Modelo {ia.get('modelo')} | erro {ia.get('detalhe')}\n"
                "O Tuca continua no ar com as respostas fixas e a classificação por palavras-chave, "
                "mas perde o jeito de gente. Confira a chave e o modelo liberado no projeto da OpenAI."
            ),
            investigar=True,
        )

    # ------------------------------------------------------------------
    # Correções: só o que está no catálogo, todas idempotentes
    # ------------------------------------------------------------------
    def destravar_processando(self) -> str:
        presas = self._inbox_presas()
        if not presas:
            return "Nenhuma mensagem presa em processamento agora."
        ids = [str(r["id"]) for r in presas]
        self.store.table("message_inbox").update({
            "processing_status": "pending",
            "next_attempt_at": iso(agora()),
        }).in_("id", ids).eq("processing_status", "processing").execute()
        return f"{len(ids)} mensagem(ns) devolvida(s) para a fila. O worker processa em segundos."

    def nova_chance_inbox(self) -> str:
        esgotadas = self._inbox_esgotadas()
        if not esgotadas:
            return "Nenhuma mensagem esgotada para reprocessar."
        ids = [str(r["id"]) for r in esgotadas]
        self.store.table("message_inbox").update({
            "processing_status": "pending",
            "attempts": 0,
            "next_attempt_at": iso(agora()),
            "processed_at": None,
        }).in_("id", ids).eq("processing_status", "failed").execute()
        return f"{len(ids)} mensagem(ns) receberam nova chance. Se a causa continuar, elas falham de novo e eu aviso."

    def reenviar_cancelados(self) -> str:
        reenviaveis = [c for c in self._saidas_canceladas() if not c.get("provider_message_id")]
        if not reenviaveis:
            return "Nenhuma resposta cancelada que a Meta ainda não tenha visto."
        ids = [str(r["id"]) for r in reenviaveis]
        self.store.table("outbound_messages").update({
            "delivery_status": "queued",
            "attempts": 0,
            "next_attempt_at": iso(agora()),
        }).in_("id", ids).eq("delivery_status", "cancelled").execute()
        return f"{len(ids)} resposta(s) voltaram para a fila de envio."

    def corrigir(self, acao: str) -> str:
        """Executa uma correção do catálogo e devolve o que aconteceu."""

        entrada = CORRECOES.get(acao)
        if not entrada:
            return f"Não conheço a correção '{acao}'."
        _, executor = entrada
        try:
            return executor(self)
        except Exception as exc:  # noqa: BLE001 - o resultado vai para o Telegram, nunca uma stack
            logger.error("Correção %s falhou | erro=%s", acao, type(exc).__name__)
            return f"A correção falhou: {type(exc).__name__}. Nada foi alterado pela metade: cada uma é um único update."


# Catálogo: id -> (o que o botão diz, função). O agente só executa o que está aqui.
CORRECOES: dict[str, tuple[str, Callable[[Monitor], str]]] = {
    "destravar_processando": ("Devolver para a fila", Monitor.destravar_processando),
    "nova_chance_inbox": ("Dar nova chance", Monitor.nova_chance_inbox),
    "reenviar_cancelados": ("Reenviar respostas", Monitor.reenviar_cancelados),
}


class RegistroDeAlertas:
    """Guarda no Supabase o que já foi avisado e o que a equipe decidiu."""

    def __init__(self, store: EventStore) -> None:
        self.store = store

    def abertos(self) -> list[dict[str, Any]]:
        response = (
            self.store.table("agent_alerts")
            .select("*")
            .eq("event_id", self.store.event_id())
            .eq("status", "aberto")
            .order("created_at", desc=True)
            .execute()
        )
        return list(response.data or [])

    def ignorados_recentes(self, horas: int = 6) -> set[str]:
        inicio = agora() - timedelta(hours=horas)
        response = (
            self.store.table("agent_alerts")
            .select("chave")
            .eq("event_id", self.store.event_id())
            .eq("status", "ignorado")
            .gte("updated_at", iso(inicio))
            .execute()
        )
        return {str(r["chave"]) for r in (response.data or [])}

    def recentes(self, limite: int = 10) -> list[dict[str, Any]]:
        response = (
            self.store.table("agent_alerts")
            .select("*")
            .eq("event_id", self.store.event_id())
            .order("created_at", desc=True)
            .limit(max(1, min(int(limite or 10), 50)))
            .execute()
        )
        return list(response.data or [])

    def por_chave(self, chave: str) -> dict[str, Any] | None:
        """O alerta mais recente com essa chave, em qualquer status."""

        response = (
            self.store.table("agent_alerts")
            .select("*")
            .eq("event_id", self.store.event_id())
            .eq("chave", chave)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        return (response.data or [None])[0]

    def anotar_issue(self, alerta_id: str, numero: int) -> None:
        self.store.table("agent_alerts").update({"github_issue": int(numero)}).eq("id", alerta_id).execute()

    def por_id(self, alerta_id: str) -> dict[str, Any] | None:
        response = (
            self.store.table("agent_alerts")
            .select("*")
            .eq("id", alerta_id)
            .limit(1)
            .execute()
        )
        return (response.data or [None])[0]

    def abrir(self, achado: Achado) -> dict[str, Any]:
        response = (
            self.store.table("agent_alerts")
            .insert({
                "event_id": self.store.event_id(),
                "chave": achado.chave,
                "gravidade": achado.gravidade,
                "titulo": achado.titulo[:300],
                "detalhe": achado.detalhe[:4000],
                "acao": achado.acao,
            })
            .execute()
        )
        return (response.data or [{}])[0]

    def anotar_mensagem(self, alerta_id: str, chat_id: Any, message_id: Any) -> None:
        self.store.table("agent_alerts").update({
            "telegram_chat_id": str(chat_id),
            "telegram_message_id": str(message_id),
        }).eq("id", alerta_id).execute()

    def fechar(self, alerta_id: str, status: str, resultado: str | None = None, por: str | None = None) -> None:
        dados: dict[str, Any] = {"status": status, "resolved_at": iso(agora())}
        if resultado is not None:
            dados["resultado"] = resultado[:2000]
        if por:
            dados["decidido_por"] = por[:120]
        self.store.table("agent_alerts").update(dados).eq("id", alerta_id).execute()
