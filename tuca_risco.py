"""Reconhecimento conservador de risco e continuação, independente da IA."""
import re
import unicodedata


def normal(text):
    return ''.join(c for c in unicodedata.normalize('NFD', str(text or '').lower()) if unicodedata.category(c) != 'Mn')


def sem_risco_negado(text):
    # Retira apenas a afirmação negada; um segundo risco continua visível.
    return re.sub(r'\bnao (?:tem|ha|teve|esta tendo) (?:nenhum[ao]? )?(?:briga|incendio|fogo|assalto|tiro|agressao)\b', ' ', normal(text))


def risco_explicito(text):
    value = sem_risco_negado(text)
    metaphor = re.search(r'\b(show|festa|palco|pista)\b', value) and re.search(r'pegando fogo', value)
    if metaphor and not re.search(r'fumaca|barraca|gerador|fio|queimad|incendio', value):
        value = value.replace('pegando fogo', '')
    return bool(re.search(
        r'\b(socorro|sos|desmai\w*|desacordad\w*|convuls\w*|sangrando|'
        r'pisoteio|esmagad\w*|incendio|fumaca|briga|brigando|tiro|facada|'
        r'assedi\w*|assedio|estupr\w*|infarto|overdose|agrediu|agredindo|'
        r'arma|assalto|surtando|panico|fainted|unconscious|bleeding|pelea|acoso)\b'
        r'|\b(?:passando mal|sem pulso|passed out|help me)\b'
        r'|\b(?:nao|n) (?:consigo |ta |esta )?respira(?:r|ndo)?\b'
        r'|\bme (?:bateu|batendo|seguindo)\b'
        r'|\b(?:filh[oa]|crianca|menino|menina)\b.{0,65}\b(?:sumiu|desaparec\w*|perdid[oa])\b'
        r'|\b(?:sumiu|desaparec\w*)\b.{0,40}\b(?:filh[oa]|crianca)\b'
        r'|\b(?:barraca|gerador|fio)\b.{0,35}\b(?:fogo|queimando)\b', value))


def problema_acesso(text):
    value = normal(text)
    return bool(re.search(r'\b(rampa|cadeirante|acessibilidade|pcd)\b', value)
                and re.search(r'bloquead|obstruid|impedid|nao consigo (?:passar|acessar|entrar)', value))


def complemento_incidente(text):
    value = normal(text).strip()
    # Não sequestrar uma pergunta nem um novo incidente completo.
    if '?' in value or re.search(r'\b(onde|quanto|qual|quem|horas|preco|custa|quero|acabou|falta)\b', value):
        return False
    return bool(re.match(r'^(?:estou |to |tou |fica |e )?(?:no |na |perto d[oa] |ao lado d[oa] |em frente)', value)
                or re.match(r'^(?:ele|ela|a pessoa) (?:ainda |continua |esta |ta )', value))


def limpar_texto_publico(text):
    text = str(text or '')
    text = re.sub(r'\s*(?:junto\.\s*)?\(Regra\s+\d+:[^)]*\)', '', text, flags=re.I)
    # Nunca completar editorialmente uma condição comercial truncada.
    text = re.sub(r',?\s*os preços sobem por\s*$', '', text, flags=re.I) if re.search(r'os preços sobem por\s*$', text, re.I) else text
    return text.strip().rstrip(',')
