"""Popula o evento com feedbacks de demonstração para ensaio do telão.

Todo registro criado aqui recebe ``source='manual'`` e ``metadata.demo = true``,
o que permite remover 100% da massa de teste sem tocar em dados reais.

Uso:
    python execution/seed_demo_tropicadelia.py          # insere a massa de demo
    python execution/seed_demo_tropicadelia.py --clear  # remove só a massa de demo
    python execution/seed_demo_tropicadelia.py --status # conta o que existe hoje
"""

from __future__ import annotations

import hashlib
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
# Os códigos são os da planta oficial de 19/09/2026.
FIXTURES: list[tuple[str, str, str, str, str]] = [
    ("ACESSO-CATRACAS-SUL", "Fila da catraca andando rápido, equipe muito atenciosa!", "Positivo", "Credenciamento & Ingressos", "aberto"),
    ("SAIDA-LOUNGE-EXCURSOES", "Desembarque da excursão foi tranquilo, já estamos dentro", "Positivo", "Credenciamento & Ingressos", "aberto"),
    ("PALCO-TROPICAL", "Que abertura sensacional, som cristalino aqui na pista!", "Positivo", "Programação & Atrações", "aberto"),
    ("PALCO-TROPICAL", "Show incrível, melhor festival que já vim na vida", "Positivo", "Programação & Atrações", "aberto"),
    ("PALCO-HYPE", "A arena do Hype tá bombando, DJ mandando muito bem", "Positivo", "Programação & Atrações", "aberto"),
    ("PRACA-ALIMENTACAO", "Comida da praça muito boa e o preço é justo", "Positivo", "Alimentação & Bebidas", "aberto"),
    ("FEIRINHA-TATTOO", "Adorei a feirinha, comprei uma camiseta linda", "Positivo", "Experiência Geral", "aberto"),
    ("AREA-DESCANSO", "A área de descanso salvou minhas pernas, obrigado!", "Positivo", "Experiência Geral", "aberto"),
    ("NY-LOUNGE", "O deck do NY Lounge tá com uma vibe ótima, bem tranquilo", "Positivo", "Experiência Geral", "aberto"),
    ("ALAMEDA-GASTRONOMICA", "O hambúrguer da alameda tá show de bola", "Positivo", "Alimentação & Bebidas", "aberto"),
    ("LOJINHA-OFICIAL", "Peguei o copo oficial na lojinha, ficou muito bonito", "Positivo", "Experiência Geral", "aberto"),

    ("WC-FEM-PALCO", "Banheiro feminino sem papel higiênico em quase todas as cabines", "Urgente", "Estrutura & Espaço", "aberto"),
    ("WC-FEM-PALCO", "Fila do banheiro feminino está gigante, umas 40 pessoas", "Urgente", "Estrutura & Espaço", "em_andamento"),
    ("WC-PISTA-NORTE-1", "Banheiro da pista norte alagado, piso escorregando", "Urgente", "Estrutura & Espaço", "aberto"),
    ("BAR-BUDWEISER-PISTA", "Bar da pista sem gelo, cerveja saindo quente", "Urgente", "Alimentação & Bebidas", "aberto"),
    ("BAR-DESTILADOS-2", "Fila do open bar travada, só um atendente no balcão", "Urgente", "Alimentação & Bebidas", "em_andamento"),
    ("BAR-DESTILADOS-1", "Acabou o limão e a cachaça no galpão 1", "Urgente", "Alimentação & Bebidas", "resolvido"),
    ("WC-MASC-PALCO", "Banheiro masculino precisando de limpeza urgente", "Urgente", "Estrutura & Espaço", "resolvido"),
    ("PALCO-TROPICAL", "Som do palco com microfonia forte, tá estourando", "Urgente", "Estrutura & Espaço", "em_andamento"),
    ("LOCKERS", "Meu locker não abre, o cadeado travou", "Urgente", "Estrutura & Espaço", "aberto"),
    ("ACESSO-CATRACAS-SUL", "Leitor de QR da catraca caiu, fila parada aqui", "Urgente", "Credenciamento & Ingressos", "resolvido"),

    ("PCD-PLATAFORMA-TROPICAL", "Pessoa passou mal na plataforma PCD, precisa de atendimento médico", "Critico", "Segurança & Organização", "em_andamento"),
    ("PALCO-TROPICAL", "Tumulto perto da grade, muita gente se empurrando na frente do palco", "Critico", "Segurança & Organização", "aberto"),

    ("SAC-ACHADOS-PERDIDOS", "Perdi minha carteira perto da praça de alimentação, como faço?", "Neutro", "Segurança & Organização", "aberto"),
    ("PALCO-HYPE", "Que horas começa o show principal no palco Hype?", "Neutro", "Programação & Atrações", "aberto"),
    ("PRACA-ALIMENTACAO", "Tem opção vegetariana na praça de alimentação?", "Neutro", "Alimentação & Bebidas", "aberto"),
    ("PCD-RETIRADA-PULSEIRA", "Onde eu retiro a pulseira PCD e até que horas?", "Neutro", "Segurança & Organização", "aberto"),
    ("WC-LOUNGE-BOSQUE", "Onde fica o banheiro mais próximo do bosque?", "Neutro", "Estrutura & Espaço", "aberto"),
    ("UPGRADE-PULSEIRA", "Consigo fazer upgrade da pulseira ainda hoje?", "Neutro", "Credenciamento & Ingressos", "aberto"),
    ("OPEN-FOOD-1", "O Open Food do galpão 1 aceita cartão?", "Neutro", "Alimentação & Bebidas", "aberto"),
]

# Respostas de exemplo, no tom que a IA usa, para a tela do chamado mostrar
# a troca completa. Variam por indice para nao parecerem copiadas.
RESPOSTAS_DEMO = {
    "Critico": [
        "🚨 Recebemos seu alerta e ele foi marcado como prioridade máxima. "
        "Se houver risco imediato, procure agora a segurança ou equipe médica mais próxima.",
    ],
    "Urgente": [
        "Putz, que perrengue! 😤 Já tô passando pra equipe resolver isso AGORA. "
        "Segura aí que eles estão indo!",
        "Eita, valeu por avisar! 🙏 Já acionei a galera responsável, "
        "deve resolver em poucos minutos.",
        "Ihhh, isso não pode mesmo! 😠 Time acionado, "
        "obrigado por me contar em vez de guardar pra você.",
    ],
    "Positivo": [
        "AAAAA que bom ouvir isso!! 🔥 Tô preso nos bastidores morrendo de inveja, "
        "aproveita muito por mim!",
        "Uhuuul, é isso!! 🎶 Que delícia saber que tá curtindo, "
        "manda mais quando quiser!",
        "Caraca, obrigado!! 😍 Vou mostrar isso pra equipe que montou tudo, "
        "eles vão amar saber.",
    ],
    "Neutro": [
        "Boa pergunta! 😎 Já anotei aqui e a equipe te responde rapidinho. "
        "Qualquer coisa me chama de novo!",
        "Show, anotei! 👍 Se precisar de mais alguma coisa, "
        "é só mandar mensagem aqui.",
    ],
}

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
            # Hash de 64 caracteres como o HMAC real, senao a tabela de
            # atendimento recusa a conversa pela restricao de tamanho.
            "sender_hash": hashlib.sha256(f"demo-{index:03d}".encode()).hexdigest(),
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

    inseridos = client.table("feedbacks").insert(rows).execute().data or []
    print(f"OK: {len(inseridos)} feedbacks de demonstração inseridos no evento '{EVENT_SLUG}'.")

    # Cada chamado ganha a resposta que o bot teria enviado, para a tela do
    # chamado mostrar a troca completa. O destinatário é fictício de propósito:
    # nada aqui pode sair para um telefone de verdade.
    respostas = []
    for i, feedback in enumerate(inseridos):
        urgencia = feedback.get("urgency", "Neutro")
        opcoes = RESPOSTAS_DEMO.get(urgencia) or RESPOSTAS_DEMO["Neutro"]
        respostas.append({
            "event_id": event_id,
            "feedback_id": feedback["id"],
            "provider": "meta",
            "channel_account_id": "demo",
            "recipient": f"demo-{i:03d}",
            "message_type": "text",
            "content": opcoes[i % len(opcoes)],
            "origin": "bot",
            "idempotency_key": f"demo:{feedback['id']}:reply",
            "delivery_status": "delivered",
            "sent_at": feedback.get("timestamp"),
            "delivered_at": feedback.get("timestamp"),
        })

    if respostas:
        client.table("outbound_messages").insert(respostas).execute()
        print(f"OK: {len(respostas)} respostas do bot gravadas para a demonstração.")

    print("Abra /telao para ver a planta acesa. Para limpar depois: --clear")


def clear() -> None:
    """Remove apenas os registros marcados como demonstração."""

    client = _client()
    event_id = _event_id(client)
    # As respostas saem primeiro: apagar o feedback antes deixaria a linha da
    # caixa de saída órfã, porque a chave estrangeira só anula o vínculo.
    saida = (
        client.table("outbound_messages")
        .delete()
        .eq("event_id", event_id)
        .like("idempotency_key", "demo:%")
        .execute()
    )

    response = (
        client.table("feedbacks")
        .delete()
        .eq("event_id", event_id)
        .eq("source", "manual")
        .contains("metadata", DEMO_MARKER)
        .execute()
    )
    print(f"OK: {len(response.data or [])} feedbacks de demonstração removidos.")
    print(f"OK: {len(saida.data or [])} respostas de demonstração removidas.")


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
