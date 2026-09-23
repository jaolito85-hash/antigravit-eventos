"""Gera os QR Codes de setor em vetor, prontos para a gráfica.

Por que este script existe e o gerador da tela não basta: a tela entrega PNG
para quem quer colar num story. A gráfica precisa de vetor, com nível de
correção alto e zona de silêncio, porque o verniz em alto relevo engorda o
módulo impresso e come a margem de erro da leitura.

Uso:
    python scripts/generate_qrcodes.py
    python scripts/generate_qrcodes.py --lado 150 --saida out/qrcodes

Depende de segno, que é Python puro e não entra no requirements.txt do app:
este script é ferramenta de bancada, não roda em produção.

    pip install segno
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape as xml_escape

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

try:
    import segno
except ImportError:  # pragma: no cover - guia de instalação, não lógica
    sys.exit("Falta o segno. Rode: pip install segno")

try:
    from dotenv import load_dotenv

    load_dotenv(RAIZ / ".env")
except ImportError:
    pass

# Migration da planta oficial, usada como reserva quando o banco não responde.
# O banco continua sendo a fonte de verdade: aqui só evitamos ficar sem QR na
# véspera do evento por causa de rede.
MIGRATION_PLANTA = (
    RAIZ / "supabase" / "migrations" / "20260919210000_setores_planta_oficial.sql"
)

# Abaixo disso o módulo impresso não sobrevive ao ganho de ponto nem ao
# registro do verniz em relevo.
MODULO_MINIMO_MM = 0.5


def carrega_setores() -> tuple[list[dict[str, str]], str]:
    """Devolve os setores ativos e de onde eles vieram."""

    try:
        from event_store import EventStore

        setores = EventStore().list_sectors()
        if setores:
            limpos = [
                {
                    "code": s["code"],
                    "name": s.get("name") or s["code"],
                    "zone": (s.get("metadata") or {}).get("zone", ""),
                }
                for s in setores
            ]
            return limpos, "Supabase (setores ativos)"
    except Exception as e:  # noqa: BLE001 - qualquer falha cai para a reserva
        print(f"  Banco indisponível ({type(e).__name__}), usando a migration.")

    return carrega_setores_da_migration(), f"reserva: {MIGRATION_PLANTA.name}"


def carrega_setores_da_migration() -> list[dict[str, str]]:
    """Lê os setores do seed oficial quando o Supabase não está ao alcance."""

    if not MIGRATION_PLANTA.exists():
        sys.exit(f"Sem banco e sem {MIGRATION_PLANTA}. Nada a gerar.")

    sql = MIGRATION_PLANTA.read_text(encoding="utf-8")
    achados = re.findall(
        r"\(\s*'([A-Z0-9][A-Z0-9_-]*)',\s*'((?:[^']|'')*)',\s*'(\{.*?\})'",
        sql,
        re.DOTALL,
    )
    setores = []
    for code, name, metadata in achados:
        zona = re.search(r'"zone":\s*"([^"]*)"', metadata)
        setores.append(
            {
                "code": code,
                "name": name.replace("''", "'"),
                "zone": zona.group(1) if zona else "",
            }
        )
    return sorted(setores, key=lambda s: s["code"])


def zona_de_silencio(modulos_mm: list[float]) -> float:
    """Zona de silêncio única em mm, dimensionada pelo caso mais exigente.

    Os códigos de setor têm comprimentos diferentes e caem em versões
    diferentes de QR, então o módulo muda de tamanho. Se a margem fosse
    4 módulos em cada arquivo, cada placa sairia com um total diferente e o
    designer teria 36 medidas para montar a arte. Dimensionada pelo maior
    módulo, a margem nunca fica abaixo dos 4 módulos da norma e sobra de
    margem só ajuda a leitura.

    Vive aqui, e não em cada script, porque a prova que vai para a gráfica
    precisa sair na mesma medida dos 36 arquivos finais.
    """

    return 4 * max(modulos_mm)


def numero_do_ambiente(informado: str | None = None) -> str:
    """O WhatsApp público que os QR Codes apontam, só dígitos e com DDI."""

    numero = (informado or os.getenv("WHATSAPP_PUBLIC_NUMBER") or "").strip()
    if not numero.isdigit():
        sys.exit(
            "WHATSAPP_PUBLIC_NUMBER ausente ou com caractere que não é dígito. "
            "É o número que o participante vê, só dígitos, com DDI."
        )
    return numero


def monta_url(numero: str, codigo: str) -> str:
    """Monta o wa.me exatamente como o participante vai enviar.

    A primeira linha precisa ser #SETOR:CODIGO, que é o que o webhook lê para
    rotear o chamado sem depender da IA.
    """

    from server import texto_do_qr

    return f"https://wa.me/{numero}?text={quote(texto_do_qr(codigo), safe='')}"


def monta_svg(
    matriz: list[list[bool]],
    borda: float,
    modulo_mm: float,
    codigo: str,
    url: str,
) -> str:
    """Desenha o QR como um único path fechado, em milímetros reais.

    Path único e não um retângulo por módulo porque a gráfica seleciona o
    código inteiro com um clique e copia para a camada de verniz. Os módulos
    escuros vizinhos de cada linha viram um retângulo só, o que elimina as
    frestas de um micron que o RIP às vezes deixa entre quadrados colados.

    A borda entra no viewBox, e não nas coordenadas, para o path continuar em
    números inteiros mesmo quando a zona de silêncio é fracionária em módulos.
    """

    modulos = len(matriz)
    total = modulos + borda * 2
    total_mm = total * modulo_mm

    partes = []
    for y, linha in enumerate(matriz):
        x = 0
        while x < modulos:
            if not linha[x]:
                x += 1
                continue
            inicio = x
            while x < modulos and linha[x]:
                x += 1
            largura = x - inicio
            partes.append(f"M{inicio} {y}h{largura}v1h-{largura}z")

    d = "".join(partes)
    titulo = xml_escape(f"QR do setor {codigo}")
    descricao = xml_escape(
        f"{url} | correcao H | zona de silencio {borda * modulo_mm:.2f} mm "
        f"({borda:.2f} modulos) | modulo {modulo_mm:.3f} mm"
    )

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" version="1.1" '
        f'width="{total_mm:.3f}mm" height="{total_mm:.3f}mm" '
        f'viewBox="{-borda:.4f} {-borda:.4f} {total:.4f} {total:.4f}">\n'
        f"  <title>{titulo}</title>\n"
        f"  <desc>{descricao}</desc>\n"
        f'  <rect id="ZONA-DE-SILENCIO" x="{-borda:.4f}" y="{-borda:.4f}" '
        f'width="{total:.4f}" height="{total:.4f}" fill="#FFFFFF"/>\n'
        f'  <path id="QR-MODULOS" fill="#000000" fill-rule="nonzero" d="{d}"/>\n'
        "</svg>\n"
    )


def especificacao(
    numero: str, lado_mm: float, total_mm: float, zona_mm: float, relevo: bool = False
) -> str:
    """Texto que viaja junto com os arquivos, para a gráfica não improvisar."""

    if relevo:
        # Só quando a gráfica tiver mesmo a técnica. O relevo é acabamento: a
        # leitura continua vindo do contraste da tinta, nunca da sombra.
        impressao = """IMPRESSAO
- QR em preto 100% sobre branco. O relevo NAO substitui a impressao.
- O relevo vai por cima, registrado sobre os modulos escuros. Para montar a
  camada de verniz, duplique o objeto QR-MODULOS. Mandamos em uma camada so
  de proposito, para nao haver risco de a cor de marcacao ser impressa.
- Tolerancia de registro do relevo sobre a impressao: 0,2 mm.
- O relevo nao pode crescer alem do modulo. Sem engorda, sem trapping, sem
  sobreimpressao que una modulos vizinhos.
- Acabamento do relevo em fosco. Brilho reflete a luz de palco e cega a
  camera do celular."""
    else:
        impressao = """IMPRESSAO
- QR em preto 100% sobre branco chapado. Sem tinta cinza, sem cor, sem
  degrade, sem textura por baixo.
- NUNCA inverter: codigo claro sobre fundo escuro derruba a leitura em boa
  parte dos celulares. A arte da placa pode ser escura, o quadrado do QR nao.
- Acabamento FOSCO. Esta e a regra que mais importa aqui: o evento e a noite,
  sob refletor de palco e lanterna de celular, e laminacao brilhante devolve
  a luz na camera e mata a leitura.
- Sem verniz brilhante, sem plastificacao brilhante, sem acrilico por cima."""

    return f"""ESPECIFICACAO TECNICA DOS QR CODES
Tuca | Tropicadelia 2026

ARQUIVOS
- Um SVG vetorial por setor, nomeado com o codigo do setor.
- Sao codigos DIFERENTES entre si. Trocar dois arquivos de lugar nao da erro
  visivel: o chamado chega no setor errado e o mapa da sala de controle mente.
  Confira o nome do arquivo contra o codigo impresso na arte de cada placa.
- Dentro do SVG existem dois objetos: ZONA-DE-SILENCIO (o fundo branco) e
  QR-MODULOS (o codigo em preto, um unico path fechado).

{impressao}

DIMENSOES
- Lado do simbolo: {lado_mm:.0f} mm.
- Zona de silencio: {zona_mm:.1f} mm de cada lado, ja dentro do arquivo.
- Lado total do arquivo: {total_mm:.1f} mm. Vale para os 36, de proposito:
  os codigos tem comprimentos diferentes e caem em versoes diferentes de QR,
  mas o bloco impresso tem sempre a mesma medida.
- Nenhuma arte, moldura, furo de fixacao ou corte pode entrar na zona de
  silencio.
- Escala sempre proporcional.

O QUE NAO FAZER
- Nao vetorizar, redesenhar nem recriar o codigo. Ele ja esta em vetor.
- Nao arredondar cantos dos modulos, nao aplicar efeito, nao inserir logo
  sobre o QR.
- Nao inverter as cores.

MATERIAL E INSTALACAO
- Uso externo, sol e chuva, madrugada inteira. Vinil ou PVC com laminacao
  fosca. Papel nao sobrevive ao orvalho da madrugada.
- Superficie plana. Colado em poste cilindrico o codigo entorta e o leitor
  perde a geometria.
- Altura do peito, entre 1,40 m e 1,60 m do chao, em ponto com alguma luz.

APROVACAO
- Prova fisica no material final, com o QR real de um setor, antes da tiragem.
- O teste e escanear, nao olhar: iPhone e Android, camera nativa, no escuro,
  de frente e a 45 graus, a 30 cm e a 1 metro, com e sem luz lateral.
  Dez tentativas. Passou nas dez em menos de 2 segundos, roda a tiragem.

Numero de destino dos codigos: +{numero}
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Gera os QR Codes de setor para a gráfica.")
    parser.add_argument(
        "--lado",
        type=float,
        default=120.0,
        help="Lado do símbolo em mm, sem a zona de silêncio (padrão: 120).",
    )
    parser.add_argument(
        "--saida",
        default="out/qrcodes",
        help="Diretório de saída (padrão: out/qrcodes).",
    )
    parser.add_argument(
        "--numero",
        default=None,
        help="WhatsApp público, só dígitos. Padrão: WHATSAPP_PUBLIC_NUMBER do .env.",
    )
    parser.add_argument(
        "--relevo",
        action="store_true",
        help="Escreve a especificação para acabamento em alto relevo sobre o código.",
    )
    args = parser.parse_args()

    numero = numero_do_ambiente(args.numero)

    setores, origem = carrega_setores()
    if not setores:
        sys.exit("Nenhum setor ativo. Nada a gerar.")

    codigos = [s["code"] for s in setores]
    repetidos = {c for c in codigos if codigos.count(c) > 1}
    if repetidos:
        sys.exit(f"Códigos repetidos, o roteamento ficaria ambíguo: {sorted(repetidos)}")

    destino = RAIZ / args.saida
    destino.mkdir(parents=True, exist_ok=True)

    print(f"Setores: {len(setores)} ({origem})")
    print(f"Destino: {destino}")
    print(f"Número:  +{numero}\n")

    # Primeira passada: codifica tudo antes de desenhar. Os códigos de setor
    # têm comprimentos diferentes, então o QR cai em versões diferentes e o
    # módulo muda de tamanho. Sem isso, cada placa sairia com um total em mm
    # diferente e o designer teria 36 medidas para montar a arte.
    codificados = []
    for setor in setores:
        url = monta_url(numero, setor["code"])

        # error='h' recupera 30% do código. É o degrau que segura o ganho de
        # ponto do verniz em relevo. boost_error desligado para o nível ser
        # exatamente o que a especificação promete à gráfica.
        qr = segno.make(url, error="h", boost_error=False)
        matriz = [[bool(m) for m in linha] for linha in qr.matrix]
        codificados.append((setor, url, qr, matriz, args.lado / len(matriz)))

    menor_modulo = min(c[4] for c in codificados)
    zona_mm = zona_de_silencio([c[4] for c in codificados])
    total_mm = args.lado + 2 * zona_mm

    linhas = []
    for setor, url, qr, matriz, modulo_mm in codificados:
        codigo = setor["code"]
        modulos = len(matriz)
        borda = zona_mm / modulo_mm

        arquivo = destino / f"{codigo}.svg"
        arquivo.write_text(
            monta_svg(matriz, borda=borda, modulo_mm=modulo_mm, codigo=codigo, url=url),
            encoding="utf-8",
        )

        linhas.append(
            {
                "arquivo": arquivo.name,
                "codigo": codigo,
                "setor": setor["name"],
                "zona": setor["zone"],
                "url": url,
                "versao_qr": qr.version,
                "modulos": f"{modulos}x{modulos}",
                "modulo_mm": f"{modulo_mm:.3f}".replace(".", ","),
            }
        )
        print(f"  {codigo:<26} v{qr.version:<2} {modulos}x{modulos}  módulo {modulo_mm:.2f} mm")

    indice = destino / "indice.csv"
    with indice.open("w", encoding="utf-8-sig", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=list(linhas[0].keys()), delimiter=";")
        escritor.writeheader()
        escritor.writerows(linhas)

    (destino / "ESPECIFICACAO-GRAFICA.txt").write_text(
        especificacao(numero, args.lado, total_mm, zona_mm, relevo=args.relevo),
        encoding="utf-8",
    )

    print(f"\n{len(linhas)} SVG + indice.csv + ESPECIFICACAO-GRAFICA.txt")
    print(f"Menor módulo: {menor_modulo:.2f} mm (mínimo seguro: {MODULO_MINIMO_MM} mm)")

    if menor_modulo < MODULO_MINIMO_MM:
        print(
            f"\nATENÇÃO: com --lado {args.lado:.0f} o módulo fica abaixo de "
            f"{MODULO_MINIMO_MM} mm e o relevo pode fechar a leitura. Aumente o lado."
        )
        return 1

    orfaos = sorted(
        p.name for p in destino.glob("*.svg") if p.stem not in set(codigos)
    )
    if orfaos:
        print(
            "\nATENÇÃO: sobraram SVG de setores que não estão mais ativos. "
            "Apague antes de enviar para a gráfica:"
        )
        for nome in orfaos:
            print(f"  {nome}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
