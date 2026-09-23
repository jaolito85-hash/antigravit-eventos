"""Abre a janela da logo no centro do QR e prepara a imagem para o PDF.

Por que isso tem risco de verdade: não existe espaço sobrando no meio de um QR
Code. O que permite cobrir um pedaço dele é a correção de erro, e as placas são
geradas em nível H, que recupera até 30% do conteúdo. Essa reserva não é
espaço livre: é a mesma reserva que cobre risco de faca, poeira, chuva, dedo
sujo e o reflexo do refletor no vinil às duas da manhã. Gastar metade dela na
logo é entregar uma placa que lê na mesa do escritório e falha no escuro.

Por isso a janela aqui é pequena, é medida por leitura real e não por palpite,
e o módulo se recusa a abrir janela em cima do que o leitor precisa para achar
a grade antes de ler qualquer bit: os três alvos dos cantos, as trilhas de
sincronismo e os alvos de alinhamento, com uma exceção medida para o alvo do
centro que está anotada em `_intervalo_proibido`. Errar nesses pontos não é
perder dados, é o celular não reconhecer que ali existe um código.

Por que ler e escrever PNG na mão em vez de usar Pillow: o container de
produção não tem Pillow, e não vale trazer uma dependência com binário
compilado junto para ler um arquivo de 4 KB uma vez por clique. PNG de 8 bits
sem entrelaçamento é zlib mais cinco filtros de linha, e é só isso que está
aqui. Escrever também, porque o painel precisa mostrar na tela o mesmo desenho
que vai para a gráfica, e isso quem sabe fazer é o servidor.

A conversão para CMYK é a aritmética simples de propósito, não por economia:
ela leva RGB(0,0,0) para K 100% com zero de C, M e Y, que é a exigência que
vale para o resto do arquivo. Logo em preto e branco sai numa chapa só, sem
risco de registro, e logo colorida não atrapalha a leitura porque a área dela
o leitor nem tenta interpretar, apenas recupera.
"""

from __future__ import annotations

import math
import os
import struct
import zlib
from dataclasses import dataclass

# Lado da janela da logo, em milímetros sobre a placa impressa. É medida de
# régua e não fração de módulo pelo mesmo motivo da margem branca: os 36
# setores caem em três versões diferentes de QR, e se a janela fosse contada em
# módulos a logo sairia de um tamanho diferente em cada placa, com a arte sendo
# a mesma. Em milímetros o designer recebe um número só.
JANELA_ALVO_MM = 30.0

# Trava de área, caso alguém reduza o lado impresso e os 30 mm virem metade da
# placa. Medido em 23/09 com leitura real: a logo não cobra em desfoque, em
# distância nem em ângulo, cobra na correção de erro, que é a mesma reserva que
# mantém a placa legível com risco de faca e respingo de bebida. Cobrindo até
# 11% da área a maior mancha tolerada continuou igual à do código limpo; de 14%
# para cima a reserva caiu um terço. O teto ficou em 10%, dentro do medido.
TETO_DE_AREA = 0.10

# Moldura branca entre a logo e o primeiro módulo preto. Sem ela o leitor tenta
# ler a borda da logo como módulo, e é aí que a leitura fica intermitente, o
# pior dos defeitos porque passa no teste e falha no evento.
FOLGA_MODULOS = 1

# Teto de resolução da imagem que entra no PDF. A janela impressa tem cerca de
# 30 mm, então 512 px já dá mais de 400 dpi, acima do que a gráfica usa. Acima
# disso o arquivo cresce sem nenhum ganho visível.
TETO_DE_PIXELS = 512


class LogoInviavel(Exception):
    """A logo não pode entrar neste código sem risco de derrubar a leitura."""


@dataclass(frozen=True)
class Logo:
    """A logo pronta para o PDF: CMYK de 8 bits, já comprimida, sem alfa."""

    largura_px: int
    altura_px: int
    dados: bytes
    lado_modulos: int
    largura_modulos: float
    altura_modulos: float


def _le_png(bruto: bytes) -> tuple[int, int, bytearray]:
    """Devolve (largura, altura, pixels RGBA) de um PNG de 8 bits.

    Aceita cinza, RGB, paleta e as duas variantes com alfa. Recusa 16 bits e
    entrelaçamento em vez de adivinhar: melhor a produção receber um recado
    claro sobre o arquivo do que uma placa com a logo embaralhada.
    """

    if bruto[:8] != b"\x89PNG\r\n\x1a\n":
        raise LogoInviavel("O arquivo da logo não é um PNG.")

    largura = altura = tipo = 0
    idat = bytearray()
    paleta = b""
    alfa_paleta = b""
    i = 8
    while i + 8 <= len(bruto):
        tamanho = struct.unpack(">I", bruto[i : i + 4])[0]
        nome = bruto[i + 4 : i + 8]
        corpo = bruto[i + 8 : i + 8 + tamanho]
        if nome == b"IHDR":
            largura, altura, profundidade, tipo, _, _, entrelace = struct.unpack(
                ">IIBBBBB", corpo
            )
            if profundidade != 8:
                raise LogoInviavel(
                    f"O PNG tem {profundidade} bits por canal. Salve em 8 bits."
                )
            if entrelace:
                raise LogoInviavel("O PNG está entrelaçado. Salve sem entrelaçamento.")
            if tipo not in (0, 2, 3, 4, 6):
                raise LogoInviavel(f"Tipo de cor {tipo} do PNG não é suportado.")
        elif nome == b"PLTE":
            paleta = corpo
        elif nome == b"tRNS":
            alfa_paleta = corpo
        elif nome == b"IDAT":
            idat += corpo
        elif nome == b"IEND":
            break
        i += 12 + tamanho

    if not largura or not altura or not idat:
        raise LogoInviavel("O PNG está incompleto: falta cabeçalho ou imagem.")

    canais = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[tipo]
    dados = zlib.decompress(bytes(idat))
    passo = largura * canais
    cru = bytearray(altura * passo)
    anterior = bytearray(passo)
    pos = 0
    for y in range(altura):
        filtro = dados[pos]
        pos += 1
        linha = bytearray(dados[pos : pos + passo])
        pos += passo
        if filtro == 1:
            for x in range(canais, passo):
                linha[x] = (linha[x] + linha[x - canais]) & 0xFF
        elif filtro == 2:
            for x in range(passo):
                linha[x] = (linha[x] + anterior[x]) & 0xFF
        elif filtro == 3:
            for x in range(passo):
                esquerda = linha[x - canais] if x >= canais else 0
                linha[x] = (linha[x] + ((esquerda + anterior[x]) >> 1)) & 0xFF
        elif filtro == 4:
            for x in range(passo):
                a = linha[x - canais] if x >= canais else 0
                b = anterior[x]
                c = anterior[x - canais] if x >= canais else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                if pa <= pb and pa <= pc:
                    perto = a
                elif pb <= pc:
                    perto = b
                else:
                    perto = c
                linha[x] = (linha[x] + perto) & 0xFF
        elif filtro != 0:
            raise LogoInviavel(f"Filtro de linha {filtro} do PNG é inválido.")
        cru[y * passo : (y + 1) * passo] = linha
        anterior = linha

    rgba = bytearray(largura * altura * 4)
    total = largura * altura
    if tipo == 6:
        rgba[:] = cru
    elif tipo == 2:
        for n in range(total):
            rgba[4 * n : 4 * n + 3] = cru[3 * n : 3 * n + 3]
            rgba[4 * n + 3] = 255
    elif tipo == 0:
        for n in range(total):
            cinza = cru[n]
            rgba[4 * n : 4 * n + 4] = bytes((cinza, cinza, cinza, 255))
    elif tipo == 4:
        for n in range(total):
            cinza = cru[2 * n]
            rgba[4 * n : 4 * n + 4] = bytes((cinza, cinza, cinza, cru[2 * n + 1]))
    else:
        if len(paleta) < 3:
            raise LogoInviavel("O PNG diz usar paleta, mas não traz a paleta.")
        for n in range(total):
            indice = cru[n]
            rgba[4 * n : 4 * n + 3] = paleta[3 * indice : 3 * indice + 3]
            rgba[4 * n + 3] = (
                alfa_paleta[indice] if indice < len(alfa_paleta) else 255
            )
    return largura, altura, rgba


def _reduz(largura: int, altura: int, rgba: bytearray, teto: int):
    """Reduz por média de bloco, que é o que preserva a borda da logo.

    Descartar pixel (vizinho mais próximo) serrilha o contorno, e contorno
    serrilhado dentro de um QR é exatamente o detalhe que o leitor tenta
    interpretar como módulo.
    """

    if max(largura, altura) <= teto:
        return largura, altura, rgba

    fator = math.ceil(max(largura, altura) / teto)
    nova_l, nova_a = max(1, largura // fator), max(1, altura // fator)
    saida = bytearray(nova_l * nova_a * 4)
    for y in range(nova_a):
        for x in range(nova_l):
            soma = [0, 0, 0, 0]
            contagem = 0
            for dy in range(fator):
                origem_y = y * fator + dy
                if origem_y >= altura:
                    break
                base = (origem_y * largura + x * fator) * 4
                for dx in range(fator):
                    if x * fator + dx >= largura:
                        break
                    ponto = base + dx * 4
                    soma[0] += rgba[ponto]
                    soma[1] += rgba[ponto + 1]
                    soma[2] += rgba[ponto + 2]
                    soma[3] += rgba[ponto + 3]
                    contagem += 1
            destino = (y * nova_l + x) * 4
            for canal in range(4):
                saida[destino + canal] = soma[canal] // contagem
    return nova_l, nova_a, saida


def _para_cmyk(largura: int, altura: int, rgba: bytearray) -> bytes:
    """Converte para CMYK compondo a transparência sobre branco.

    O alfa é resolvido aqui, e não com máscara no PDF, porque a janela já é
    branca e porque arquivo sem transparência é o que a gráfica sabe processar
    sem surpresa. Preto puro continua saindo em K 100% sem C, M e Y.
    """

    saida = bytearray(largura * altura * 4)
    for n in range(largura * altura):
        r, g, b, a = rgba[4 * n : 4 * n + 4]
        if a != 255:
            r = 255 - ((255 - r) * a) // 255
            g = 255 - ((255 - g) * a) // 255
            b = 255 - ((255 - b) * a) // 255
        maior = max(r, g, b)
        destino = 4 * n
        if maior == 0:
            saida[destino + 3] = 255
            continue
        saida[destino] = (maior - r) * 255 // maior
        saida[destino + 1] = (maior - g) * 255 // maior
        saida[destino + 2] = (maior - b) * 255 // maior
        saida[destino + 3] = 255 - maior
    return bytes(saida)


def _alvos_de_alinhamento(versao: int) -> list[int]:
    """Coordenadas dos alvos de alinhamento da versão, pela regra do padrão."""

    if versao < 2:
        return []
    quantidade = versao // 7 + 2
    primeiro, ultimo = 6, 4 * versao + 10
    if quantidade == 2:
        return [primeiro, ultimo]
    # A versão 32 é a exceção conhecida da fórmula e tem passo fixo de 26.
    passo = 26 if versao == 32 else 2 * math.ceil((ultimo - primeiro) / (2 * (quantidade - 1)))
    coordenadas = [ultimo - i * passo for i in range(quantidade - 1)]
    return [primeiro] + sorted(coordenadas)


def _intervalo_proibido(lado: int, versao: int) -> list[tuple[int, int, int, int]]:
    """Retângulos que a janela não pode tocar, em (x0, y0, x1, y1) inclusivos.

    Entram os três alvos dos cantos com a faixa de formato, as duas trilhas de
    sincronismo e os alvos de alinhamento, menos um: o do centro do símbolo.

    A exceção é medida, não concessão. Nas versões 7 a 13 o alvo do meio cai
    exatamente no centro, e 24 dos 36 setores caem ali porque o nome do setor
    vai dentro da URL. A regra antiga recusava a logo nesses 24, o que na
    prática recusava a logo. Na medição de 23/09 a leitura com o alvo central
    coberto ficou idêntica à do código limpo em todas as condições, inclusive
    de lado e com contraste baixo, e a reserva contra mancha não mudou. Dá
    para cobrir esse alvo porque a partir da versão 7 existem seis deles: o
    leitor perde uma referência e fica com cinco. Cobrir qualquer outro é o
    que não tem volta, e continua barrado.
    """

    proibidos = [
        (0, 0, 8, 8),
        (lado - 8, 0, lado - 1, 8),
        (0, lado - 8, 8, lado - 1),
        (6, 0, 6, lado - 1),
        (0, 6, lado - 1, 6),
    ]
    coordenadas = _alvos_de_alinhamento(versao)
    if coordenadas:
        primeiro, ultimo, centro = coordenadas[0], coordenadas[-1], lado // 2
        # Os três cruzamentos sobre os alvos dos cantos não recebem alvo de
        # alinhamento, e esses cantos já entraram na lista acima.
        livres = {
            (primeiro, primeiro),
            (primeiro, ultimo),
            (ultimo, primeiro),
            (centro, centro),
        }
        for cy in coordenadas:
            for cx in coordenadas:
                if (cy, cx) in livres:
                    continue
                proibidos.append((cx - 2, cy - 2, cx + 2, cy + 2))
    return proibidos


def lado_da_janela(
    lado: int,
    versao: int,
    lado_mm: float,
    alvo_mm: float = JANELA_ALVO_MM,
    teto: float = TETO_DE_AREA,
) -> int:
    """Lado da janela em módulos: o alvo em milímetros, limitado pelo teto.

    Ímpar sempre, porque o lado do símbolo é ímpar em toda versão: só ímpar
    deixa a janela exatamente no centro, sem empurrar a logo meio módulo para
    um lado e comer um módulo a mais de um dos dois lados.
    """

    modulo_mm = lado_mm / lado
    por_medida = int(alvo_mm / modulo_mm)
    por_area = math.isqrt(int(lado * lado * teto))
    maximo = min(por_medida, por_area)
    if maximo % 2 == 0:
        maximo -= 1
    if maximo < 3:
        raise LogoInviavel(
            f"A janela de {alvo_mm:.0f} mm não chega a três módulos neste "
            f"código, onde cada módulo tem {modulo_mm:.1f} mm. Numa placa "
            f"de {lado_mm:.0f} mm a logo tem que ser proporcionalmente maior "
            "para valer a pena, e aí ela precisa ser medida de novo."
        )
    for candidato in range(maximo, 2, -2):
        meio = candidato // 2
        centro = lado // 2
        x0, y0, x1, y1 = centro - meio, centro - meio, centro + meio, centro + meio
        colide = any(
            x0 <= px1 and x1 >= px0 and y0 <= py1 and y1 >= py0
            for px0, py0, px1, py1 in _intervalo_proibido(lado, versao)
        )
        if not colide:
            return candidato
    raise LogoInviavel(
        f"Não sobra centro livre num QR versão {versao}: a janela bateria "
        "numa referência que o leitor usa para achar o código antes de ler "
        "qualquer bit. Encurte o destino do QR para o código cair numa versão "
        "menor."
    )


def abre_janela(matriz: list[list[bool]], lado_modulos: int) -> list[list[bool]]:
    """Devolve a matriz com o quadrado central apagado, sem alterar a original.

    Apagar na matriz em vez de só cobrir com branco no PDF garante que não vai
    tinta preta nenhuma sob a logo: se a logo tiver área clara, ela fica clara
    de verdade, e o preview do painel mostra o mesmo que a gráfica recebe.
    """

    lado = len(matriz)
    centro, meio = lado // 2, lado_modulos // 2
    nova = [linha[:] for linha in matriz]
    for y in range(centro - meio, centro + meio + 1):
        for x in range(centro - meio, centro + meio + 1):
            nova[y][x] = False
    return nova


_CACHE: dict[tuple[str, float, int, int, float], Logo] = {}


def prepara(caminho: str, lado: int, versao: int, lado_mm: float) -> Logo:
    """Lê o arquivo e devolve a logo dimensionada para este código.

    O resultado fica em cache por arquivo e versão porque a conversão roda em
    Python puro: são 36 setores e a produção baixa os arquivos em sequência.
    """

    chave = (
        os.path.abspath(caminho),
        os.path.getmtime(caminho),
        lado,
        versao,
        lado_mm,
    )
    if chave in _CACHE:
        return _CACHE[chave]

    lado_modulos = lado_da_janela(lado, versao, lado_mm)
    with open(caminho, "rb") as arquivo:
        largura, altura, rgba = _le_png(arquivo.read())
    largura, altura, rgba = _reduz(largura, altura, rgba, TETO_DE_PIXELS)

    # A logo entra inteira dentro da janela menos a moldura, mantendo a
    # proporção: esticar a logo da marca do cliente não é uma opção.
    util = lado_modulos - 2 * FOLGA_MODULOS
    if util < 1:
        raise LogoInviavel("A janela ficou menor que a moldura branca exigida.")
    escala = min(util / largura, util / altura)
    logo = Logo(
        largura_px=largura,
        altura_px=altura,
        dados=zlib.compress(_para_cmyk(largura, altura, rgba), 9),
        lado_modulos=lado_modulos,
        largura_modulos=largura * escala,
        altura_modulos=altura * escala,
    )
    _CACHE[chave] = logo
    return logo


def _bloco_png(nome: bytes, corpo: bytes) -> bytes:
    return (
        struct.pack(">I", len(corpo))
        + nome
        + corpo
        + struct.pack(">I", zlib.crc32(nome + corpo))
    )


def png_do_codigo(
    matriz: list[list[bool]],
    logo: Logo | None,
    px_por_modulo: int = 8,
    zona: int = 4,
) -> bytes:
    """Desenha o código como PNG, com a logo no lugar em que ela vai imprimir.

    Existe para o painel mostrar na tela o mesmo desenho que a gráfica recebe.
    O preview antigo é montado no navegador por uma biblioteca que não sabe da
    janela da logo, e painel mostrando uma coisa enquanto o PDF traz outra é o
    tipo de diferença que só aparece depois de a tiragem estar pronta.

    A cor sai da conversão CMYK que já foi feita para o PDF e volta daqui,
    então o que aparece na tela é a cor convertida, não a original: se a
    conversão apagar um tom da logo, a produção vê isso antes da gráfica.
    """

    lado = len(matriz)
    total = (lado + 2 * zona) * px_por_modulo
    tela = [bytearray(b"\xff" * (total * 3)) for _ in range(total)]

    for y in range(lado):
        for x in range(lado):
            if not matriz[y][x]:
                continue
            for py in range((y + zona) * px_por_modulo, (y + zona + 1) * px_por_modulo):
                inicio = (x + zona) * px_por_modulo * 3
                tela[py][inicio : inicio + px_por_modulo * 3] = b"\x00" * (
                    px_por_modulo * 3
                )

    if logo is not None:
        cmyk = zlib.decompress(logo.dados)
        larg = max(1, round(logo.largura_modulos * px_por_modulo))
        alt = max(1, round(logo.altura_modulos * px_por_modulo))
        centro = (lado / 2 + zona) * px_por_modulo
        x0, y0 = round(centro - larg / 2), round(centro - alt / 2)
        for dy in range(alt):
            # Média do bloco de origem, e não o pixel mais próximo: a logo cai
            # para um terço do tamanho e o contorno serrilhado dentro de um QR
            # é justamente o que o leitor tenta interpretar como módulo.
            oy0 = dy * logo.altura_px // alt
            oy1 = max(oy0 + 1, (dy + 1) * logo.altura_px // alt)
            for dx in range(larg):
                ox0 = dx * logo.largura_px // larg
                ox1 = max(ox0 + 1, (dx + 1) * logo.largura_px // larg)
                soma = [0, 0, 0, 0]
                for oy in range(oy0, oy1):
                    for ox in range(ox0, ox1):
                        ponto = (oy * logo.largura_px + ox) * 4
                        for canal in range(4):
                            soma[canal] += cmyk[ponto + canal]
                quantos = (oy1 - oy0) * (ox1 - ox0)
                c, m, y, k = (valor // quantos for valor in soma)
                base = 255 - k
                destino = (x0 + dx) * 3
                tela[y0 + dy][destino : destino + 3] = bytes(
                    (
                        base - c * base // 255,
                        base - m * base // 255,
                        base - y * base // 255,
                    )
                )

    cru = bytearray()
    for linha in tela:
        cru.append(0)  # filtro nenhum: o zlib já resolve o tamanho
        cru += linha
    return (
        b"\x89PNG\r\n\x1a\n"
        + _bloco_png(b"IHDR", struct.pack(">IIBBBBB", total, total, 8, 2, 0, 0, 0))
        + _bloco_png(b"IDAT", zlib.compress(bytes(cru), 6))
        + _bloco_png(b"IEND", b"")
    )
