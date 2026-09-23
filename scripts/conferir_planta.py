# -*- coding: utf-8 -*-
"""Confere as posições marcadas na planta e desenha o mapa para olhar.

Clicar 63 pinos numa planta é trabalho manual, e trabalho manual erra de dois
jeitos que nenhuma tela mostra sozinha:

  pino sobreposto: dois setores no mesmo ponto, quase sempre um clique que
      caiu antes de a seleção mudar;
  pino fora do bairro: um setor de Backstage marcado no meio da Pista, que é
      o clique dado no lugar errado da planta.

O script mede os dois e gera uma imagem com todos os pinos desenhados, que é a
única forma de conferir de verdade: olhando.

    python scripts/conferir_planta.py
"""

from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SETORES = RAIZ / "scripts" / "calibragem" / "setores.json"
COORDENADAS = RAIZ / "scripts" / "calibragem" / "coordenadas.json"
PLANTA = RAIZ / "static" / "planta-tropicadelia-oficial.jpg"
SAIDA = RAIZ / "out" / "planta-conferencia.png"

# Abaixo disso dois pinos se tocam na tela do telão e viram um borrão.
DISTANCIA_MINIMA = 1.2  # em pontos percentuais da planta

CORES = {
    "Sanitários": (56, 189, 248),
    "Bares": (245, 158, 11),
    "Alimentação": (251, 113, 133),
    "Saúde": (239, 68, 68),
    "Caixas": (167, 139, 250),
    "Telões": (34, 211, 238),
    "Entradas e Acessos": (132, 204, 22),
    "Acessibilidade": (232, 121, 249),
    "Atendimento ao Público": (45, 212, 191),
    "Lojas e Feirinha": (251, 191, 36),
    "Ativações e Lazer": (192, 132, 252),
}


def distancia(a: dict, b: dict) -> float:
    return math.hypot(a["x"] - b["x"], a["y"] - b["y"])


def main() -> int:
    setores = json.loads(SETORES.read_text(encoding="utf-8"))["setores"]
    coords = json.loads(COORDENADAS.read_text(encoding="utf-8"))
    por_codigo = {s["code"]: s for s in setores}

    marcados = [s for s in setores if s["code"] in coords]
    faltando = [s["code"] for s in setores if s["code"] not in coords]

    print(f"Setores: {len(setores)} | com posição: {len(marcados)} | sem: {len(faltando)}")
    if faltando:
        for codigo in faltando:
            print(f"  sem posição: {codigo}  ({por_codigo[codigo]['name']})")

    # --- pinos colados ---
    colados = []
    for i, a in enumerate(marcados):
        for b in marcados[i + 1:]:
            d = distancia(coords[a["code"]], coords[b["code"]])
            if d < DISTANCIA_MINIMA:
                colados.append((d, a, b))
    print(f"\nPinos a menos de {DISTANCIA_MINIMA} da planta um do outro: {len(colados)}")
    for d, a, b in sorted(colados, key=lambda t: t[0]):
        mesma = "mesma zona" if a.get("zona") == b.get("zona") else "ZONAS DIFERENTES"
        print(f"  {d:.2f}  {a['code']} x {b['code']}  ({mesma})")

    # --- setor longe dos vizinhos de zona ---
    por_zona = defaultdict(list)
    for s in marcados:
        por_zona[s.get("zona") or "sem zona"].append(s)

    print("\nDistância de cada setor ao centro da sua zona:")
    for zona, lista in sorted(por_zona.items()):
        cx = sum(coords[s["code"]]["x"] for s in lista) / len(lista)
        cy = sum(coords[s["code"]]["y"] for s in lista) / len(lista)
        distancias = sorted(
            ((math.hypot(coords[s["code"]]["x"] - cx, coords[s["code"]]["y"] - cy), s)
             for s in lista),
            key=lambda t: -t[0],
        )
        media = sum(d for d, _ in distancias) / len(distancias)
        print(f"  {zona}: {len(lista)} setores, média {media:.1f}")
        for d, s in distancias[:2]:
            marca = "  <<< confira" if d > media * 2.2 else ""
            print(f"      mais longe: {d:5.1f}  {s['code']}{marca}")

    # --- desenho ---
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("\n(sem Pillow: pip install pillow para gerar a imagem de conferência)")
        return 0

    planta = Image.open(PLANTA).convert("RGB")
    largura, altura = planta.size
    escuro = Image.blend(planta, Image.new("RGB", planta.size, (0, 0, 0)), 0.45)
    desenho = ImageDraw.Draw(escuro)

    raio = max(6, largura // 220)
    for s in marcados:
        c = coords[s["code"]]
        x, y = c["x"] / 100 * largura, c["y"] / 100 * altura
        cor = CORES.get(s.get("grupo"), (255, 255, 255))
        desenho.ellipse([x - raio, y - raio, x + raio, y + raio], fill=cor,
                        outline=(255, 255, 255), width=max(2, raio // 4))
        desenho.text((x + raio + 4, y - raio), s["code"], fill=cor)

    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    escuro.save(SAIDA, "PNG")
    print(f"\nMapa de conferência: {SAIDA.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
