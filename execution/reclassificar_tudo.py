import json

EVENTS_FILE = 'execution/events.json'

def classificar_sentimento(texto):
    texto_lower = texto.lower()
    
    # POSITIVO - verificar primeiro!
    palavras_positivas = ['lindo', 'maravilhoso', 'incrivel', 'incrível', 'show', 'top', 
                          'otimo', 'ótimo', 'excelente', 'perfeito', 'sensacional', 
                          'fantastico', 'fantástico', 'adorei', 'amei', 'recomendo', 'bom', 'mto bom', 'muito bom']
    for palavra in palavras_positivas:
        if palavra in texto_lower:
            return 'Positivo'
    
    # CRÍTICO
    palavras_criticas = ['droga', 'assalto', 'roubo', 'briga', 'arma', 'agressao', 'agressão', 
                         'perigo', 'violencia', 'violência', 'ferido', 'sangue', 'emergencia', 'emergência']
    for palavra in palavras_criticas:
        if palavra in texto_lower:
            return 'Critico'
    
    # URGENTE
    palavras_urgentes = ['sujo', 'alagado', 'quebrado', 'nao funciona', 'não funciona', 
                         'acabou', 'faltando', 'fila', 'pessimo', 'péssimo', 'horrivel', 
                         'horrível', 'nojento', 'caiu', 'machucou', 'gigante', 'enorme']
    for palavra in palavras_urgentes:
        if palavra in texto_lower:
            return 'Urgente'
    
    return 'Neutro'

def classificar_categoria(texto):
    texto_lower = texto.lower()
    
    # SEGURANÇA (verificar primeiro por ser crítico)
    if any(p in texto_lower for p in ['briga', 'seguranca', 'segurança', 'portaria', 'assalto', 'roubo', 'caiu', 'machucou', 'emergencia', 'emergência']):
        return 'Segurança & Organização'
    
    # ESTRUTURA (banheiro, fila, etc)
    if any(p in texto_lower for p in ['banheiro', 'estacionamento', 'fila', 'bar enorme', 'temperatura', 'lixo', 'sujeira', 'alagado']):
        return 'Estrutura & Espaço'
    
    # ALIMENTAÇÃO
    if any(p in texto_lower for p in ['comida', 'bebida', 'cerveja', 'agua', 'água', 'fome', 'sede', 'lanche']):
        return 'Alimentação & Bebidas'
    
    # PROGRAMAÇÃO (show, música, etc)
    if any(p in texto_lower for p in ['show', 'dj', 'banda', 'musica', 'música', 'artista', 'palco', 'som']):
        return 'Programação & Atrações'
    
    # CREDENCIAMENTO
    if any(p in texto_lower for p in ['ingresso', 'entrada', 'check-in', 'pulseira', 'bilheteria']):
        return 'Credenciamento & Ingressos'
    
    return 'Experiência Geral'

def reclassificar():
    with open(EVENTS_FILE, 'r', encoding='utf-8') as f:
        feedbacks = json.load(f)
    
    alterados = 0
    for fb in feedbacks:
        texto = fb.get('message', '')
        
        novo_sentimento = classificar_sentimento(texto)
        nova_categoria = classificar_categoria(texto)
        
        # Verificar se mudou
        if fb.get('urgency') != novo_sentimento or fb.get('category') != nova_categoria:
            alterados += 1
            print(f"'{texto}' | {fb.get('urgency')} → {novo_sentimento} | {fb.get('category')} → {nova_categoria}")
        
        # Atualizar
        fb['urgency'] = novo_sentimento
        fb['category'] = nova_categoria
        fb['sentiment'] = 'Positivo' if novo_sentimento == 'Positivo' else ('Negativo' if novo_sentimento in ['Critico', 'Urgente'] else 'Neutro')
    
    with open(EVENTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(feedbacks, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ Reclassificados: {alterados} de {len(feedbacks)} feedbacks")

if __name__ == '__main__':
    reclassificar()
