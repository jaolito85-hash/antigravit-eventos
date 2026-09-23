# -*- coding: utf-8 -*-
"""Monta a pasta de QR Codes que vai para o marketing no Drive.

Diferente de `generate_qrcodes.py`, que entrega SVG cru para a gráfica, aqui a
saída é pensada para quem vai montar a arte da placa e precisa saber, olhando
o nome do arquivo, de que lugar é cada código.

Três coisas que este script resolve e que ninguém acerta na mão:

1. **A logo no centro.** Os sócios pediram na reunião de 23/09, e o desenho
   vem de `logo_qrcode`, o mesmo que o painel usa. Gerar o QR em qualquer
   outro lugar produziria placa sem a logo aprovada.
2. **Zona de silêncio igual para todos.** Os códigos têm comprimentos
   diferentes e caem em versões diferentes de QR. A margem é calculada sobre o
   conjunto, então as 65 placas têm o mesmo tamanho total e o designer trabalha
   com uma medida só.
3. **O que ainda não está confirmado fica separado.** Setor com pendência não
   entra na mesma pasta de quem já pode virar arte: placa impressa com código
   que vai mudar é dinheiro no lixo.

Uso:
    python scripts/gerar_placas_marketing.py
    python scripts/gerar_placas_marketing.py --saida out/placas --lado 120

Precisa de segno (`pip install segno`), como o gerador da gráfica.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from urllib.parse import quote

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))

try:
    import segno
except ImportError:
    sys.exit("Falta o segno. Rode: pip install segno")

import logo_qrcode
import pdf_qrcode
from generate_qrcodes import especificacao, numero_do_ambiente
from server import texto_do_qr

SETORES_JSON = RAIZ / "scripts" / "calibragem" / "setores.json"
ARQUIVO_DA_LOGO = RAIZ / "static" / "qr-logo.png"
MARCA = "Tuca | Tropicadelia 2026"

PASTA_PRONTOS = "1-prontos-para-a-arte"
PASTA_SEGURAR = "2-confirmar-antes-de-imprimir"
PASTA_PNG = "visualizacao (nao mandar para a grafica)"
PASTA_PROVA = "prova-de-leitura"

# A especificação da gráfica foi escrita antes de a logo existir. Em vez de
# duplicar o texto inteiro aqui, corrigimos a única linha que ficou errada, e
# o assert avisa se ela mudar de lugar em vez de deixar a mentira passar.
LINHA_VELHA = (
    "- Nao arredondar cantos dos modulos, nao aplicar efeito, nao inserir logo\n"
    "  sobre o QR."
)
LINHA_NOVA = (
    "- Nao arredondar cantos dos modulos e nao aplicar efeito.\n"
    "- A logo do centro JA VEM no arquivo, na janela medida para nao derrubar a\n"
    "  leitura. Nao aumentar, nao trocar por outra e nao acrescentar uma segunda."
)


def nome_de_arquivo(codigo: str, nome: str) -> str:
    """`WC-FEM-HYPE-PISTA Sanitários Femininos Hype (Pista)`.

    O código vem primeiro porque é ele que tem de bater com a arte, e a lista
    ordenada por nome de arquivo fica agrupada por tipo de ponto. O resto é
    para o marketing saber de que lugar é a placa sem abrir planilha nenhuma.
    """

    legivel = nome.replace(" • ", " (") + ")" if " • " in nome else nome
    for proibido in '\\/:*?"<>|':
        legivel = legivel.replace(proibido, "-")
    return f"{codigo} {legivel}".strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Pacote de QR Codes para o marketing.")
    parser.add_argument("--saida", default="out/placas-marketing")
    parser.add_argument("--lado", type=float, default=120.0,
                        help="Lado do símbolo em mm, sem a zona de silêncio.")
    parser.add_argument("--numero", default=None,
                        help="WhatsApp público, só dígitos. Padrão: o do .env.")
    args = parser.parse_args()

    if not SETORES_JSON.exists():
        sys.exit("Rode antes: python scripts/derivar_setores.py")
    setores = json.loads(SETORES_JSON.read_text(encoding="utf-8"))["setores"]

    numero = numero_do_ambiente(args.numero)
    destino = RAIZ / args.saida
    for sub in (PASTA_PRONTOS, PASTA_SEGURAR, PASTA_PNG, PASTA_PROVA):
        (destino / sub).mkdir(parents=True, exist_ok=True)

    # Primeira passada: codifica todos antes de desenhar qualquer um, porque a
    # zona de silêncio sai do conjunto e não de cada código.
    codificados = []
    for setor in setores:
        url = f"https://wa.me/{numero}?text={quote(texto_do_qr(setor['code']), safe='')}"
        qr = segno.make(url, error="h", boost_error=False)
        matriz = [[bool(m) for m in linha] for linha in qr.matrix]
        codificados.append((setor, url, qr.version, matriz, args.lado / len(matriz)))

    zona_mm = 4 * max(c[4] for c in codificados)
    total_mm = args.lado + 2 * zona_mm

    linhas = []
    pendentes = 0
    for setor, url, versao, matriz, modulo_mm in codificados:
        logo = None
        if ARQUIVO_DA_LOGO.is_file():
            logo = logo_qrcode.prepara(str(ARQUIVO_DA_LOGO), len(matriz), versao, args.lado)
            matriz = logo_qrcode.abre_janela(matriz, logo.lado_modulos)

        base = nome_de_arquivo(setor["code"], setor["name"])
        segurar = bool(setor.get("avisos"))
        pendentes += 1 if segurar else 0
        pasta = PASTA_SEGURAR if segurar else PASTA_PRONTOS

        (destino / pasta / f"{base}.pdf").write_bytes(
            pdf_qrcode.pdf_producao(
                matriz, modulo_mm, zona_mm, setor["code"], url, MARCA, logo=logo
            )
        )
        (destino / PASTA_PNG / f"{base}.png").write_bytes(
            logo_qrcode.png_do_codigo(matriz, logo)
        )

        linhas.append({
            "arquivo": f"{base}.pdf",
            "pasta": pasta,
            "codigo": setor["code"],
            "lugar": setor["name"],
            "zona": setor.get("zona") or "",
            "tipo de lugar": setor.get("grupo") or "",
            "texto sugerido para a placa": setor.get("cta") or "",
            "link do QR": url,
            "conferir antes": "; ".join(setor.get("avisos") or []),
        })

    # Prova de leitura: o pior caso e os dois extremos, não os 65. A prova
    # existe para escanear no material final, e testar o código mais longo já
    # cobre os outros, porque é ele que tem o módulo menor.
    por_tamanho = sorted(codificados, key=lambda c: len(c[3]))
    for setor, url, versao, matriz, modulo_mm in (por_tamanho[0], por_tamanho[len(por_tamanho) // 2], por_tamanho[-1]):
        logo = None
        if ARQUIVO_DA_LOGO.is_file():
            logo = logo_qrcode.prepara(str(ARQUIVO_DA_LOGO), len(matriz), versao, args.lado)
            matriz = logo_qrcode.abre_janela(matriz, logo.lado_modulos)
        base = nome_de_arquivo(setor["code"], setor["name"])
        (destino / PASTA_PROVA / f"{base}.pdf").write_bytes(
            pdf_qrcode.pdf_prova(
                matriz, modulo_mm, zona_mm, setor["code"], setor["name"], url,
                versao, MARCA, logo=logo,
            )
        )

    with (destino / "indice.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        escritor = csv.DictWriter(fh, fieldnames=list(linhas[0].keys()), delimiter=";")
        escritor.writeheader()
        escritor.writerows(linhas)

    texto = especificacao(numero, args.lado, total_mm, zona_mm)
    assert LINHA_VELHA in texto, (
        "A especificação mudou: confira a linha sobre logo em generate_qrcodes.py"
    )
    (destino / "ESPECIFICACAO-GRAFICA.txt").write_text(
        texto.replace(LINHA_VELHA, LINHA_NOVA), encoding="utf-8"
    )

    prontos = len(linhas) - pendentes
    (destino / "LEIA-ME.txt").write_text(f"""QR CODES DOS SETORES
Tuca | Tropicadelia 2026

O QUE TEM AQUI

{PASTA_PRONTOS}/
    {prontos} PDFs, um por ponto do festival. Vetor, preto K 100%, com a logo
    no centro. E o arquivo que entra na arte da placa.

{PASTA_SEGURAR}/
    {pendentes} PDFs de pontos cujo codigo ainda nao esta confirmado com a
    diretoria. Nao imprimir. Se o codigo mudar, a placa vai para o lixo.
    O motivo de cada um esta na coluna "conferir antes" do indice.csv.

{PASTA_PNG}/
    Imagem de cada QR, so para conferir na tela e ver miniatura no Drive.
    Nao mandar para a grafica: PNG nao e vetor e perde qualidade na ampliacao.

{PASTA_PROVA}/
    Tres folhas A4 para escanear antes da tiragem, com o codigo impresso no
    tamanho real. Sao os casos extremos: o codigo mais curto, um do meio e o
    mais longo, que e o de modulo menor e portanto o mais dificil de ler.

indice.csv
    A lista completa: codigo, lugar, zona, tipo, texto sugerido para a placa e
    o link que o QR abre. Abre no Excel.

ESPECIFICACAO-GRAFICA.txt
    O que a grafica precisa saber: impressao, acabamento, medidas e o teste de
    aprovacao. Mandar junto com os arquivos.

O QUE CADA QR FAZ

Ao escanear, abre o WhatsApp do evento com uma mensagem pronta comecando por
#SETOR:CODIGO. E essa etiqueta que diz ao sistema de onde a pessoa esta
falando. Por isso os codigos sao diferentes entre si e nao podem ser trocados
de lugar: trocar dois arquivos nao da erro visivel, so manda a equipe para o
lugar errado.

Numero de destino: +{numero}

MEDIDAS

Simbolo: {args.lado:.0f} mm de lado. Com a margem branca, o bloco fecha em
{total_mm:.1f} mm, e essa medida vale para todas as placas, de proposito.
A margem branca ({zona_mm:.1f} mm de cada lado) ja esta dentro do arquivo e
nenhuma arte, moldura ou furo pode invadi-la.
""", encoding="utf-8")

    print(f"Setores:       {len(linhas)}")
    print(f"  prontos:     {prontos}  -> {PASTA_PRONTOS}/")
    print(f"  a confirmar: {pendentes}  -> {PASTA_SEGURAR}/")
    print(f"Logo no centro: {'sim' if ARQUIVO_DA_LOGO.is_file() else 'NAO (arquivo ausente)'}")
    print(f"Numero:        +{numero}")
    print(f"Medidas:       simbolo {args.lado:.0f} mm | margem {zona_mm:.1f} mm | total {total_mm:.1f} mm")
    print(f"\nPasta pronta para subir no Drive: {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
