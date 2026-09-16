import os
import sys
import json
import requests
from dotenv import load_dotenv

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

load_dotenv()

URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
KEY = (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY") or "").strip()
EVENT_SLUG = os.getenv("EVENT_SLUG", "tropicadelia-2026").strip()

def verify():
    print("==================================================")
    print("🔍 VERIFICAÇÃO DE INTEGRIDADE SUPABASE")
    print("==================================================")

    if not URL or not KEY or "your-project" in URL:
        print("⚠️  AVISO: Credenciais do Supabase não configuradas no .env!")
        print("👉 Abra o arquivo .env e preencha:")
        print("   SUPABASE_URL=https://<seu-projeto>.supabase.co")
        print("   SUPABASE_SERVICE_ROLE_KEY=<sua-service-role-key>")
        return False

    headers = {
        "apikey": KEY,
        "Authorization": f"Bearer {KEY}",
        "Content-Type": "application/json",
        "Prefer": "count=exact"
    }

    print(f"📡 Conectando a: {URL}")
    print(f"🎫 Event Slug: {EVENT_SLUG}")
    print("--------------------------------------------------")

    # 1. Verificar tabela events
    try:
        res = requests.get(f"{URL}/rest/v1/events?slug=eq.{EVENT_SLUG}&select=*", headers=headers, timeout=12)
        if res.status_code != 200:
            print(f"❌ Erro ao consultar public.events (HTTP {res.status_code}): {res.text}")
            return False

        events = res.json()
        if not events:
            print(f"⚠️  Tabela 'events' acessada, mas o evento '{EVENT_SLUG}' não foi encontrado.")
            print("   Execute a migração '20260915173601_secure_event_schema.sql' primeiro.")
            return False

        event = events[0]
        event_id = event.get("id")
        print(f"✅ Evento encontrado: '{event.get('name')}' (ID: {event_id})")

    except Exception as e:
        print(f"❌ Falha de conexão com o Supabase: {e}")
        return False

    # 2. Verificar setores da planta
    try:
        res = requests.get(
            f"{URL}/rest/v1/event_sectors?event_id=eq.{event_id}&select=code,name,metadata,active",
            headers=headers,
            timeout=12
        )
        if res.status_code == 200:
            sectors = res.json()
            total_sectors = len(sectors)
            print(f"📍 Setores cadastrados no banco: {total_sectors}/26")
            if total_sectors == 26:
                print("✅ Todos os 26 setores da Planta Tropicadelia estão migrados e ativos!")
            elif total_sectors > 0:
                print(f"⚠️  Apenas {total_sectors} setores encontrados. Recomenda-se aplicar '20260916180000_seed_tropicadelia_sectors.sql'.")
            else:
                print("ℹ️  Nenhum setor cadastrado ainda. Aplique '20260916180000_seed_tropicadelia_sectors.sql'.")
        else:
            print(f"❌ Erro ao consultar event_sectors (HTTP {res.status_code}): {res.text}")

    except Exception as e:
        print(f"❌ Erro ao consultar setores: {e}")

    # 3. Verificar tabelas operacionais do schema
    tables = [
        ("config", "Configurações de categorias e cores"),
        ("feedbacks", "Feedbacks, sentimentos e ocorrências operacionais"),
        ("outbound_messages", "Fila de respostas e notificações enviadas"),
        ("feedback_status_history", "Histórico de auditoria de status"),
        ("event_members", "Operadores e administradores vinculados")
    ]

    for tbl, desc in tables:
        try:
            r = requests.get(f"{URL}/rest/v1/{tbl}?select=*&limit=1", headers=headers, timeout=10)
            if r.status_code in (200, 206):
                count = r.headers.get("content-range", "").split("/")[-1]
                print(f"✅ Tabela '{tbl}' ({desc}): Ativa (Total registros: {count or '0'})")
            else:
                print(f"⚠️  Tabela '{tbl}': HTTP {r.status_code} - {r.text}")
        except Exception as e:
            print(f"❌ Tabela '{tbl}': Falha - {e}")

    print("==================================================")
    return True

if __name__ == "__main__":
    verify()
