# -*- coding: utf-8 -*-
"""Põe no banco os setores da planta, a partir da mesma fonte da migration.

Por que existe, em vez de rodar o .sql: o projeto fala com o Supabase pela API,
não por conexão direta de Postgres, e é essa a via disponível aqui. O arquivo
em `supabase/migrations/` continua sendo o registro versionado do que foi
aplicado; este script apenas executa o mesmo efeito, lendo os mesmos dois
arquivos que geraram aquele SQL, para não existir chance de o banco ficar
diferente do que está escrito no repositório.

O que ele faz, na ordem:

1. insere ou atualiza os setores da planta (a chave é o código, então rodar de
   novo corrige em vez de duplicar);
2. desativa os setores que não estão mais na planta, sem apagar: chamado antigo
   aponta para eles e apagar quebraria o histórico.

    python scripts/aplicar_setores.py --conferir   (só mostra o que faria)
    python scripts/aplicar_setores.py
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from event_store import EventStore  # noqa: E402

SETORES_JSON = RAIZ / "scripts" / "calibragem" / "setores.json"
COORDENADAS_JSON = RAIZ / "scripts" / "calibragem" / "coordenadas.json"


def montar_linhas(event_id: str) -> list[dict]:
    setores = json.loads(SETORES_JSON.read_text(encoding="utf-8"))["setores"]
    coords = json.loads(COORDENADAS_JSON.read_text(encoding="utf-8"))
    agora = datetime.now(timezone.utc).isoformat()

    linhas = []
    for setor in setores:
        metadata = {
            "zone": setor.get("zona"),
            "group": setor.get("grupo"),
            "team": setor.get("equipe"),
            "cta": setor.get("cta"),
            "priority": "normal",
        }
        coord = coords.get(setor["code"])
        if coord:
            metadata["coord"] = {"x": coord["x"], "y": coord["y"]}
        linhas.append({
            "event_id": event_id,
            "code": setor["code"],
            "name": setor["name"],
            "active": True,
            "metadata": {k: v for k, v in metadata.items() if v is not None},
            "updated_at": agora,
        })
    return linhas


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--conferir", action="store_true",
                        help="mostra o que mudaria e não escreve nada")
    args = parser.parse_args()

    store = EventStore()
    client = store._get_client()
    event_id = store.event_id()

    antes = store.list_sectors()
    linhas = montar_linhas(event_id)
    novos = {linha["code"] for linha in linhas}
    ativos_antes = {s["code"] for s in antes}

    entram = sorted(novos - ativos_antes)
    saem = sorted(ativos_antes - novos)
    ficam = sorted(novos & ativos_antes)

    print(f"Evento: {event_id}")
    print(f"  ativos hoje:        {len(ativos_antes)}")
    print(f"  entram na planta:   {len(entram)}")
    print(f"  já existiam:        {len(ficam)}")
    print(f"  saem do mapa:       {len(saem)} (desativados, não apagados)")
    sem_coord = [linha["code"] for linha in linhas if "coord" not in linha["metadata"]]
    print(f"  sem coordenada:     {len(sem_coord)} {sem_coord}")

    if args.conferir:
        print("\n(--conferir: nada foi escrito)")
        return 0

    client.table("event_sectors").upsert(
        linhas, on_conflict="event_id,code"
    ).execute()

    if saem:
        (
            client.table("event_sectors")
            .update({"active": False,
                     "updated_at": datetime.now(timezone.utc).isoformat()})
            .eq("event_id", event_id)
            .in_("code", saem)
            .execute()
        )

    depois = EventStore().list_sectors()
    com_coord = sum(1 for s in depois if (s.get("metadata") or {}).get("coord"))
    print(f"\nDepois: {len(depois)} setores ativos, {com_coord} com coordenada")
    faltando = novos - {s["code"] for s in depois}
    if faltando:
        print(f"ATENÇÃO: não entraram: {sorted(faltando)}")
        return 1
    sobrando = {s["code"] for s in depois} - novos
    if sobrando:
        print(f"ATENÇÃO: continuam ativos sem estar na planta: {sorted(sobrando)}")
        return 1
    print("O banco está igual à planta.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
