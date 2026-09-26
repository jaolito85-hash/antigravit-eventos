"""Intencao da pergunta controla a midia, independentemente da ficha escolhida."""
import re
from tuca_risco import normal, risco_explicito

PAGAMENTO = re.compile(r"\b(?:pix|cartao|credito|debito|dinheiro|pagamento|pagar|pago|paga|pagam|aceita|aceitam|parcela)\b")
LOCAL = re.compile(r"\b(?:onde|aonde|cade|kd|localizacao|em que lugar|como (?:eu )?(?:chego|chegar|acho|encontro))\b")
PRECO = re.compile(r"\b(?:preco|precos|custa|custam|valor|valores|quanto|qto)\b")
ARTE = re.compile(r"\b(?:cardapio|cardapios|menu|tabela|arte|artes|banner|foto|imagem|catalogo|lista de bebidas)\b")
DISPONIVEL = re.compile(r"\b(?:tem|vende|vendem|vendendo|encontro|disponivel|disponibilidade|ha)\b")
PROBLEMA = re.compile(r"\b(?:acabou|faltou|falta|sem agua|nao tem|nao sai|nao funciona|quebrad\w*|suja|sujo|turva|fila|passando mal|cobraram|cobrou|reembolso|estorno|golpe)\b")
AGUA = re.compile(r"\bagua\b.*\b(?:gratis|gratuita|gratuito|graca|potavel|torneira)\b|\b(?:bebedouro|hidratacao)\b")
# Texto das fichas oficiais: um ponto de hidratação, na pista. "Vários pontos"
# não tinha fonte e foi trocado em 26/09.
AGUA_RESPOSTA = "O ponto de hidratação na pista tem água potável grátis durante todo o festival, é só levar seu copo. Se não achar, peça orientação à equipe em campo."
_LUGAR = re.compile(r"\b(?:pista|feirinha|bares?|praca|loja|lounge|backstage)\b")


def intencao(text):
    value = normal(text)
    if LOCAL.search(value): return 'local'
    if PAGAMENTO.search(value): return 'pagamento'
    if AGUA.search(value): return 'agua_gratis'
    if ARTE.search(value): return 'arte'
    if PRECO.search(value): return 'preco'
    if DISPONIVEL.search(value): return 'disponibilidade'
    return 'informacao'


def permite_arte(text, ficha):
    intent = intencao(text)
    if intent in ('local', 'pagamento', 'agua_gratis'): return False
    if intent == 'arte': return True
    # Line-up mantem o contrato de palco/artista; consultas de agora sao anteriores.
    if ficha.get('kind') == 'lineup': return True
    return intent == 'preco'


def agua_gratis(text, history=()):
    value = normal(text)
    if risco_explicito(text) or PROBLEMA.search(value): return None
    direct = bool(AGUA.search(value))
    previous = next((normal(m.get('content') or '') for m in reversed(history) if m.get('direction') == 'out'), '')
    follow = 'ponto de hidratacao na pista' in previous and bool(re.fullmatch(r'(?:e )?(?:onde(?: e| fica| tem)?|fica onde|e gelada|tem gelada|qual ponto|qual o mais proximo)[ ?!.]*', value))
    if not direct and not follow: return None
    reply = AGUA_RESPOSTA
    if re.search(r'gelad|fria|temperatura|torneira', value):
        reply += ' Não tenho confirmação da temperatura da água nem do tipo de instalação de cada ponto.'
    return reply


def local_documentado(answer):
    """O lugar de venda escrito na ficha, numa frase pronta, ou None.

    As fichas com arte guardam o lugar entre parênteses depois do título
    ("LOJA OFICIAL (na pista, perto da feirinha)", "CERVEJAS E ÁGUA (à venda
    nos bares)") ou abrem com "À VENDA NOS BARES do festival".
    """
    text = str(answer or '')
    for m in re.finditer(r"([A-ZÀ-Ú][A-ZÀ-Ú '&]{2,60})\s*\(([^)]+)\)", text):
        nome, onde = m.group(1).strip(), m.group(2).strip()
        if not _LUGAR.search(normal(onde)):
            continue
        if normal(onde).startswith('a venda'):
            return onde[0].upper() + onde[1:] + '.'
        return f"Fica na {nome.title()}, {onde}."
    if re.search(r"\bà venda nos bares\b", text, re.I):
        return 'À venda nos bares do festival.'
    return None


def com_local(reply, text, known):
    """Pergunta de disponibilidade nunca fica sem o lugar de venda.

    Em 26/09 "tem seda?" voltou só "Tem sim!": a frase da IA que dizia a
    loja também trazia o preço, e o filtro de preço levou as duas juntas.
    """
    if intencao(text) != 'disponibilidade' or not known:
        return reply
    lugar = local_documentado(known.get('answer'))
    if not lugar:
        return reply
    chaves = set(_LUGAR.findall(normal(lugar)))
    if any(chave in normal(reply) for chave in chaves):
        return reply
    return (reply.rstrip() + ' ' + lugar).strip()


def ficha_pagamento(entries):
    candidates = [f for f in entries if f.get('active', True) and f.get('kind') not in ('bar','food','lineup')
                  and re.search(r'formas de pagamento|pagamento.*(?:pix|cartao)|(?:pix|cartao).*pagamento', normal(f.get('answer') or ''))]
    # Mais de uma regra pode ter escopos diferentes. A IA deve resolver, nao escolher ao acaso.
    return candidates[0] if len(candidates) == 1 else None


def reserva_informativa(text, known, history=''):
    """Sem IA, jamais despejar uma tabela de precos para responder onde/tem."""
    intent = intencao(text)
    if intent not in ('local','disponibilidade'): return None
    answer = str((known or {}).get('answer') or '')
    if intent == 'local':
        # Somente frases de localizacao documentadas; linhas com precos nao sao enderecos.
        pieces = re.split(r'[\n.!]', answer)
        places = [p.strip() for p in pieces if not re.search(r'R\$|\d+\s*reais', p, re.I)
                  and re.search(r'\b(?:na pista|perto d|proximo|fica|nos bares|na loja|loja oficial|praca de alimentacao)\b', normal(p))]
        if places: return '. '.join(places[:2]) + '.'
        return 'Não tenho a localização exata confirmada. Peça orientação à equipe em campo.' if known else 'De qual lugar ou produto você quer saber a localização?'
    lugar = local_documentado(answer) if known else None
    if lugar:
        # A ficha diz que o item é vendido, não que há estoque agora.
        return f'Está na lista oficial do festival. {lugar}'
    return 'Não consigo confirmar a disponibilidade agora. Consulte a equipe do ponto de venda.'


def sem_precos_nao_pedidos(reply, text):
    """Ultima barreira: disponibilidade/localizacao nao vira lista de precos."""
    if intencao(text) not in ('local','disponibilidade') or PRECO.search(normal(text)):
        return reply
    sentences = re.split(r'(?<=[.!?])\s+|\n', reply)
    return ' '.join(s for s in sentences if not re.search(r'R\$|\b\d+(?:[.,]\d+)?\s*reais\b', s, re.I)).strip()
