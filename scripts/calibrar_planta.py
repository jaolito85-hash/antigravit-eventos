# -*- coding: utf-8 -*-
"""Ferramenta local para marcar na planta onde fica cada setor.

Coordenada é a única coisa da planta que nenhum script deduz: ela sai de
olhar a arte e clicar. Esta ferramenta existe para isso não virar 65 pares de
números estimados no olho, que foi o erro que a planta atual evitou marcando
um por um ("conferidas uma a uma desenhando os pinos sobre a imagem").

Como usar:

    python scripts/calibrar_planta.py

Abre em http://127.0.0.1:8123. Clique no ponto da planta e ele grava a
coordenada do setor selecionado, em porcentagem da arte, já pulando para o
próximo da fila. Cada clique salva em disco na hora
(`scripts/calibragem/coordenadas.json`), então fechar o navegador não perde
trabalho. No fim, o botão de migration devolve o SQL pronto.

O servidor responde só nos caminhos declarados aqui e não lista diretório:
nada fora da planta e da própria ferramenta é servido.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PASTA = RAIZ / "scripts" / "calibragem"
SETORES_JSON = PASTA / "setores.json"
COORDENADAS_JSON = PASTA / "coordenadas.json"
INDEX_HTML = PASTA / "index.html"
PLANTA = RAIZ / "static" / "planta-tropicadelia-oficial.jpg"
MIGRATION_ANTIGA = RAIZ / "supabase" / "migrations" / "20260919210000_setores_planta_oficial.sql"
EVENTO = "tropicadelia-2026"
PORTA = 8123


def carregar_setores() -> list[dict]:
    if not SETORES_JSON.exists():
        raise SystemExit(
            "Rode antes: python scripts/derivar_setores.py\n"
            f"(falta {SETORES_JSON.relative_to(RAIZ)})"
        )
    return json.loads(SETORES_JSON.read_text(encoding="utf-8"))["setores"]


def carregar_coordenadas() -> dict:
    if COORDENADAS_JSON.exists():
        return json.loads(COORDENADAS_JSON.read_text(encoding="utf-8"))
    return {}


def salvar_coordenadas(coords: dict) -> None:
    COORDENADAS_JSON.write_text(
        json.dumps(coords, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def planta_atual() -> list[dict]:
    """Os 36 pinos que já estão no ar, como referência visual de escala.

    Eles aparecem em cinza no fundo. Nenhuma coordenada é herdada automa-
    ticamente: nome parecido em posição parecida é exatamente como se criam
    pares errados.
    """

    if not MIGRATION_ANTIGA.exists():
        return []
    texto = MIGRATION_ANTIGA.read_text(encoding="utf-8")
    achados = re.findall(
        r"\n            '([A-Z0-9\-]+)',\n            '([^']+)',\n            '(\{.*?\})'",
        texto,
        re.S,
    )
    saida = []
    for code, name, meta in achados:
        try:
            dados = json.loads(meta)
        except json.JSONDecodeError:
            continue
        coord = dados.get("coord") or {}
        if coord.get("x") is not None:
            saida.append({"code": code, "name": name, "coord": coord})
    return saida


def gerar_migration(setores: list[dict], coords: dict) -> str:
    hoje = date.today().strftime("%d/%m/%Y")
    posicionados = [s for s in setores if s["code"] in coords]
    faltando = [s["code"] for s in setores if s["code"] not in coords]

    linhas = [
        f"-- Setores oficiais da Tropicadelia 2026, lista da diretoria de 23/09/2026.",
        f"-- Gerado por scripts/calibrar_planta.py em {hoje}.",
        "--",
        "-- As coordenadas são porcentagem sobre a arte oficial",
        "-- (static/planta-tropicadelia-oficial.jpg) e foram marcadas clicando uma a",
        "-- uma sobre a imagem, não estimadas.",
    ]
    if faltando:
        linhas += [
            "--",
            f"-- ATENÇÃO: {len(faltando)} setor(es) ainda sem posição na planta. Eles entram",
            "-- no banco e recebem chamado pelo QR, mas não acendem pino no mapa:",
            *[f"--   {c}" for c in faltando],
        ]
    linhas += [
        "",
        "insert into public.event_sectors (event_id, code, name, active, metadata)",
        "select",
        "    e.id,",
        "    v.code,",
        "    v.name,",
        "    true,",
        "    v.metadata::jsonb",
        "from public.events e",
        "cross join (",
        "    values",
    ]

    valores = []
    for setor in setores:
        meta = {
            "zone": setor.get("zona"),
            "group": setor.get("grupo"),
            "team": setor.get("equipe"),
            "cta": setor.get("cta"),
            "priority": "normal",
        }
        coord = coords.get(setor["code"])
        if coord:
            meta["coord"] = {"x": coord["x"], "y": coord["y"]}
        meta = {k: v for k, v in meta.items() if v is not None}
        nome = setor["name"].replace("'", "''")
        meta_txt = json.dumps(meta, ensure_ascii=False).replace("'", "''")
        valores.append(
            f"        (\n            '{setor['code']}',\n"
            f"            '{nome}',\n            '{meta_txt}'\n        )"
        )
    linhas.append(",\n".join(valores))

    codigos = ", ".join(f"'{s['code']}'" for s in setores)
    linhas += [
        ") as v(code, name, metadata)",
        f"where e.slug = '{EVENTO}'",
        "on conflict (event_id, code) do update",
        "set name = excluded.name,",
        "    metadata = excluded.metadata,",
        "    active = true,",
        "    updated_at = now();",
        "",
        "-- Os setores da planta anterior saem do mapa sem serem apagados: chamado de",
        "-- teste aponta para esses códigos e apagar quebraria o histórico.",
        "update public.event_sectors s",
        "set active = false,",
        "    updated_at = now()",
        "from public.events e",
        "where s.event_id = e.id",
        f"  and e.slug = '{EVENTO}'",
        f"  and s.code not in ({codigos});",
        "",
    ]
    return "\n".join(linhas)


def sem_acento(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )


class Handler(BaseHTTPRequestHandler):
    def log_message(self, formato, *args):  # silencia o log de cada request
        pass

    def _envia(self, corpo: bytes, tipo: str, status: int = 200, extra=None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        for chave, valor in (extra or {}).items():
            self.send_header(chave, valor)
        self.end_headers()
        self.wfile.write(corpo)

    def _json(self, dados, status: int = 200) -> None:
        self._envia(
            json.dumps(dados, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
            status,
        )

    def do_GET(self):  # noqa: N802
        rota = self.path.split("?")[0]
        if rota in ("/", "/index.html"):
            self._envia(INDEX_HTML.read_bytes(), "text/html; charset=utf-8")
        elif rota == "/planta.jpg":
            self._envia(PLANTA.read_bytes(), "image/jpeg")
        elif rota == "/api/dados":
            self._json({
                "setores": carregar_setores(),
                "coordenadas": carregar_coordenadas(),
                "referencia": planta_atual(),
            })
        elif rota == "/api/migration":
            sql = gerar_migration(carregar_setores(), carregar_coordenadas())
            self._envia(
                sql.encode("utf-8"),
                "text/plain; charset=utf-8",
                extra={"Content-Disposition":
                       'attachment; filename="setores_planta_oficial.sql"'},
            )
        else:
            self._json({"erro": "rota desconhecida"}, 404)

    def do_POST(self):  # noqa: N802
        tamanho = int(self.headers.get("Content-Length") or 0)
        try:
            corpo = json.loads(self.rfile.read(tamanho) or b"{}")
        except json.JSONDecodeError:
            return self._json({"erro": "json inválido"}, 400)

        codigo = str(corpo.get("code") or "").strip()
        if not codigo:
            return self._json({"erro": "setor não informado"}, 400)

        coords = carregar_coordenadas()
        if self.path == "/api/coord":
            try:
                x = round(float(corpo["x"]), 1)
                y = round(float(corpo["y"]), 1)
            except (KeyError, TypeError, ValueError):
                return self._json({"erro": "coordenada inválida"}, 400)
            if not (0 <= x <= 100 and 0 <= y <= 100):
                return self._json({"erro": "coordenada fora da planta"}, 400)
            coords[codigo] = {"x": x, "y": y}
        elif self.path == "/api/limpar":
            coords.pop(codigo, None)
        else:
            return self._json({"erro": "rota desconhecida"}, 404)

        salvar_coordenadas(coords)
        self._json({"ok": True, "total": len(coords)})


def main() -> None:
    setores = carregar_setores()
    coords = carregar_coordenadas()
    print(f"Setores a posicionar: {len(setores)}")
    print(f"Já posicionados:      {len(coords)}")
    print(f"Planta:               {PLANTA.relative_to(RAIZ)}")
    print(f"\nAbra http://127.0.0.1:{PORTA}  (Ctrl+C para encerrar)")
    ThreadingHTTPServer(("127.0.0.1", PORTA), Handler).serve_forever()


if __name__ == "__main__":
    main()
