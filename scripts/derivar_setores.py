# -*- coding: utf-8 -*-
"""Transforma a lista de códigos da diretoria na tabela de setores da planta.

Por que derivar em vez de digitar: os códigos seguem regra de formação
(`TIPO-[MARCA|SUBTIPO]-AREA-ZONA`), então grupo, zona, nome, equipe e CTA saem
do próprio código. Digitar 65 linhas à mão são 65 chances de erro, e o erro
aparece no meio do festival, quando o pino acende no lugar errado.

O que este script NÃO faz: coordenada. Posição na planta não se deduz de
código nenhum, e é o que a ferramenta de calibragem resolve
(`scripts/calibrar_planta.py`).

Uso:
    python scripts/derivar_setores.py
    python scripts/derivar_setores.py --lista docs/outra-lista.txt

Saídas:
    docs/setores-derivados.csv          para a diretoria conferir
    scripts/calibragem/setores.json     entrada da ferramenta de calibragem
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
LISTA_PADRAO = RAIZ / "docs" / "setores-diretoria-2026-09-23.txt"
CSV_SAIDA = RAIZ / "docs" / "setores-derivados.csv"
JSON_SAIDA = RAIZ / "scripts" / "calibragem" / "setores.json"

# O banco recusa qualquer coisa fora disto (event_sectors_code_format).
CODIGO_VALIDO = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,49}$")

ZONAS = {"PISTA": "Pista", "LOUNGE": "Tropical Lounge", "BACKSTAGE": "Backstage Hype"}

# Prefixo do código manda no grupo, que é como o relatório fecha a conta por
# tipo de lugar ("287 chamados em Sanitários").
GRUPOS = {
    "WC": "Sanitários",
    "BAR": "Bares",
    "OPENFOOD": "Alimentação",
    "PRACA": "Alimentação",
    "AMB": "Saúde",
    "CAIXA": "Caixas",
    "LED": "Telões",
    "ACESSO": "Entradas e Acessos",
    "PCD": "Acessibilidade",
    "LOCKER": "Atendimento ao Público",
    "AVANCO": "Atendimento ao Público",
    "FEIRINHA": "Lojas e Feirinha",
    "DESCANSO": "Ativações e Lazer",
    "GARRA": "Ativações e Lazer",
}

# Tipo de ponto, para o começo do nome que a equipe lê no telão.
TIPOS = {
    "WC-FEM": "Sanitários Femininos",
    "WC-MASC": "Sanitários Masculinos",
    "BAR": "Bar",
    "OPENFOOD": "Open Food",
    "PRACA": "Praça de Alimentação",
    "AMB": "Ambulatório",
    "CAIXA": "Caixa",
    "LED": "Telão",
    "ACESSO": "Acesso",
    "PCD": "Apoio PCD",
    "LOCKER": "Lockers",
    "AVANCO": "Avanço de Pulseira",
    "FEIRINHA": "Feirinha",
    "DESCANSO": "Área de Descanso",
    "GARRA": "Garra",
}

# Área dentro do parque, que é o que distingue 14 banheiros entre si.
AREAS = {
    "HYPE": "Hype",
    "TROPICAL": "Tropical",
    "LAB": "LAB",
    "FEIRINHA": "Feirinha",
    "OPENFOOD": "Open Food",
    "CENTRAL": "Central",
    "PRACA": "Praça",
    "NY": "NY Lounge",
    "LOJINHA": "Lojinha",
    "DELEGA": "Delegacia",
    "DRINK": "Drinks",
    "GERAL": "Geral",
    "JOHN": "John Roger",
    "ROGER": None,  # segunda parte de JOHN ROGER, não vira área sozinha
}

# Termos que eu não sei o que são: a tradução abaixo é palpite meu e sai
# marcada para conferência, em vez de virar nome oficial sem ninguém decidir.
# DELEGA pode ser delegação de artistas ou delegacia, e a diferença muda quem
# atende. GARRA e AVANCO não aparecem na planta de 12/09.
INCERTOS = {
    "DELEGA": "pode ser delegação de artistas ou delegacia, muda a equipe",
    "JOHN": "John Roger não aparece na planta de 12/09",
    "GARRA": "ativação? confirmar o que é e quem atende",
    "AVANCO": "supus avanço/upgrade de pulseira, confirmar",
}

MARCAS = {"COCOLEVE": "Coco Leve", "REDBULL": "Red Bull", "BUD": "Budweiser"}

# Equipes: reaproveitadas da planta que já está em produção, para o roteamento
# não ganhar nomes novos sem ninguém ter combinado.
EQUIPES = {
    "WC": "limpeza_higienizacao",
    "BAR": "bar_insumos",
    "OPENFOOD": "gastronomia_lounge",
    "PRACA": "operacao_praca",
    "AMB": "saude_emergencia",
    "CAIXA": "operacao_caixas",       # equipe nova, confirmar
    "LED": "producao_artistica",      # confirmar se é produção técnica própria
    "ACESSO": "portaria_ingressos",
    "PCD": "acessibilidade",
    "LOCKER": "atendimento_lockers",
    "AVANCO": "sac_atendimento",
    "FEIRINHA": "experiencia_marcas",
    "DESCANSO": "bem_estar",
    "GARRA": "experiencia_marcas",
}

# CTA da placa: o texto que a pessoa lê antes de escanear.
CTAS = {
    "WC": "Falta papel, sabonete ou a fila travou? Avise a equipe.",
    "BAR": "Acabou o gelo, a bebida ou a fila travou? Avise na hora.",
    "OPENFOOD": "Demora, prato frio ou item em falta? Conte para a gente.",
    "PRACA": "Demora, preço ou comida fria? Queremos saber agora.",
    "AMB": "Emergência de saúde? Fale agora que acionamos a equipe.",
    "CAIXA": "Fila no caixa ou problema no pagamento? Avise aqui.",
    "LED": "Imagem travada, som ou telão apagado? Avise a produção.",
    "ACESSO": "Fila na catraca ou problema com a pulseira? Avise aqui.",
    "PCD": "Precisa de apoio ou acessibilidade? Fale direto com a equipe.",
    "LOCKER": "Dúvida de disponibilidade ou problema no locker? Fale aqui.",
    "AVANCO": "Quer trocar ou fazer upgrade da pulseira? Fale com a gente.",
    "FEIRINHA": "Como está a experiência na feirinha? Conte para a gente.",
    "DESCANSO": "Precisa de um lugar para sentar ou de água? Fale com a gente.",
    "GARRA": "Fila grande ou tudo tranquilo na ativação? Avise aqui.",
}

CABECALHO_BLOCO = re.compile(r"^\*?\s*[A-ZÇÃÕ ]+\s*\(\d+\)\s*$")


def normalizar(codigo_cru: str) -> tuple[str, str | None]:
    """Devolve (código aceito pelo banco, aviso).

    Espaço no meio do código é recusado pela tabela, então `LED - NY LOUNGE`
    vira `LED-NY-LOUNGE`. A troca é registrada em vez de silenciosa: quem
    aprovou a lista escreveu de outro jeito e precisa confirmar.
    """

    limpo = re.sub(r"\s*-\s*", "-", codigo_cru.strip())
    limpo = re.sub(r"\s+", "-", limpo).upper()
    if limpo != codigo_cru.strip().upper():
        return limpo, f"código veio como «{codigo_cru.strip()}» e foi normalizado"
    return limpo, None


def ler_lista(caminho: Path) -> list[str]:
    codigos = []
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or CABECALHO_BLOCO.match(linha):
            continue
        codigos.append(linha)
    return codigos


def sem_acento(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )


def derivar(codigo_cru: str) -> dict:
    codigo, aviso_codigo = normalizar(codigo_cru)
    partes = [p for p in codigo.split("-") if p]
    avisos = [a for a in (aviso_codigo,) if a]

    prefixo = partes[0]
    tipo_chave = f"{prefixo}-{partes[1]}" if prefixo == "WC" and len(partes) > 1 else prefixo
    tipo = TIPOS.get(tipo_chave) or TIPOS.get(prefixo)
    grupo = GRUPOS.get(prefixo)
    equipe = EQUIPES.get(prefixo)
    cta = CTAS.get(prefixo)

    zona = None
    for parte in reversed(partes):
        if parte in ZONAS:
            zona = ZONAS[parte]
            break

    # Backstage tem portaria própria: credencial, não ingresso.
    if prefixo == "ACESSO" and zona == "Backstage Hype":
        equipe = "portaria_vip"

    marca = next((MARCAS[p] for p in partes if p in MARCAS), None)
    numero = next((p for p in partes if p.isdigit()), None)

    ignorar = {prefixo, "FEM", "MASC"} | set(ZONAS) | set(MARCAS)
    area_partes = [
        AREAS[p] for p in partes
        if p not in ignorar and not p.isdigit() and AREAS.get(p)
    ]
    area = " ".join(dict.fromkeys(area_partes)) or None

    if not tipo:
        avisos.append("tipo desconhecido, nome precisa ser escrito à mão")
    if not grupo:
        avisos.append("grupo desconhecido, não entra na conta do relatório")
    if not zona:
        avisos.append("sem zona no código, não soma em nenhuma macrozona do telão")
    for parte in partes[1:]:
        if (parte not in ignorar and not parte.isdigit()
                and parte not in AREAS and parte not in MARCAS):
            avisos.append(f"«{parte}» não é área nem marca conhecida")
    if not CODIGO_VALIDO.match(codigo):
        avisos.append("código recusado pelo banco mesmo depois de normalizar")
    for parte in partes:
        if parte in INCERTOS:
            avisos.append(f"«{parte}»: {INCERTOS[parte]}")

    miolo = " ".join(p for p in (tipo, marca, area, numero) if p)
    nome = f"{miolo} • {zona}" if zona else miolo

    return {
        "code": codigo,
        "code_original": codigo_cru.strip(),
        "name": nome,
        "grupo": grupo,
        "zona": zona,
        "area": area,
        "marca": marca,
        "equipe": equipe,
        "cta": cta,
        "avisos": avisos,
        "coord": None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lista", type=Path, default=LISTA_PADRAO)
    args = parser.parse_args()

    setores = [derivar(c) for c in ler_lista(args.lista)]

    repetidos = {s["code"] for s in setores if [x["code"] for x in setores].count(s["code"]) > 1}
    if repetidos:
        for s in setores:
            if s["code"] in repetidos:
                s["avisos"].append("código repetido na lista")

    JSON_SAIDA.parent.mkdir(parents=True, exist_ok=True)
    JSON_SAIDA.write_text(
        json.dumps({"setores": setores}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with CSV_SAIDA.open("w", encoding="utf-8-sig", newline="") as fh:
        escritor = csv.writer(fh, delimiter=";")
        escritor.writerow([
            "Código (vai no QR)", "Nome que a equipe vê", "Tipo de lugar",
            "Zona", "Equipe que recebe", "Texto da placa", "Conferir",
        ])
        for s in setores:
            escritor.writerow([
                s["code"], s["name"], s["grupo"] or "?", s["zona"] or "?",
                s["equipe"] or "?", s["cta"] or "?", "; ".join(s["avisos"]),
            ])

    com_aviso = [s for s in setores if s["avisos"]]
    print(f"setores derivados: {len(setores)}")
    print(f"  com grupo:  {sum(1 for s in setores if s['grupo'])}")
    print(f"  com zona:   {sum(1 for s in setores if s['zona'])}")
    print(f"  com equipe: {sum(1 for s in setores if s['equipe'])}")
    print(f"  precisam de conferência: {len(com_aviso)}")
    for s in com_aviso:
        print(f"    {s['code']:30} {'; '.join(s['avisos'])}")
    print(f"\nCSV para a diretoria: {CSV_SAIDA.relative_to(RAIZ)}")
    print(f"JSON da calibragem:   {JSON_SAIDA.relative_to(RAIZ)}")


if __name__ == "__main__":
    main()
