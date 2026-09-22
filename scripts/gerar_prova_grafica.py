"""Monta o pacote de um setor para a gráfica imprimir a prova.

Por que não basta mandar o SVG: gráfica trabalha em CMYK, e preto convertido
automático de RGB vira preto rico (tinta nos quatro canais). Em QR Code isso
é fatal, porque qualquer desencontro de registro entre as chapas borra a
borda do módulo e o leitor perde o código. Aqui o preto sai K 100% puro,
sem uma gota de ciano, magenta ou amarelo.

Uso:
    python scripts/gerar_prova_grafica.py
    python scripts/gerar_prova_grafica.py --setor PALCO-TROPICAL

Sem --setor, escolhe o QR mais denso da planta: se o pior caso imprime e lê,
todos os outros imprimem e leem.

O PDF sai do módulo `pdf_qrcode`, o mesmo que o painel usa: uma implementação
só para o arquivo da bancada e o do botão nunca divergirem.

    pip install segno
"""

from __future__ import annotations

import argparse
import struct
import sys
import zlib
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

try:
    import segno
except ImportError:
    sys.exit("Falta o segno. Rode: pip install segno")

from pdf_qrcode import pdf_producao, pdf_prova  # noqa: E402
from scripts.generate_qrcodes import (  # noqa: E402
    carrega_setores,
    monta_svg,
    monta_url,
    numero_do_ambiente,
    zona_de_silencio,
)

MARCA = "Tuca | Tropicadelia 2026"


def matriz_do_qr(url: str) -> tuple[list[list[bool]], int]:
    """Codifica com correção H, o mesmo nível dos 36 arquivos de produção."""

    qr = segno.make(url, error="h", boost_error=False)
    return [[bool(m) for m in linha] for linha in qr.matrix], qr.version


def escreve_png(destino: Path, matriz, zona_mm: float, dpi: int, modulo_mm: float) -> None:
    """PNG de reserva, 1 bit, para fluxo que não aceita vetor.

    Escrito à mão para o pixel cair exatamente na borda do módulo: qualquer
    reamostragem por biblioteca de imagem borra a borda e come a margem de
    leitura que a correção H comprou.
    """

    lado = len(matriz)
    # Pixels por módulo arredondado para inteiro: meio pixel de módulo é
    # exatamente o tipo de erro que vira borda tremida na impressão.
    px = max(1, round(modulo_mm / 25.4 * dpi))
    zona_px = max(1, round(zona_mm / 25.4 * dpi))
    largura = lado * px + 2 * zona_px

    linhas = []
    for y in range(lado):
        bits = bytearray()
        atual = 0
        conta = 0

        def empurra(escuro: bool, vezes: int) -> None:
            nonlocal atual, conta
            for _ in range(vezes):
                atual = (atual << 1) | (0 if escuro else 1)
                conta += 1
                if conta == 8:
                    bits.append(atual)
                    atual = 0
                    conta = 0

        empurra(False, zona_px)
        for x in range(lado):
            empurra(matriz[y][x], px)
        empurra(False, zona_px)
        if conta:
            bits.append(atual << (8 - conta))
        linhas.append(bytes(bits))

    branca = bytes([0xFF] * ((largura + 7) // 8))
    corpo = (
        [b"\x00" + branca] * zona_px
        + [b"\x00" + linha for linha in linhas for _ in range(px)]
        + [b"\x00" + branca] * zona_px
    )
    bruto = b"".join(corpo)

    def parte(tipo: bytes, dados: bytes) -> bytes:
        return (
            struct.pack(">I", len(dados))
            + tipo
            + dados
            + struct.pack(">I", zlib.crc32(tipo + dados) & 0xFFFFFFFF)
        )

    altura = zona_px * 2 + lado * px
    ppm = int(round(dpi / 0.0254))
    destino.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + parte(b"IHDR", struct.pack(">IIBBBBB", largura, altura, 1, 0, 0, 0, 0))
        + parte(b"pHYs", struct.pack(">IIB", ppm, ppm, 1))
        + parte(b"IDAT", zlib.compress(bruto, 9))
        + parte(b"IEND", b"")
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Monta o pacote de prova de um setor.")
    parser.add_argument("--setor", default=None, help="Código do setor (padrão: o QR mais denso).")
    parser.add_argument("--lado", type=float, default=120.0, help="Lado do símbolo em mm.")
    parser.add_argument("--dpi", type=int, default=600, help="Resolução do PNG de reserva.")
    parser.add_argument("--saida", default="out/prova-gráfica", help="Diretório de saída.")
    args = parser.parse_args()

    numero = numero_do_ambiente()
    setores, origem = carrega_setores()
    if not setores:
        sys.exit("Nenhum setor ativo. Nada a gerar.")

    # Codifica a planta inteira mesmo quando a prova é de um setor só: a
    # margem branca tem que sair na mesma medida dos 36 arquivos finais,
    # senão a arte aprovada na prova não serve para o resto da tiragem.
    codificados = []
    for setor in setores:
        m, v = matriz_do_qr(monta_url(numero, setor["code"]))
        codificados.append((setor, m, v, args.lado / len(m)))

    if args.setor:
        escolhido = next(
            (c for c in codificados if c[0]["code"] == args.setor.upper()), None
        )
        if not escolhido:
            sys.exit(f"Setor {args.setor} não existe ou não está ativo.")
    else:
        # O pior caso: mais módulos, módulo menor, impressão mais exigente.
        escolhido = max(codificados, key=lambda c: len(c[1]))

    alvo, matriz, versao, modulo_mm = escolhido
    codigo = alvo["code"]
    url = monta_url(numero, codigo)
    lado = len(matriz)
    zona_mm = zona_de_silencio([c[3] for c in codificados])

    destino = RAIZ / args.saida
    destino.mkdir(parents=True, exist_ok=True)
    base = f"TUCA_QR_{codigo}"

    producao = destino / f"{base}_PRODUCAO.pdf"
    prova = destino / f"{base}_PROVA_A4.pdf"
    reserva = destino / f"{base}_reserva_{args.dpi}dpi.png"
    vetor = destino / f"{base}.svg"

    producao.write_bytes(
        pdf_producao(matriz, modulo_mm, zona_mm, codigo, url, MARCA)
    )
    prova.write_bytes(
        pdf_prova(matriz, modulo_mm, zona_mm, codigo, alvo["name"], url, versao, MARCA)
    )
    escreve_png(reserva, matriz, zona_mm, args.dpi, modulo_mm)
    vetor.write_text(
        monta_svg(
            matriz, borda=zona_mm / modulo_mm, modulo_mm=modulo_mm, codigo=codigo, url=url
        ),
        encoding="utf-8",
    )

    print(f"Setor:  {codigo} ({alvo['name']})")
    print(f"Origem: {origem}")
    print(f"QR:     versão {versao}, {lado}x{lado} módulos, módulo {modulo_mm:.3f} mm")
    print(f"Bloco:  {args.lado:.0f} mm de código + {zona_mm:.1f} mm de margem = "
          f"{lado * modulo_mm + 2 * zona_mm:.1f} mm\n")
    for arquivo in (producao, prova, reserva, vetor):
        print(f"  {arquivo.stat().st_size / 1024:7.1f} KB  {arquivo.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
