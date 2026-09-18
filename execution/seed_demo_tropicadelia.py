"""Popula o evento com feedbacks de demonstração para ensaio do telão.

Todo registro criado aqui recebe ``source='manual'`` e ``metadata.demo = true``,
o que permite remover 100% da massa de teste sem tocar em dados reais.

Uso:
    python execution/seed_demo_tropicadelia.py          # insere a massa de demo
    python execution/seed_demo_tropicadelia.py --clear  # remove só a massa de demo
    python execution/seed_demo_tropicadelia.py --status # conta o que existe hoje
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

EVENT_SLUG = os.getenv("EVENT_SLUG", "tropicadelia-2026")
DEMO_MARKER = {"demo": True}

# (código do setor, mensagem, urgência, categoria, status)
# Curado de propósito: a demo precisa ser previsível na frente do cliente.
FIXTURES: list[tuple[str, str, str, str, str]] = [
    ("ACESSO-CREDENCIAMENTO", "Fila do credenciamento andando rápido, equipe muito atenciosa!", "Positivo", "Credenciamento & Ingressos", "aberto"),
    ("ACESSO-EXCURSOES", "Desembarque da excursão foi tranquilo, já estamos dentro", "Positivo", "Credenciamento & Ingressos", "aberto"),
    ("PALCO-PRINCIPAL", "Que abertura sensacional, som cristalino aqui na pista!", "Positivo", "Programação & Atrações", "aberto"),
    ("PALCO-PRINCIPAL", "Show incrível, melhor festival que já vim na vida", "Positivo", "Programação & Atrações", "aberto"),
    ("PALCO-HYPE", "A arena coberta tá bombando, DJ mandando muito bem", "Positivo", "Programação & Atrações", "aberto"),
    ("PRACA-ALIMENTACAO", "Comida da praça muito boa e o preço é justo", "Positivo", "Alimentação & Bebidas", "aberto"),
    ("FEIRINHA-TATTOO", "Adorei a feirinha, comprei uma camiseta linda", "Positivo", "Experiência Geral", "aberto"),
    ("DESCANSO-BAMBOO", "Lounge de descanso salvou minhas pernas, obrigado!", "Positivo", "Experiência Geral", "aberto"),
    ("PALCO-3", "Palco 3 com uma vibe ótima, bem menos cheio", "Positivo", "Programação & Atrações", "aberto"),
    ("ALAMEDA-FOODTRUCKS", "O hambúrguer da alameda tá show de bola", "Positivo", "Alimentação & Bebidas", "aberto"),

    ("WC-FEM-PRINCIPAL", "Banheiro feminino sem papel higiênico em quase todas as cabines", "Urgente", "Estrutura & Espaço", "aberto"),
    ("WC-FEM-PRINCIPAL", "Fila do banheiro feminino está gigante, umas 40 pessoas", "Urgente", "Estrutura & Espaço", "em_andamento"),
    ("WC-PISTA-NORTE", "Banheiro da pista norte alagado, piso escorregando", "Urgente", "Estrutura & Espaço", "aberto"),
    ("BAR-CELEIRO-P1", "Bar celeiro sem gelo, cerveja saindo quente", "Urgente", "Alimentação & Bebidas", "aberto"),
    ("BAR-06-PALCO-HYPE", "Fila do bar 06 travada, só um atendente no balcão", "Urgente", "Alimentação & Bebidas", "em_andamento"),
    ("DESTILADOS-P2", "Acabou o limão e a cachaça no destilados ala 2", "Urgente", "Alimentação & Bebidas", "resolvido"),
    ("WC-MASC-CENTRAL", "Banheiro masculino central precisando de limpeza urgente", "Urgente", "Estrutura & Espaço", "resolvido"),
    ("PALCO-PRINCIPAL-HOUSEMIX", "Som do house mix com microfonia forte, tá estourando", "Urgente", "Estrutura & Espaço", "em_andamento"),
    ("LOCKERS-CENTRAL", "Meu locker não abre, cadeado travou", "Urgente", "Estrutura & Espaço", "aberto"),
    ("ACESSO-CREDENCIAMENTO", "Leitor de QR da portaria caiu, fila parada aqui", "Urgente", "Credenciamento & Ingressos", "resolvido"),

    ("PALCO-PRINCIPAL-PCD", "Pessoa passou mal na plataforma PCD, precisa de atendimento médico", "Critico", "Segurança & Organização", "em_andamento"),
    ("PALCO-PRINCIPAL", "Tumulto perto da grade, muita gente se empurrando na frente do palco", "Critico", "Segurança & Organização", "aberto"),

    ("CCO-ACHADOS-PERDIDOS", "Perdi minha carteira perto da praça de alimentação, como faço?", "Neutro", "Segurança & Organização", "aberto"),
    ("PALCO-HYPE", "Que horas começa o show principal no palco hype?", "Neutro", "Programação & Atrações", "aberto"),
    ("PRACA-ALIMENTACAO", "Tem opção vegetariana na praça de alimentação?", "Neutro", "Alimentação & Bebidas", "aberto"),
    ("ACESSO-PCD", "O portão PCD funciona até que horas hoje?", "Neutro", "Segurança & Organização", "aberto"),
    ("WC-PALCO-3", "Onde fica o banheiro mais próximo do palco 3?", "Neutro", "Estrutura & Espaço", "aberto"),
    ("BAR-CELEIRO-P2", "Vocês aceitam pix no bar ou só ficha?", "Neutro", "Alimentação & Bebidas", "aberto"),
]

SENTIMENT_BY_URGENCY = {
    "Positivo": "Positivo",
    "Critico": "Negativo",
    "Urgente": "Negativo",
    "Neutro": "Neutro",
}


def _client():
    """Cria o cliente Supabase exigindo a service role do backend."""

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        sys.exit("SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY são obrigatórios no .env")
    return create_client(url, key)


def _event_id(client) -> str:
    """Resolve o evento configurado pelo slug."""

    response = client.table("events").select("id").eq("slug", EVENT_SLUG).limit(1).execute()
    if not response.data:
        sys.exit(f"Evento '{EVENT_SLUG}' não existe. Rode as migrações primeiro.")
    return str(response.data[0]["id"])


def _sectors(client, event_id: str) -> dict[str, dict]:
    """Indexa os setores ativos por código para ligar cada feedback à planta."""

    response = (
        client.table("event_sectors")
        .select("id,code,name")
        .eq("event_id", event_id)
        .eq("active", True)
        .execute()
    )
    return {row["code"]: row for row in (response.data or [])}


def _topic(message: str, category: str, urgency: str) -> str:
    """Rótulo curto para os cards e para o Top 3 do dashboard."""

    lowered = message.lower()
    if "banheiro" in lowered:
        return "Banheiro Sujo" if urgency == "Urgente" else "Banheiro"
    if "fila" in lowered:
        return "Fila"
    if "som" in lowered or "microfonia" in lowered:
        return "Som"
    if "show" in lowered or "dj" in lowered or "palco" in lowered:
        return "Show"
    if "gelo" in lowered or "cerveja" in lowered or "comida" in lowered or "hambúrguer" in lowered:
        return "Alimentação"
    return category


def seed() -> None:
    """Insere a massa de demonstração distribuída nas últimas 5 horas."""

    client = _client()
    event_id = _event_id(client)
    sectors = _sectors(client, event_id)

    if not sectors:
        sys.exit("Nenhum setor cadastrado. Rode a migração dos setores da Tropicadelia.")

    now = datetime.now(timezone.utc)
    total = len(FIXTURES)
    rows = []
    faltando = []

    for index, (code, message, urgency, category, status) in enumerate(FIXTURES):
        sector = sectors.get(code)
        if not sector:
            faltando.append(code)
            continue

        # Distribui do mais antigo ao mais recente, adensando o fim da noite.
        minutes_ago = int(300 * (1 - index / total) ** 1.6)
        occurred = now - timedelta(minutes=minutes_ago)

        rows.append({
            "event_id": event_id,
            "sector_id": sector["id"],
            "sender": None,
            "sender_hash": f"demo-{index:03d}",
            "name": "Anônimo",
            "message": message,
            "category": category,
            "region": sector["name"],
            "urgency": urgency,
            "sentiment": SENTIMENT_BY_URGENCY[urgency],
            "topic": _topic(message, category, urgency),
            "status": status,
            "resolved_at": occurred.isoformat() if status == "resolvido" else None,
            "timestamp": occurred.isoformat(),
            "updated_at": occurred.isoformat(),
            "source": "manual",
            "metadata": DEMO_MARKER,
        })

    if faltando:
        print(f"Aviso: setores não encontrados e ignorados: {', '.join(sorted(set(faltando)))}")

    client.table("feedbacks").insert(rows).execute()
    print(f"OK: {len(rows)} feedbacks de demonstração inseridos no evento '{EVENT_SLUG}'.")
    print("Abra /telao para ver a planta acesa. Para limpar depois: --clear")


def clear() -> None:
    """Remove apenas os registros marcados como demonstração."""

    client = _client()
    event_id = _event_id(client)
    response = (
        client.table("feedbacks")
        .delete()
        .eq("event_id", event_id)
        .eq("source", "manual")
        .contains("metadata", DEMO_MARKER)
        .execute()
    )
    print(f"OK: {len(response.data or [])} feedbacks de demonstração removidos.")


def status() -> None:
    """Mostra quantos registros são reais e quantos são de demonstração."""

    client = _client()
    event_id = _event_id(client)
    todos = client.table("feedbacks").select("id", count="exact").eq("event_id", event_id).execute()
    demo = (
        client.table("feedbacks")
        .select("id", count="exact")
        .eq("event_id", event_id)
        .contains("metadata", DEMO_MARKER)
        .execute()
    )
    sectors = _sectors(client, event_id)
    print(f"Evento:        {EVENT_SLUG}")
    print(f"Setores:       {len(sectors)}")
    print(f"Feedbacks:     {todos.count or 0}")
    print(f"  demo:        {demo.count or 0}")
    print(f"  reais:       {(todos.count or 0) - (demo.count or 0)}")


if __name__ == "__main__":
    if "--clear" in sys.argv:
        clear()
    elif "--status" in sys.argv:
        status()
    else:
        seed()
