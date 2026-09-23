# -*- coding: utf-8 -*-
"""Lê de volta cada QR gerado e confere se ele aponta para o setor certo.

Por que existe: trocar dois arquivos de lugar, ou gerar um código com a janela
da logo grande demais, não dá erro visível. O PDF abre, a arte fica bonita, a
placa é impressa, e o defeito só aparece no festival, com o chamado caindo no
setor errado ou o celular não lendo nada.

Este script decodifica o PNG de cada placa, que é o mesmo desenho do PDF, e
compara o conteúdo com o código que está no nome do arquivo.

    pip install zxing-cpp
    python scripts/conferir_placas.py
    python scripts/conferir_placas.py --pasta out/placas-marketing
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import unquote

RAIZ = Path(__file__).resolve().parent.parent

try:
    import zxingcpp
except ImportError:
    sys.exit("Falta o leitor. Rode: pip install zxing-cpp")

try:
    from PIL import Image
    import numpy as np
except ImportError:
    Image = None


def le_png(caminho: Path):
    """PNG cru em matriz, sem depender do Pillow.

    O container não tem Pillow e o projeto escreve PNG na mão por causa disso
    (logo_qrcode). Aqui o leitor aceita qualquer um dos dois caminhos: usa
    Pillow quando existe e cai no decodificador próprio quando não existe.
    """

    if Image is not None:
        return np.array(Image.open(caminho).convert("L"))

    import zlib

    bruto = caminho.read_bytes()
    assert bruto[:8] == b"\x89PNG\r\n\x1a\n", f"{caminho.name} não é PNG"
    pos, dados, largura, altura, cor, profundidade = 8, bytearray(), 0, 0, None, None
    while pos < len(bruto):
        tamanho = int.from_bytes(bruto[pos:pos + 4], "big")
        tipo = bruto[pos + 4:pos + 8]
        corpo = bruto[pos + 8:pos + 8 + tamanho]
        if tipo == b"IHDR":
            largura = int.from_bytes(corpo[0:4], "big")
            altura = int.from_bytes(corpo[4:8], "big")
            profundidade, cor = corpo[8], corpo[9]
        elif tipo == b"IDAT":
            dados += corpo
        elif tipo == b"IEND":
            break
        pos += 12 + tamanho

    assert profundidade == 8, "esperado 8 bits por canal"
    canais = {0: 1, 2: 3, 4: 2, 6: 4}[cor]
    linha_bytes = largura * canais
    puro = zlib.decompress(bytes(dados))
    saida = bytearray(largura * altura)
    anterior = bytearray(linha_bytes)
    for y in range(altura):
        inicio = y * (linha_bytes + 1)
        filtro = puro[inicio]
        linha = bytearray(puro[inicio + 1:inicio + 1 + linha_bytes])
        for i in range(linha_bytes):
            a = linha[i - canais] if i >= canais else 0
            b = anterior[i]
            c = anterior[i - canais] if i >= canais else 0
            if filtro == 1:
                linha[i] = (linha[i] + a) & 0xFF
            elif filtro == 2:
                linha[i] = (linha[i] + b) & 0xFF
            elif filtro == 3:
                linha[i] = (linha[i] + (a + b) // 2) & 0xFF
            elif filtro == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                previsto = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                linha[i] = (linha[i] + previsto) & 0xFF
        for x in range(largura):
            saida[y * largura + x] = linha[x * canais]
        anterior = linha
    return saida, largura, altura


def decodifica(caminho: Path) -> str | None:
    imagem = le_png(caminho)
    if Image is None:
        # O leitor quer uma matriz 2D; o decodificador próprio devolve os
        # pixels achatados, então a forma volta aqui.
        import numpy as np

        pixels, largura, altura = imagem
        imagem = np.frombuffer(bytes(pixels), dtype=np.uint8).reshape(altura, largura)
    achados = zxingcpp.read_barcodes(imagem)
    return achados[0].text if achados else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pasta", default="out/placas-marketing")
    args = parser.parse_args()

    base = RAIZ / args.pasta
    pngs = sorted(base.rglob("*.png"))
    if not pngs:
        sys.exit(f"Nenhum PNG em {base}")

    falhas, lidos, vistos = [], 0, {}
    for png in pngs:
        esperado = re.match(r"^([A-Z0-9][A-Z0-9_-]*)\s", png.name)
        if not esperado:
            falhas.append((png.name, "nome do arquivo não começa com o código"))
            continue
        codigo = esperado.group(1)

        conteudo = decodifica(png)
        if not conteudo:
            falhas.append((png.name, "o leitor NÃO conseguiu ler o código"))
            continue
        lidos += 1

        texto = unquote(conteudo)
        if f"#SETOR:{codigo}" not in texto:
            falhas.append((png.name, f"aponta para outro setor: {texto}"))
        if "api.whatsapp.com/send" not in texto and "wa.me/" not in texto:
            falhas.append((png.name, f"não abre o WhatsApp: {texto}"))
        if texto in vistos:
            falhas.append((png.name, f"código idêntico ao de {vistos[texto]}"))
        vistos[texto] = png.name

    print(f"Arquivos conferidos: {len(pngs)}")
    print(f"Lidos pelo leitor:   {lidos}")
    print(f"Conteúdos distintos: {len(vistos)}")
    if falhas:
        print(f"\nFALHAS: {len(falhas)}")
        for nome, motivo in falhas:
            print(f"  {nome}\n    {motivo}")
        return 1
    print("\nTodos leem, apontam para o próprio setor e nenhum se repete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
