import json
import hashlib

EVENTS_FILE = 'execution/events.json'

# Ler arquivo atual
try:
    with open(EVENTS_FILE, 'r', encoding='utf-8') as f:
        feedbacks = json.load(f)
except FileNotFoundError:
    print("Arquivo events.json nao encontrado.")
    exit()

print(f"[LIMPEZA] Total antes: {len(feedbacks)} feedbacks")

# Usar hash para identificar duplicatas
feedbacks_unicos = {}
for fb in feedbacks:
    # Hash based on message text + sender (if available) or just message
    unique_str = f"{fb.get('message', '')}{fb.get('sender', '')}" 
    texto_hash = hashlib.md5(unique_str.encode()).hexdigest()
    
    # Manter apenas o primeiro de cada
    if texto_hash not in feedbacks_unicos:
        feedbacks_unicos[texto_hash] = fb

feedbacks_limpos = list(feedbacks_unicos.values())

print(f"[LIMPEZA] Total depois: {len(feedbacks_limpos)} feedbacks")
print(f"[LIMPEZA] Removidos: {len(feedbacks) - len(feedbacks_limpos)} duplicatas")

# Salvar arquivo limpo
with open(EVENTS_FILE, 'w', encoding='utf-8') as f:
    json.dump(feedbacks_limpos, f, ensure_ascii=False, indent=2)

print("[LIMPEZA] Arquivo salvo!")
