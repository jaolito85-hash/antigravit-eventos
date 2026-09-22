"""Gera o PDF do QR Code em CMYK, sem biblioteca de PDF.

Por que escrito à mão: o requisito difícil aqui é um só, o preto sair **K 100%
puro**. Preto convertido de RGB vira preto rico, com tinta nos quatro canais, e
aí qualquer desencontro de registro entre as chapas borra a borda do módulo e o
leitor perde o código. As bibliotecas de PDF em JavaScript trabalham em RGB, e
as de Python que fazem CMYK trazem binários junto, que é peso e risco de build
para o container de produção.

O PDF que a gente precisa é retângulo preto sobre página branca, sem imagem e
sem transparência. Escrever os operadores direto sai mais leve que a
dependência e deixa o arquivo auditável a olho, que é o que a gráfica pede
quando algo dá errado.
"""

from __future__ import annotations

PT_POR_MM = 72 / 25.4

# As duas únicas cores do arquivo. O branco é ausência de tinta, ou seja, a cor
# do material: por isso a especificação exige material branco sob o código, e
# não fundo colorido da arte.
PRETO = "0 0 0 1 k"
BRANCO = "0 0 0 0 k"


def _texto_pdf(valor: str) -> bytes:
    """Escapa uma string literal do PDF, em WinAnsi como a fonte declara."""

    bruto = valor.encode("cp1252", errors="replace")
    for alvo, troca in ((b"\\", b"\\\\"), (b"(", b"\\("), (b")", b"\\)")):
        bruto = bruto.replace(alvo, troca)
    return b"(" + bruto + b")"


def _documento(paginas: list[tuple[float, float, str]], com_fonte: bool, meta: dict) -> bytes:
    """Monta o arquivo com a tabela xref, que é o que torna o PDF legível.

    Cada página entra como (largura_pt, altura_pt, fluxo de operadores).
    """

    objetos: list[bytes] = []

    def adiciona(corpo: bytes) -> int:
        objetos.append(corpo)
        return len(objetos)

    fonte_normal = fonte_negrito = None
    if com_fonte:
        # Helvetica é uma das 14 fontes base do PDF: existe em qualquer leitor
        # e em qualquer RIP, então não precisa ser embutida nem convertida.
        fonte_normal = adiciona(
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
            b"/Encoding /WinAnsiEncoding >>"
        )
        fonte_negrito = adiciona(
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold "
            b"/Encoding /WinAnsiEncoding >>"
        )

    recursos = b"<< >>"
    if com_fonte:
        recursos = (
            b"<< /Font << /F1 %d 0 R /F2 %d 0 R >> >>" % (fonte_normal, fonte_negrito)
        )

    paginas_ref: list[int] = []
    conteudos: list[tuple[int, bytes]] = []
    for largura, altura, fluxo in paginas:
        dados = fluxo.encode("latin-1", errors="replace")
        conteudo = adiciona(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(dados), dados))
        pagina = adiciona(
            b"<< /Type /Page /Parent PAI 0 R /MediaBox [0 0 %.4f %.4f] "
            b"/Resources %s /Contents %d 0 R >>"
            % (largura, altura, recursos, conteudo)
        )
        paginas_ref.append(pagina)
        conteudos.append((pagina, dados))

    arvore = adiciona(
        b"<< /Type /Pages /Count %d /Kids [%s] >>"
        % (len(paginas_ref), b" ".join(b"%d 0 R" % n for n in paginas_ref))
    )
    # O número da árvore só existe depois que as páginas entram, então o
    # ponteiro para o pai é preenchido agora.
    for numero in paginas_ref:
        objetos[numero - 1] = objetos[numero - 1].replace(b"PAI", b"%d" % arvore)

    info = adiciona(
        b"<< /Title %s /Author %s /Subject %s /Creator %s /Producer %s >>"
        % (
            _texto_pdf(meta.get("titulo", "")),
            _texto_pdf(meta.get("autor", "")),
            _texto_pdf(meta.get("assunto", "")),
            _texto_pdf(meta.get("autor", "")),
            _texto_pdf(meta.get("autor", "")),
        )
    )
    catalogo = adiciona(b"<< /Type /Catalog /Pages %d 0 R >>" % arvore)

    saida = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for numero, corpo in enumerate(objetos, start=1):
        offsets.append(len(saida))
        saida += b"%d 0 obj\n" % numero + corpo + b"\nendobj\n"

    inicio_xref = len(saida)
    saida += b"xref\n0 %d\n" % (len(objetos) + 1)
    saida += b"0000000000 65535 f \n"
    for posicao in offsets:
        saida += b"%010d 00000 n \n" % posicao
    saida += (
        b"trailer\n<< /Size %d /Root %d 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
        % (len(objetos) + 1, catalogo, info, inicio_xref)
    )
    return bytes(saida)


def _faixas(matriz: list[list[bool]]):
    """Agrupa módulos escuros vizinhos de cada linha em um retângulo só.

    Menos objetos no arquivo e, mais importante, sem a fresta de um micron que
    o RIP às vezes deixa entre dois quadrados apenas encostados.
    """

    for y, linha in enumerate(matriz):
        x = 0
        while x < len(linha):
            if not linha[x]:
                x += 1
                continue
            inicio = x
            while x < len(linha) and linha[x]:
                x += 1
            yield inicio, y, x - inicio


def _desenha_qr(matriz, modulo_mm: float, x0_mm: float, y0_mm: float) -> list[str]:
    """Operadores do código, com a origem no canto inferior do símbolo.

    O eixo y do PDF cresce para cima e o da matriz para baixo, então cada linha
    é espelhada aqui.
    """

    lado = len(matriz)
    passo = modulo_mm * PT_POR_MM
    saida = [PRETO]
    for x, y, largura in _faixas(matriz):
        saida.append(
            "%.4f %.4f %.4f %.4f re f"
            % (
                x0_mm * PT_POR_MM + x * passo,
                y0_mm * PT_POR_MM + (lado - 1 - y) * passo,
                largura * passo,
                passo,
            )
        )
    return saida


def pdf_producao(
    matriz: list[list[bool]],
    modulo_mm: float,
    zona_mm: float,
    codigo: str,
    url: str,
    marca: str,
) -> bytes:
    """O arquivo que entra na arte: só o código, no tamanho real, mais nada."""

    lado_mm = len(matriz) * modulo_mm
    total_mm = lado_mm + 2 * zona_mm
    total_pt = total_mm * PT_POR_MM

    fluxo = [BRANCO, "0 0 %.4f %.4f re f" % (total_pt, total_pt)]
    fluxo += _desenha_qr(matriz, modulo_mm, zona_mm, zona_mm)

    return _documento(
        [(total_pt, total_pt, "\n".join(fluxo))],
        com_fonte=False,
        meta={
            "titulo": f"QR do setor {codigo} | {marca}",
            "autor": marca,
            "assunto": f"{url} | correcao H | modulo {modulo_mm:.3f} mm | preto K 100%",
        },
    )


def pdf_prova(
    matriz: list[list[bool]],
    modulo_mm: float,
    zona_mm: float,
    codigo: str,
    nome: str,
    url: str,
    versao: int,
    marca: str,
) -> bytes:
    """A folha A4 que a gráfica imprime para testarmos a leitura.

    Leva régua de 100 mm porque o erro mais comum não é de arquivo: é alguém
    mandar imprimir com "ajustar à página" e o código sair fora de escala. Com
    a régua, uma trena resolve a dúvida em cinco segundos.
    """

    largura_mm, altura_mm = 210.0, 297.0
    lado = len(matriz)
    lado_mm = lado * modulo_mm
    total_mm = lado_mm + 2 * zona_mm

    def escreve(x_mm, y_mm, texto, tamanho=9, negrito=False, centro=False):
        fonte = "/F2" if negrito else "/F1"
        x_pt = x_mm * PT_POR_MM
        if centro:
            # Largura média da Helvetica serve para centralizar sem tabela de
            # métricas: erro de um ou dois pontos não muda nada aqui.
            x_pt -= len(texto) * tamanho * 0.5 * 0.5
        return "BT %s %.2f Tf %.4f %.4f Td %s Tj ET" % (
            fonte, tamanho, x_pt, y_mm * PT_POR_MM,
            _texto_pdf(texto).decode("latin-1"),
        )

    fluxo = [BRANCO, "0 0 %.4f %.4f re f" % (largura_mm * PT_POR_MM, altura_mm * PT_POR_MM), PRETO]

    fluxo.append(escreve(20, altura_mm - 20, "PROVA DE IMPRESSÃO", 13, negrito=True))
    fluxo.append(escreve(20, altura_mm - 26, f"{marca}  |  setor {codigo}", 9.5))
    fluxo.append(escreve(20, altura_mm - 31, nome, 9.5))
    fluxo.append(
        escreve(20, altura_mm - 42, "IMPRIMIR EM 100%. NÃO AJUSTAR À PÁGINA.", 10, negrito=True)
    )

    # O código em tamanho real, centralizado.
    x0 = (largura_mm - total_mm) / 2 + zona_mm
    y0 = altura_mm - 52 - (total_mm - zona_mm)
    fluxo += _desenha_qr(matriz, modulo_mm, x0, y0)

    # Régua de conferência: 100 mm exatos, traço a cada 10.
    regua_y = y0 - 12
    regua_x = (largura_mm - 100) / 2
    fluxo.append("0.6 w")
    fluxo.append("%.4f %.4f m %.4f %.4f l S" % (
        regua_x * PT_POR_MM, regua_y * PT_POR_MM,
        (regua_x + 100) * PT_POR_MM, regua_y * PT_POR_MM,
    ))
    for i in range(11):
        altura = 3.5 if i % 5 == 0 else 2
        x = (regua_x + i * 10) * PT_POR_MM
        fluxo.append("%.4f %.4f m %.4f %.4f l S" % (
            x, regua_y * PT_POR_MM, x, (regua_y + altura) * PT_POR_MM,
        ))
    for i, rotulo in ((0, "0"), (5, "50 mm"), (10, "100 mm")):
        fluxo.append(escreve(regua_x + i * 10, regua_y + 5, rotulo, 7.5, centro=True))
    fluxo.append(escreve(
        largura_mm / 2, regua_y - 5,
        "Esta régua tem 100 mm exatos. Se medir diferente, a impressão saiu fora de escala.",
        8, centro=True,
    ))

    linhas = [
        ("Especificação deste código", 10, True),
        (f"Lado do código: {lado_mm:.0f} mm    Com a margem branca: {total_mm:.1f} mm"
         f"    Módulo: {modulo_mm:.2f} mm", 9, False),
        (f"Correção de erro: H (30%)    Versão do QR: {versao}"
         f"    Preto: K 100%, sem C, M ou Y", 9, False),
        ("", 9, False),
        ("Obrigatório na impressão final:", 9, False),
        ("1. Acabamento FOSCO. O evento é à noite, sob refletor e lanterna de celular,", 9, False),
        ("   e laminação brilhante devolve a luz na câmera e derruba a leitura.", 9, False),
        ("2. Preto sobre branco, nunca invertido. A arte pode ser escura, o quadrado do QR não.", 9, False),
        ("3. A margem branca ao redor do código é parte do arquivo. Nenhuma arte, moldura,", 9, False),
        ("   furo de fixação ou corte pode entrar nela.", 9, False),
        ("4. Não vetorizar nem redesenhar o código: ele já está em vetor.", 9, False),
        ("5. Uso externo, sol e chuva a noite inteira. Vinil ou PVC, superfície plana.", 9, False),
        ("", 9, False),
        ("Como aprovamos: escaneando no escuro, iPhone e Android, de frente e a 45 graus,", 9, False),
        ("a 30 cm e a 1 metro, dez tentativas. Passou nas dez, roda a tiragem.", 9, False),
        ("", 9, False),
        (f"Destino do código: {url}", 7, False),
    ]
    y = regua_y - 16
    for texto, tamanho, negrito in linhas:
        if texto:
            fluxo.append(escreve(20, y, texto, tamanho, negrito=negrito))
        y -= 3.9

    return _documento(
        [(largura_mm * PT_POR_MM, altura_mm * PT_POR_MM, "\n".join(fluxo))],
        com_fonte=True,
        meta={
            "titulo": f"Prova de impressao | QR do setor {codigo} | {marca}",
            "autor": marca,
            "assunto": url,
        },
    )
