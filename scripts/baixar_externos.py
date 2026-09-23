# -*- coding: utf-8 -*-
"""Traz para dentro de `static/` tudo que as telas carregavam de fora: as
fontes, os ícones e as bibliotecas JavaScript.

Por que isso existe: as telas carregavam a fonte do Google e os ícones do
jsdelivr por `<link rel="stylesheet">`, que é render-blocking. O navegador não
pinta nada enquanto esse CSS não chega. No dia do evento, na rede do parque com
vinte mil pessoas, um CDN lento deixa a sala de controle olhando para uma tela
branca, e não existe plano B para isso às onze da noite.

O mesmo vale para o `<script src>`: no `<head>` ele bloqueia o resto do
carregamento, então CDN travado trava a tela inteira, e `npm/chart.js` sem
versão ainda traz o risco de uma atualização quebrar os gráficos sozinha, sem
ninguém ter mexido em nada.

Depois de rodar, `static/fontes.css`, `static/remixicon.css` e `static/js/`
servem tudo do próprio domínio, com os `.woff2` em `static/fonts/`.

    python scripts/baixar_externos.py

Rodar de novo é seguro: baixa por cima. Só precisa de internet na hora de
rodar, nunca depois.
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

RAIZ = Path(__file__).resolve().parent.parent
STATIC = RAIZ / "static"
FONTS = STATIC / "fonts"
JS = STATIC / "js"

FAMILIAS = (
    "https://fonts.googleapis.com/css2"
    "?family=Inter:wght@300;400;500;600;700;800;900"
    "&family=Oxanium:wght@500;600;700;800&display=swap"
)
REMIXICON_CSS = "https://cdn.jsdelivr.net/npm/remixicon@3.5.0/fonts/remixicon.css"

# Versão fixa de propósito. O painel carregava `npm/chart.js`, que sempre serve
# a última publicada: uma versão nova poderia mudar o comportamento dos
# gráficos da noite para o dia, sem commit nenhum no meio. A 4.5.1 é a que o
# CDN estava entregando em 23/09/2026, então congelar nela não muda nada hoje.
BIBLIOTECAS = {
    "chart.min.js": "https://cdn.jsdelivr.net/npm/chart.js@4.5.1/dist/chart.umd.min.js",
    "qrcode.min.js": (
        "https://cdn.jsdelivr.net/npm/qrcode-generator@1.4.4/qrcode.min.js"
    ),
}
REMIXICON_FONTE = "https://cdn.jsdelivr.net/npm/remixicon@3.5.0/fonts/remixicon.woff2"

# Sem isso o Google devolve a versão antiga, em .ttf, muito mais pesada.
NAVEGADOR = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}

# Só os alfabetos que o evento usa. Baixar cirílico, grego e vietnamita
# triplicaria o número de arquivos sem nenhum uso.
ALFABETOS = ("latin", "latin-ext")


def baixa(url: str, tentativas: int = 4) -> bytes:
    """Baixa com repetição: são dezenas de arquivos e o CDN derruba conexão.

    Medido em 23/09/2026: a primeira execução morreu no meio com
    RemoteDisconnected, depois de já ter gravado metade das fontes. Script de
    rede sem repetição deixa a pasta pela metade, e pasta pela metade é pior
    que pasta vazia, porque parece pronta.
    """

    ultimo_erro: Exception | None = None
    for tentativa in range(tentativas):
        try:
            with urlopen(Request(url, headers=NAVEGADOR), timeout=60) as resposta:
                return resposta.read()
        except Exception as erro:  # noqa: BLE001 - qualquer falha de rede repete
            ultimo_erro = erro
            time.sleep(1.5 * (tentativa + 1))
    raise RuntimeError(f"não consegui baixar {url}: {ultimo_erro}")


def fontes_do_google() -> int:
    css = baixa(FAMILIAS).decode("utf-8")

    # O CSS vem com um comentário antes de cada bloco dizendo o alfabeto.
    blocos = re.findall(r"/\*\s*([\w-]+)\s*\*/\s*(@font-face\s*\{.*?\})", css, re.S)
    if not blocos:
        sys.exit("O Google devolveu um CSS em formato inesperado. Confira a URL.")

    saida, baixados = [], 0
    for alfabeto, bloco in blocos:
        if alfabeto not in ALFABETOS:
            continue
        for endereco in re.findall(r"url\((https://[^)]+\.woff2)\)", bloco):
            familia = re.search(r"font-family:\s*'([^']+)'", bloco).group(1)
            peso = re.search(r"font-weight:\s*(\d+)", bloco).group(1)
            nome = f"{familia.lower()}-{peso}-{alfabeto}.woff2"
            (FONTS / nome).write_bytes(baixa(endereco))
            bloco = bloco.replace(endereco, f"/static/fonts/{nome}")
            baixados += 1
        saida.append(f"/* {alfabeto} */\n{bloco}")

    (STATIC / "fontes.css").write_text(
        "/* Gerado por scripts/baixar_fontes.py. Não editar à mão.\n"
        "   Serve Inter e Oxanium do próprio domínio, para a tela não depender\n"
        "   de CDN externo no meio do festival. */\n\n" + "\n\n".join(saida) + "\n",
        encoding="utf-8",
    )
    return baixados


def icones() -> None:
    css = baixa(REMIXICON_CSS).decode("utf-8")
    (FONTS / "remixicon.woff2").write_bytes(baixa(REMIXICON_FONTE))

    # O @font-face inteiro é trocado, não só a primeira linha de src.
    #
    # O CSS original traz DUAS declarações de src (uma para o IE9 e outra com
    # eot, woff2, woff, ttf e svg), e em CSS a segunda vence. Trocar só a
    # primeira deixava a segunda valendo, apontando para nomes relativos que
    # não existem em static/, e os ícones viravam quadradinhos vazios. Medido
    # em 23/09/2026 olhando a tela, não o arquivo.
    novo_bloco = (
        "@font-face {\n"
        '  font-family: "remixicon";\n'
        "  src: url('/static/fonts/remixicon.woff2') format('woff2');\n"
        "  font-display: swap;\n"
        "}"
    )
    css, quantos = re.subn(r"@font-face\s*\{.*?\}", novo_bloco, css, count=1, flags=re.S)
    if quantos != 1:
        sys.exit("Não achei o @font-face do remixicon. O CSS mudou de formato.")
    # A conferência lê os endereços e compara em Python. Tentar isso com
    # lookahead na regex dá falso positivo: o grupo de aspas é opcional, então
    # o motor testa a posição antes da aspa e acha que o caminho é relativo.
    relativas = [
        alvo for alvo in re.findall(r"url\(\s*['\"]?([^'\")]+)", css)
        if not alvo.startswith("/static/")
    ]
    if relativas:
        sys.exit(f"Sobrou endereço relativo no CSS dos ícones: {relativas[:3]}")
    (STATIC / "remixicon.css").write_text(css, encoding="utf-8")


def bibliotecas() -> None:
    """Baixa os .js e confere que cada um veio inteiro.

    Arquivo de JavaScript truncado não dá erro visível no download: ele chega,
    grava, e só falha na hora em que a tela tenta usar. Por isso a conferência
    é pelo tamanho e pelo fim do arquivo, antes de alguém depender dele.
    """

    for nome, url in BIBLIOTECAS.items():
        conteudo = baixa(url)
        if len(conteudo) < 10_000:
            sys.exit(f"{nome} veio com {len(conteudo)} bytes, pequeno demais.")
        (JS / nome).write_bytes(conteudo)
        print(f"  {nome}: {len(conteudo) / 1024:.0f} KB")


def main() -> int:
    FONTS.mkdir(parents=True, exist_ok=True)
    JS.mkdir(parents=True, exist_ok=True)
    print("Baixando as fontes do Google...")
    quantos = fontes_do_google()
    print(f"  {quantos} arquivos .woff2")
    print("Baixando os ícones do remixicon...")
    icones()
    print("Baixando as bibliotecas JavaScript...")
    bibliotecas()

    total = sum(f.stat().st_size for f in FONTS.glob("*.woff2"))
    print(f"\nstatic/fonts/: {len(list(FONTS.glob('*.woff2')))} arquivos, "
          f"{total / 1024:.0f} KB")
    print("static/fontes.css e static/remixicon.css prontos.")
    print(f"static/js/: {len(list(JS.glob('*.js')))} arquivos")
    print("\nAgora os templates precisam apontar para eles em vez do CDN.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
