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

Depende de segno e reportlab (ferramentas de bancada, fora do requirements.txt
do app porque não rodam em produção):

    pip install segno reportlab
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
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
except ImportError:
    sys.exit("Faltam dependências. Rode: pip install segno reportlab")

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


def faixas(matriz: list[list[bool]]) -> list[tuple[int, int, int]]:
    """Agrupa módulos escuros vizinhos de cada linha em um retângulo só.

    Menos objetos no arquivo e, mais importante, sem a fresta de um micron
    que o RIP às vezes deixa entre dois quadrados encostados.
    """

    saida = []
    for y, linha in enumerate(matriz):
        x = 0
        while x < len(linha):
            if not linha[x]:
                x += 1
                continue
            inicio = x
            while x < len(linha) and linha[x]:
                x += 1
            saida.append((inicio, y, x - inicio))
    return saida


def desenha_qr(c: canvas.Canvas, matriz, modulo_mm: float, x0: float, y0: float) -> None:
    """Desenha o código em K 100%, com a origem no canto do símbolo.

    O eixo y do PDF cresce para cima e o da matriz para baixo, então cada
    linha é espelhada na hora de desenhar.
    """

    c.setFillColorCMYK(0, 0, 0, 1)
    c.setStrokeColorCMYK(0, 0, 0, 1)
    lado = len(matriz)
    for x, y, largura in faixas(matriz):
        c.rect(
            x0 + x * modulo_mm * mm,
            y0 + (lado - 1 - y) * modulo_mm * mm,
            largura * modulo_mm * mm,
            modulo_mm * mm,
            stroke=0,
            fill=1,
        )


def pdf_de_producao(destino: Path, matriz, modulo_mm: float, zona_mm: float, codigo: str, url: str) -> None:
    """O arquivo que entra na arte: só o código, do tamanho real, mais nada."""

    lado = len(matriz)
    total_mm = lado * modulo_mm + 2 * zona_mm
    c = canvas.Canvas(str(destino), pagesize=(total_mm * mm, total_mm * mm))
    c.setTitle(f"QR do setor {codigo} | {MARCA}")
    c.setAuthor(MARCA)
    c.setSubject(f"{url} | correcao H | modulo {modulo_mm:.3f} mm")
    c.setCreator(MARCA)

    # Zona de silêncio: branco é ausência de tinta, ou seja, a cor do
    # material. Por isso a especificação exige material branco embaixo do
    # código, e não fundo colorido da arte.
    c.setFillColorCMYK(0, 0, 0, 0)
    c.rect(0, 0, total_mm * mm, total_mm * mm, stroke=0, fill=1)

    desenha_qr(c, matriz, modulo_mm, zona_mm * mm, zona_mm * mm)
    c.showPage()
    c.save()


def pdf_de_prova(
    destino: Path, matriz, modulo_mm: float, zona_mm: float,
    codigo: str, nome: str, url: str, versao: int,
) -> None:
    """A folha que a gráfica imprime agora para testarmos a leitura.

    Leva régua de 100 mm porque o erro mais comum não é de arquivo: é alguém
    mandar imprimir com "ajustar à página" e o código sair fora de escala.
    Com a régua, uma trena resolve a dúvida em cinco segundos.
    """

    lado = len(matriz)
    total_mm = lado * modulo_mm + 2 * zona_mm
    largura_pg, altura_pg = A4

    c = canvas.Canvas(str(destino), pagesize=A4)
    c.setTitle(f"Prova de impressao | QR do setor {codigo} | {MARCA}")
    c.setAuthor(MARCA)
    c.setCreator(MARCA)

    c.setFillColorCMYK(0, 0, 0, 1)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(20 * mm, altura_pg - 20 * mm, "PROVA DE IMPRESSÃO")
    c.setFont("Helvetica", 9.5)
    c.drawString(20 * mm, altura_pg - 26 * mm, f"{MARCA}  |  setor {codigo}")
    c.drawString(20 * mm, altura_pg - 31 * mm, nome)

    c.setFont("Helvetica-Bold", 10)
    c.drawString(20 * mm, altura_pg - 42 * mm, "IMPRIMIR EM 100%. NÃO AJUSTAR À PÁGINA.")

    # O código em tamanho real, centralizado.
    x0 = (largura_pg - total_mm * mm) / 2 + zona_mm * mm
    y0 = altura_pg - 52 * mm - (total_mm - zona_mm) * mm
    desenha_qr(c, matriz, modulo_mm, x0, y0)

    # Régua de conferência: 100 mm exatos, com traço a cada 10.
    regua_y = y0 - 12 * mm
    regua_x = (largura_pg - 100 * mm) / 2
    c.setLineWidth(0.6)
    c.line(regua_x, regua_y, regua_x + 100 * mm, regua_y)
    for i in range(11):
        altura = 3.5 * mm if i % 5 == 0 else 2 * mm
        c.line(regua_x + i * 10 * mm, regua_y, regua_x + i * 10 * mm, regua_y + altura)
    c.setFont("Helvetica", 7.5)
    for i, rotulo in ((0, "0"), (5, "50 mm"), (10, "100 mm")):
        c.drawCentredString(regua_x + i * 10 * mm, regua_y + 5 * mm, rotulo)
    c.setFont("Helvetica", 8)
    c.drawCentredString(
        largura_pg / 2, regua_y - 5 * mm,
        "Esta régua tem 100 mm exatos. Se medir diferente, a impressão saiu fora de escala.",
    )

    texto = c.beginText(20 * mm, regua_y - 16 * mm)
    texto.setLeading(11)
    texto.setFont("Helvetica-Bold", 10)
    texto.textLine("Especificação deste código")
    texto.setFont("Helvetica", 9)
    for linha in [
        f"Lado do código: {lado * modulo_mm:.0f} mm    Com a margem branca: {total_mm:.1f} mm"
        f"    Módulo: {modulo_mm:.2f} mm",
        f"Correção de erro: H (30%)    Versão do QR: {versao}    Preto: K 100%, sem C, M ou Y",
        "",
        "Obrigatório na impressão final:",
        "1. Acabamento FOSCO. O evento é à noite, sob refletor e lanterna de celular,",
        "   e laminação brilhante devolve a luz na câmera e derruba a leitura.",
        "2. Preto sobre branco, nunca invertido. A arte pode ser escura, o quadrado do QR não.",
        "3. A margem branca ao redor do código é parte do arquivo. Nenhuma arte, moldura,",
        "   furo de fixação ou corte pode entrar nela.",
        "4. Não vetorizar nem redesenhar o código: ele já está em vetor.",
        "5. Uso externo, sol e chuva a noite inteira. Vinil ou PVC, superfície plana.",
        "",
        "Como aprovamos: escaneando no escuro, iPhone e Android, de frente e a 45 graus,",
        "a 30 cm e a 1 metro, dez tentativas. Passou nas dez, roda a tiragem.",
    ]:
        texto.textLine(linha)
    texto.setFont("Helvetica", 7)
    texto.textLine("")
    texto.textLine(f"Destino do código: {url}")
    c.drawText(texto)
    c.showPage()
    c.save()


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

    pdf_de_producao(producao, matriz, modulo_mm, zona_mm, codigo, url)
    pdf_de_prova(prova, matriz, modulo_mm, zona_mm, codigo, alvo["name"], url, versao)
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
