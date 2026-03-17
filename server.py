import os
import requests
import json
import hashlib
import csv
import re
from io import StringIO
from functools import wraps
from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from dotenv import load_dotenv
from datetime import datetime
from collections import Counter, defaultdict
from time import time as time_now

# Load environment variables
load_dotenv()

app = Flask(__name__, static_folder='static', static_url_path='/static')
app.secret_key = os.getenv("SECRET_KEY", "nodedata-secret-key-2026")

# Config
EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY")
EVOLUTION_INSTANCE_NAME = os.getenv("EVOLUTION_INSTANCE_NAME")

# Supabase Config
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Initialize Supabase client (if configured)
supabase = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        from supabase import create_client, Client
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        print("✅ Supabase connected!")
    except Exception as e:
        print(f"⚠️ Supabase connection failed: {e}")
        supabase = None

def get_supabase():
    """Returns a working Supabase client, reconnecting if needed."""
    global supabase
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    if supabase is None:
        try:
            from supabase import create_client, Client
            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
            print("🔄 Supabase reconnected!")
        except Exception as e:
            print(f"⚠️ Supabase reconnection failed: {e}")
            return None
    return supabase

def _reconnect_supabase():
    """Force reconnect Supabase client."""
    global supabase
    supabase = None
    return get_supabase()

# Fallback to local JSON if Supabase not configured
EVENTS_FILE = 'execution/events.json'
CONFIG_FILE = 'execution/config.json'

# --- MEDIA & TRANSCRIPTION ---

def download_evolution_media(remote_jid, message_id):
    """Downloads media from Evolution API and returns binary content."""
    if not EVOLUTION_API_URL or not EVOLUTION_API_KEY or not EVOLUTION_INSTANCE_NAME:
        print(f"❌ [DOWNLOAD] Evolution API not configured: URL={EVOLUTION_API_URL}, KEY={'SET' if EVOLUTION_API_KEY else 'MISSING'}, INSTANCE={EVOLUTION_INSTANCE_NAME}")
        return None
    
    url = f"{EVOLUTION_API_URL}/chat/getBase64FromMediaMessage/{EVOLUTION_INSTANCE_NAME}"
    headers = {"apikey": EVOLUTION_API_KEY, "Content-Type": "application/json"}
    payload = {"message": {"key": {"id": message_id, "remoteJid": remote_jid, "fromMe": False}}, "convertToMp4": True}
    
    print(f"🔍 [DOWNLOAD] Requesting: POST {url}")
    print(f"🔍 [DOWNLOAD] Payload: {json.dumps(payload)}")
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        print(f"🔍 [DOWNLOAD] Response status: {response.status_code}")
        print(f"🔍 [DOWNLOAD] Response body (first 500 chars): {response.text[:500]}")
        
        if response.status_code in [200, 201]:
            import base64
            data = response.json()
            if "base64" in data:
                b64_content = data["base64"]
                # Handle data URI prefix (e.g., "data:audio/ogg;base64,...")
                if "," in b64_content and b64_content.startswith("data:"):
                    b64_content = b64_content.split(",", 1)[1]
                decoded = base64.b64decode(b64_content)
                print(f"✅ [DOWNLOAD] Decoded {len(decoded)} bytes of audio")
                return decoded
            else:
                print(f"❌ [DOWNLOAD] Response 200 but no 'base64' key. Keys: {list(data.keys())}")
        else:
            print(f"❌ [DOWNLOAD] Non-200 response: {response.status_code}")
        return None
    except Exception as e:
        print(f"❌ [DOWNLOAD] Exception: {e}")
        return None

def transcribe_audio(audio_content):
    """Transcribes audio content using OpenAI Whisper API."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or not audio_content:
        return None
    
    try:
        from openai import OpenAI
        from io import BytesIO
        client = OpenAI(api_key=api_key)
        
        # Whisper requires a file-like object with a name attribute
        audio_file = BytesIO(audio_content)
        audio_file.name = "audio.ogg"
        
        transcript = client.audio.transcriptions.create(
            model="whisper-1", 
            file=audio_file
        )
        return transcript.text
    except Exception as e:
        print(f"❌ Transcription error: {e}")
        return None

# --- HELPER FUNCTIONS ---

def load_json(filepath, default):
    """Fallback for local JSON files"""
    if not os.path.exists(filepath):
        return default
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return default

def save_json(filepath, data):
    """Fallback for local JSON files"""
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_feedbacks():
    """Get feedbacks from Supabase or local JSON"""
    sb = get_supabase()
    if sb:
        try:
            response = sb.table('feedbacks').select('*').order('updated_at', desc=True).execute()
            return response.data
        except Exception as e:
            print(f"Supabase error: {e}")
            # Try reconnecting once
            sb = _reconnect_supabase()
            if sb:
                try:
                    response = sb.table('feedbacks').select('*').order('updated_at', desc=True).execute()
                    return response.data
                except Exception as e2:
                    print(f"Supabase retry failed: {e2}")
            return load_json(EVENTS_FILE, [])
    return load_json(EVENTS_FILE, [])

def save_feedback(feedback_data):
    """Save feedback to Supabase or local JSON"""
    sb = get_supabase()
    if sb:
        try:
            sb.table('feedbacks').insert(feedback_data).execute()
            return True
        except Exception as e:
            print(f"Supabase insert error: {e}")
            # Try reconnecting once
            sb = _reconnect_supabase()
            if sb:
                try:
                    sb.table('feedbacks').insert(feedback_data).execute()
                    return True
                except Exception as e2:
                    print(f"Supabase insert retry failed: {e2}")
            # Fallback to local
            feedbacks = load_json(EVENTS_FILE, [])
            feedbacks.insert(0, feedback_data)
            save_json(EVENTS_FILE, feedbacks)
            return True
    else:
        feedbacks = load_json(EVENTS_FILE, [])
        feedbacks.insert(0, feedback_data)
        save_json(EVENTS_FILE, feedbacks)
        return True

def update_feedback(feedback_id, updates):
    """Update feedback in Supabase or local JSON"""
    sb = get_supabase()
    if sb:
        try:
            sb.table('feedbacks').update(updates).eq('id', feedback_id).execute()
            return True
        except Exception as e:
            print(f"Supabase update error: {e}")
            sb = _reconnect_supabase()
            if sb:
                try:
                    sb.table('feedbacks').update(updates).eq('id', feedback_id).execute()
                    return True
                except Exception as e2:
                    print(f"Supabase update retry failed: {e2}")
            # Fallback to local JSON
            feedbacks = load_json(EVENTS_FILE, [])
            for fb in feedbacks:
                if fb.get('id') == feedback_id:
                    fb.update(updates)
                    break
            save_json(EVENTS_FILE, feedbacks)
            return True
    else:
        feedbacks = load_json(EVENTS_FILE, [])
        for fb in feedbacks:
            if fb.get('id') == feedback_id:
                fb.update(updates)
                break
        save_json(EVENTS_FILE, feedbacks)
        return True

def get_active_feedback(remote_jid):
    """Verifica se existe um chamado Aberto ou Em Andamento para este número"""
    sb = get_supabase()
    if sb:
        try:
            response = sb.table('feedbacks')\
                .select("*")\
                .eq('sender', remote_jid)\
                .in_('status', ['aberto', 'em_andamento'])\
                .order('id', desc=True)\
                .limit(1)\
                .execute()
            if response.data and len(response.data) > 0:
                return response.data[0]
            return None
        except Exception as e:
            print(f"Erro ao buscar feedback ativo: {e}")
            sb = _reconnect_supabase()
            if sb:
                try:
                    response = sb.table('feedbacks')\
                        .select("*")\
                        .eq('sender', remote_jid)\
                        .in_('status', ['aberto', 'em_andamento'])\
                        .order('id', desc=True)\
                        .limit(1)\
                        .execute()
                    if response.data and len(response.data) > 0:
                        return response.data[0]
                except Exception as e2:
                    print(f"Supabase retry get_active_feedback failed: {e2}")
            return None
    else:
        # Local JSON fallback
        feedbacks = load_json(EVENTS_FILE, [])
        for fb in sorted(feedbacks, key=lambda x: x.get('id', 0), reverse=True):
            if fb.get('sender') == remote_jid and fb.get('status', 'aberto') in ['aberto', 'em_andamento']:
                return fb
        return None

def append_to_feedback(feedback_id, old_message, new_content, new_urgency=None):
    """Adiciona mensagem ao feedback existente e opcionalmente faz upgrade de urgência"""
    now = datetime.utcnow()
    time_str = now.strftime("%H:%M")
    updated_message = f"{old_message}\n\n[Atualização {time_str}]: {new_content}"
    data = {'message': updated_message, 'updated_at': now.isoformat()}
    if new_urgency:
        data['urgency'] = new_urgency
        data['sentiment'] = 'Negativo' if new_urgency in ['Critico', 'Urgente'] else 'Positivo' if new_urgency == 'Positivo' else 'Neutro'
    return update_feedback(feedback_id, data)

def get_config():
    """Get config from Supabase or local JSON"""
    sb = get_supabase()
    if sb:
        try:
            categories_resp = sb.table('config').select('*').eq('type', 'category').execute()
            regions_resp = sb.table('config').select('*').eq('type', 'region').execute()
            return {
                "categories": [{"name": c['name'], "color": c.get('color', '#8b5cf6')} for c in categories_resp.data],
                "regions": [{"name": r['name']} for r in regions_resp.data]
            }
        except Exception as e:
            print(f"Supabase config error: {e}")
            sb = _reconnect_supabase()
            if sb:
                try:
                    categories_resp = sb.table('config').select('*').eq('type', 'category').execute()
                    regions_resp = sb.table('config').select('*').eq('type', 'region').execute()
                    return {
                        "categories": [{"name": c['name'], "color": c.get('color', '#8b5cf6')} for c in categories_resp.data],
                        "regions": [{"name": r['name']} for r in regions_resp.data]
                    }
                except Exception as e2:
                    print(f"Supabase config retry failed: {e2}")
            return load_json(CONFIG_FILE, {"categories": [], "regions": []})
    return load_json(CONFIG_FILE, {"categories": [], "regions": []})

def get_next_id():
    """Get next ID for new feedback"""
    sb = get_supabase()
    if sb:
        try:
            response = sb.table('feedbacks').select('id').order('id', desc=True).limit(1).execute()
            if response.data:
                return response.data[0]['id'] + 1
            return 1
        except:
            return 1
    else:
        feedbacks = load_json(EVENTS_FILE, [])
        return len(feedbacks) + 1

# --- CLASSIFICATION FUNCTIONS (DETERMINISTIC - DO NOT CHANGE) ---

def classificar_sentimento(texto):
    """Classifica sentimento com gírias brasileiras"""
    texto_lower = texto.lower()
    
    # POSITIVO - verificar primeiro!
    palavras_positivas = [
        # Formais
        'lindo', 'maravilhoso', 'incrivel', 'incrível', 'excelente', 'perfeito', 
        'sensacional', 'fantastico', 'fantástico', 'adorei', 'amei', 'recomendo',
        # Gírias BR
        'top', 'show', 'bom', 'mto bom', 'muito bom', 'demais', 'd+', 'animal',
        'brabo', 'brabissimo', 'foda', 'monstro', 'sinistro', 'insano', 'irado',
        'maneiro', 'da hora', 'massa', 'dahora', 'firmeza', 'suave', 'de boa',
        'arrasou', 'arrasa', 'lacrou', 'mitou', 'arrebentou', 'bombando',
        'curti', 'curtindo', 'gostei', 'gostando', 'amando', 'to amando',
        'muito legal', 'legal demais', 'show de bola', 'nota 10', '10/10'
    ]
    for palavra in palavras_positivas:
        if palavra in texto_lower:
            return 'Positivo'
    
    # CRÍTICO - emergências e violência
    palavras_criticas = [
        # Violência/Crime
        'droga', 'assalto', 'roubo', 'roubaram', 'briga', 'brigando', 'arma',
        'agressao', 'agressão', 'perigo', 'violencia', 'violência', 'ferido',
        'sangue', 'sangrando', 'emergencia', 'emergência', 'socorro',
        # Gírias BR violência
        'pancadaria', 'porrada', 'treta', 'tretando', 'covardia', 'facada',
        'esfaqueado', 'tiro', 'tiroteio', 'navalhada', 'paulada', 'voadora',
        'baixaria', 'confusão geral', 'saiu na mão', 'saindo na mão',
        'desceu a porrada', 'meteu a mão', 'deu pau', 'pegou fogo',
        # Emergências médicas
        'desmaiou', 'desmaiada', 'desmaiado', 'desacordado', 'desacordada',
        'passou mal', 'passando mal', 'convulsão', 'convulsionando',
        'infarto', 'enfartando', 'parada cardiaca', 'não respira', 'sem pulso',
        'overdose', 'ambulancia', 'ambulância', 'samu', 'uti', 'hospital',
        'médico', 'medico', 'paramédico', 'socorrer', 'reanimacao', 'reanimação',
        # Acidentes graves
        'acidente', 'acidente grave', 'atropelado', 'atropelamento', 'capotou', 'explosao',
        'explosão', 'incendio', 'incêndio', 'fogo', 'queimando', 'desabou',
        'desmoronou', 'afogando', 'afogado', 'afogamento'
    ]
    for palavra in palavras_criticas:
        if palavra in texto_lower:
            return 'Critico'
    
    # URGENTE - problemas que precisam atenção rápida
    palavras_urgentes = [
        # Problemas estruturais
        'sujo', 'sujeira', 'alagado', 'alagamento', 'quebrado', 'quebrou',
        'nao funciona', 'não funciona', 'pifou', 'estragou', 'travou',
        'acabou', 'acabando', 'faltando', 'faltou', 'zerou', 'esgotou',
        # Filas e lotação
        'fila', 'fila gigante', 'fila enorme', 'lotado', 'lotação', 'cheio',
        'superlotado', 'apertado', 'empurra empurra', 'esmagado', 'pisoteio',
        # Reclamações fortes
        'pessimo', 'péssimo', 'horrivel', 'horrível', 'nojento', 'podre',
        'intragável', 'absurdo', 'vergonha', 'palhaçada', 'sacanagem',
        'descaso', 'desrespeito', 'inadmissível', 'inaceitável',
        # Acidentes leves
        'caiu', 'escorregou', 'tropeçou', 'machucou', 'ralou', 'cortou',
        'bateu', 'trombou', 'esbarrou', 'torceu', 'torção',
        # Gírias BR reclamação
        'ta osso', 'tá osso', 'ta foda', 'tá foda', 'paia', 'zoado',
        'zuado', 'uma bosta', 'uma merda', 'lixo', 'um lixo', 'demora',
        'demorando', 'atrasado', 'sem condição', 'sem condições'
    ]
    for palavra in palavras_urgentes:
        if palavra in texto_lower:
            return 'Urgente'
    
    # NEUTRO (padrão)
    return 'Neutro'

def classificar_categoria(texto):
    """Classifica categoria com gírias brasileiras"""
    texto_lower = texto.lower()
    
    # SEGURANÇA (verificar primeiro - emergências e violência)
    palavras_seguranca = [
        # Violência/Crime
        'briga', 'brigando', 'seguranca', 'segurança', 'assalto', 'roubo', 'roubaram',
        'pancadaria', 'porrada', 'treta', 'confusão', 'baixaria', 'facada', 'tiro',
        # Emergências médicas
        'desmaiou', 'desmaiada', 'desmaiado', 'passou mal', 'passando mal', 'socorrer',
        'emergencia', 'emergência', 'ambulancia', 'ambulância', 'samu', 'médico', 'medico',
        'convulsão', 'infarto', 'sangue', 'sangrando', 'ferido', 'machucado',
        # Acidentes
        'caiu', 'machucou', 'acidente', 'atropelado', 'desacordado', 'desacordada',
        # Outros
        'perigo', 'perigoso', 'suspeito', 'arma', 'faca', 'guarda', 'policia', 'polícia'
    ]
    if any(p in texto_lower for p in palavras_seguranca):
        return 'Segurança & Organização'
    
    # ESTRUTURA (banheiro, fila, instalações)
    palavras_estrutura = [
        'banheiro', 'privada', 'mictorio', 'mictório', 'toalete', 'wc',
        'estacionamento', 'vaga', 'estacionar',
        'fila', 'fila grande', 'fila enorme', 'lotado', 'cheio', 'superlotado',
        'temperatura', 'calor', 'quente demais', 'abafado', 'ar condicionado',
        'lixo', 'sujeira', 'sujo', 'alagado', 'alagamento', 'poça',
        'escuro', 'iluminação', 'luz', 'quebrado', 'quebrou', 'pifou'
    ]
    if any(p in texto_lower for p in palavras_estrutura):
        return 'Estrutura & Espaço'
    
    # ALIMENTAÇÃO
    palavras_alimentacao = [
        'comida', 'bebida', 'cerveja', 'chopp', 'agua', 'água', 'drink',
        'fome', 'sede', 'lanche', 'hamburguer', 'pizza', 'espetinho',
        'bar', 'copo', 'garrafa', 'gelo', 'gelado', 'quente',
        'caro', 'preço', 'precos', 'absurdo o preço'
    ]
    if any(p in texto_lower for p in palavras_alimentacao):
        return 'Alimentação & Bebidas'
    
    # PROGRAMAÇÃO (show, música, etc)
    palavras_programacao = [
        'show', 'dj', 'banda', 'musica', 'música', 'artista', 'cantor', 'cantora',
        'palco', 'som', 'audio', 'áudio', 'volume', 'alto', 'baixo demais',
        'atração', 'atracao', 'repertório', 'playlist', 'tocando'
    ]
    if any(p in texto_lower for p in palavras_programacao):
        return 'Programação & Atrações'
    
    # CREDENCIAMENTO
    palavras_credenciamento = [
        'ingresso', 'entrada', 'check-in', 'checkin', 'pulseira', 'bilheteria',
        'ticket', 'qr code', 'qrcode', 'cadastro', 'nome na lista', 'lista vip',
        'credencial', 'credenciamento', 'acesso negado', 'não deixou entrar'
    ]
    if any(p in texto_lower for p in palavras_credenciamento):
        return 'Credenciamento & Ingressos'
    
    # EXPERIÊNCIA GERAL (padrão)
    return 'Experiência Geral'

def classificar_regiao(texto):
    """Classifica região/local SEMPRE da mesma forma"""
    texto_lower = texto.lower()
    
    # VIP & Camarotes
    if any(p in texto_lower for p in ['camarote', 'vip', 'area vip', 'área vip', 'lounge']):
        return 'VIP & Camarotes'
    
    # Estacionamento
    if any(p in texto_lower for p in ['estacionamento', 'carro', 'moto', 'valet', 'estacionar']):
        return 'Estacionamento'
    
    # Entrada Principal
    if any(p in texto_lower for p in ['entrada', 'portao', 'portão', 'portaria', 'acesso', 'bilheteria']):
        return 'Entrada Principal'
    
    # Área de Bares
    if any(p in texto_lower for p in ['bar', 'bebida', 'cerveja', 'drink', 'chopp', 'copo']):
        return 'Área de Bares'
    
    # Área do Palco
    if any(p in texto_lower for p in ['palco', 'show', 'banda', 'dj', 'som', 'musica', 'música', 'artista']):
        return 'Área do Palco'
    
    # Praça de Alimentação
    if any(p in texto_lower for p in ['comida', 'lanche', 'alimentacao', 'alimentação', 'hamburguer', 'pizza', 'espetinho']):
        return 'Praça de Alimentação'
    
    # Pista Central
    if any(p in texto_lower for p in ['pista', 'grade', 'frente do palco', 'meio da pista']):
        return 'Pista Central'
    
    # Banheiros
    if any(p in texto_lower for p in ['banheiro', 'toalete', 'wc', 'mictorio', 'mictório', 'privada']):
        return 'Banheiros'
    
    # Bistrô
    if any(p in texto_lower for p in ['bistro', 'bistrô', 'restaurante']):
        return 'Bistrô'
    
    # N/A (não identificado)
    return 'N/A'

# --- AI SENTIMENT CLASSIFICATION (PRIMARY) ---
def classificar_sentimento_ia(texto):
    """Classifica sentimento usando IA como método principal. Retorna: Positivo, Critico, Urgente ou Neutro."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        
        prompt = f'''Classifique o SENTIMENTO desta mensagem de um participante em um evento.
A mensagem pode estar em QUALQUER idioma (português, inglês, espanhol, etc).
Mensagem: "{texto}"

Responda com UMA ÚNICA PALAVRA, exatamente uma destas opções:
- Critico (emergências, acidentes, violência, risco de vida, crimes, incêndios, desmoronamentos, pessoas feridas)
- Urgente (problemas sérios, reclamações fortes, coisas quebradas, sujeira grave, falhas de estrutura, aglomerações perigosas, falta de itens essenciais)
- Positivo (elogios, agradecimentos, aprovação, satisfação, diversão)
- Neutro (perguntas, informações, sugestões, dúvidas, comentários sem carga emocional)

Exemplos:
"acidente feio aqui" → Critico
"there was a fight near the stage" → Critico
"el baño está inundado" → Urgente
"banheiro tá nojento" → Urgente
"amazing show, loved it!" → Positivo
"show incrível, adorei" → Positivo
"what time does it start?" → Neutro
"que horas começa?" → Neutro

Responda APENAS a palavra, sem pontuação.'''

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=5,
            temperature=0
        )
        
        result = response.choices[0].message.content.strip()
        
        # Validar que é um dos valores esperados
        valid = ['Critico', 'Urgente', 'Positivo', 'Neutro']
        for v in valid:
            if v.lower() in result.lower():
                print(f"🤖 [IA-SENTIMENT] '{texto[:50]}...' → {v}")
                return v
        
        print(f"⚠️ [IA-SENTIMENT] Resposta inesperada: '{result}', usando fallback")
        return None
    except Exception as e:
        print(f"❌ [IA-SENTIMENT] Erro: {e}, usando fallback keywords")
        return None

# --- AI FULL CLASSIFICATION (LEGACY FALLBACK) ---
def classificar_com_ia(texto):
    """Usa IA para classificar categoria/regiao quando keywords são ambíguas"""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        
        prompt = f'''Classifique este feedback de um evento brasileiro.
Texto: "{texto}"

Responda APENAS em JSON com este formato exato:
{{
  "categoria": "Segurança & Organização" | "Estrutura & Espaço" | "Alimentação & Bebidas" | "Programação & Atrações" | "Credenciamento & Ingressos" | "Experiência Geral",
  "sentimento": "Positivo" | "Critico" | "Urgente" | "Neutro",
  "regiao": "VIP & Camarotes" | "Estacionamento" | "Entrada Principal" | "Área de Bares" | "Área do Palco" | "Praça de Alimentação" | "Pista Central" | "Banheiros" | "Bistrô" | "N/A"
}}

Regras:
- Critico = emergências médicas, violência, crimes
- Urgente = problemas estruturais, reclamações fortes
- Positivo = elogios
- Neutro = perguntas ou informações'''

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=100,
            temperature=0
        )
        
        result_text = response.choices[0].message.content.strip()
        if result_text.startswith('```'):
            result_text = result_text.split('```')[1]
            if result_text.startswith('json'):
                result_text = result_text[4:]
        
        return json.loads(result_text)
    except Exception as e:
        print(f"Erro IA classificação: {e}")
        return None

# --- AI RESPONSE FUNCTION ---
def generate_ai_response(text, category, urgency):
    """Generates a fun response using AI — like a friend who works at the event"""
    api_key = os.getenv("OPENAI_API_KEY")
    
    # Fallback if AI unavailable
    if not api_key:
        emoji_map = {"Positivo": "🎉", "Neutro": "👍", "Critico": "🚨", "Urgente": "⚠️"}
        emoji = emoji_map.get(urgency, "✅")
        return f"{emoji} Recebido! Obrigado pelo feedback!"
    
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        
        system_msg = '''You are a fun backstage crew member at a live event. You MUST detect the language of the participant's message and ALWAYS reply in THAT SAME LANGUAGE. This is your #1 rule.

Your personality:
- You're a young, energetic person stuck working backstage and jealous of the people enjoying the event
- You're FUNNY but never disrespectful
- You use casual slang natural to the detected language (Brazilian Portuguese gírias, American English slang, Dutch straattaal, Latin American Spanish slang)
- You use emojis moderately (2-4 per message)
- Your replies are SHORT (max 2-3 sentences, ideal for WhatsApp)
- NEVER mention being a robot, AI, system, or bot
- NEVER use corporate or formal language
- NEVER mention categories, classifications, or technical terms
- Respond as a REAL PERSON backstage
- The response should be so good the person screenshots it and shares with friends

LANGUAGE EXAMPLES:

Portuguese input → Portuguese reply:
"Show muito top!" → "UHUUUUL 🔥🔥 Aproveita por mim que eu tô preso aqui nos bastidores!! Manda um vídeo desse show que tô curiosão!! 🎶"
"Banheiro alagado" → "PQP sério isso?? 😤 Calma que JÁ tô mandando a equipe resolver isso AGORA! Aguenta firme!! 💪"

English input → English reply:
"Amazing show tonight!" → "YOOO no way!! 🔥🔥 I'm stuck backstage and SO jealous rn!! Send me a clip, I can only hear it from here!! 🎶😭"
"Bathroom is flooded" → "Yo for REAL?? 😤 I'm sending the crew over RIGHT NOW! Hang tight, they're on their way!! 💪🔧"

Dutch input → Dutch reply:
"Geweldige show vanavond!" → "WOOOOW echt waar!! 🔥🔥 Ik zit hier vast backstage en ben ZO jaloers!! Stuur me een filmpje, ik kan het alleen maar horen hiervandaan!! 🎶😭"
"Toilet is overstroomd" → "Serieus WAT?? 😤 Ik stuur het team er NU op af! Hou vol, ze komen eraan!! 💪🔧"
"Eten is echt lekker!" → "Jaaaa toch!! 🔥 En ik zit hier backstage met m'n boterhammetje 😭 Geniet ervan voor mij!! 🍕"
"De muziek is te hard" → "Oei dat is balen!! 😬 Ik geef het METEEN door aan het geluidsteam! Ze gaan het fixen!! 🎧💪"

Spanish input → Spanish reply:
"El show está increíble!" → "UFFF qué envidia!! 🔥🔥 Yo aquí atrapado trabajando y ustedes disfrutando!! Mándame un video porfa!! 🎶😭"
"El baño está inundado" → "No puede ser!! 😤 Ya estoy mandando al equipo para allá AHORA! Aguanta un momento!! 💪🔧"'''

        user_msg = f'''Sentiment: {urgency}
Category: {category}
Participant message: "{text}"

Generate ONE creative, unique reply (do NOT copy the examples). Reply in the SAME LANGUAGE as the participant's message:'''

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg}
            ],
            max_tokens=120,
            temperature=0.9
        )
        
        reply = response.choices[0].message.content.strip()
        
        # Remove quotes if AI added them
        if reply.startswith('"') and reply.endswith('"'):
            reply = reply[1:-1]
        
        print(f"🤖 [VIRAL-REPLY] Generated: {reply}")
        return reply
        
    except Exception as e:
        print(f"❌ [VIRAL-REPLY] Error: {e}, using fallback")
        # Fallback with minimal personality
        if urgency == "Positivo":
            return "🔥 Que massa!! Valeu demais pelo feedback! Aproveita muito!! 🎉"
        elif urgency in ["Critico", "Urgente"]:
            return "😤 Eita! Já tô passando pra equipe resolver isso AGORA! Valeu por avisar!! 💪"
        else:
            return "👍 Valeu por mandar! Já anotei aqui! Aproveita o evento!! 🎶"

def send_whatsapp_message(remote_jid, message):
    """Sends a text message using Evolution API."""
    if not EVOLUTION_API_URL or not EVOLUTION_API_KEY or not EVOLUTION_INSTANCE_NAME:
        print(f"❌ Evolution API not configured!")
        return
    
    url = f"{EVOLUTION_API_URL}/message/sendText/{EVOLUTION_INSTANCE_NAME}"
    headers = {
        "apikey": EVOLUTION_API_KEY,
        "Content-Type": "application/json"
    }
    payload = {"number": remote_jid, "text": message}
    
    print(f"📤 Sending WhatsApp reply to: {remote_jid}")
    print(f"📤 URL: {url}")
    print(f"📤 Message: {message}")
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        print(f"📤 Response Status: {response.status_code}")
        print(f"📤 Response Body: {response.text[:200]}")
    except Exception as e:
        print(f"❌ Error sending message: {e}")

# --- AI EVENT PULSE ---
def generate_ai_pulse(feedbacks):
    """Gera resumo inteligente do evento usando IA"""
    api_key = os.getenv("OPENAI_API_KEY")
    
    if not api_key or not feedbacks:
        return {"summary": "Aguardando feedbacks para análise...", "status": "waiting"}
    
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        
        # Pegar últimos 50 feedbacks
        recent = feedbacks[:50]
        
        # Contar sentimentos
        sentimentos = Counter([f.get('urgency', 'Neutro') for f in recent])
        categorias = Counter([f.get('category', 'Geral') for f in recent])
        
        # Montar contexto
        feedback_list = "\n".join([f"- [{f.get('urgency')}] {f.get('message')[:80]}" for f in recent[:20]])
        
        prompt = f'''Você é um analista de eventos. Analise os feedbacks recentes e gere um resumo MUITO CURTO (máximo 2 frases).

DADOS:
- Total feedbacks recentes: {len(recent)}
- Sentimentos: {dict(sentimentos)}
- Categorias: {dict(categorias)}

Últimos feedbacks:
{feedback_list}

FORMATO DA RESPOSTA:
1. Status geral (🟢 Ótimo / 🟡 Atenção / 🔴 Crítico)
2. Insight principal (o que mais se destaca)
3. Sugestão rápida se houver problema

Exemplo: "🟢 Evento estável! Show está sendo muito elogiado. Atenção: 2 reclamações sobre fila do bar norte."

Seja MUITO conciso, máximo 150 caracteres.'''

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=100,
            temperature=0.7
        )
        
        summary = response.choices[0].message.content.strip()
        
        # Determinar status baseado no resumo
        if "🔴" in summary or "crítico" in summary.lower():
            status = "critical"
        elif "🟡" in summary or "atenção" in summary.lower():
            status = "warning"
        else:
            status = "good"
        
        return {"summary": summary, "status": status}
        
    except Exception as e:
        print(f"Erro AI Pulse: {e}")
        return {"summary": "Não foi possível gerar análise.", "status": "error"}

# --- SPAM PROTECTION ---

# Rate Limiter: max messages per sender in a time window
rate_limit_store = defaultdict(list)  # {remoteJid: [timestamps]}
RATE_LIMIT_MAX = 3        # max messages per window
RATE_LIMIT_WINDOW = 600   # 10 minutes (in seconds)

def is_rate_limited(remote_jid):
    """Verifica se o número excedeu o limite de mensagens"""
    now = time_now()
    # Remove timestamps fora da janela
    rate_limit_store[remote_jid] = [t for t in rate_limit_store[remote_jid] if now - t < RATE_LIMIT_WINDOW]
    # Verifica limite
    if len(rate_limit_store[remote_jid]) >= RATE_LIMIT_MAX:
        return True
    rate_limit_store[remote_jid].append(now)
    return False

def is_emoji_only(text):
    """Verifica se a mensagem contém apenas emojis (sem texto real)"""
    # Remove emojis, espaços e caracteres especiais
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"  # emoticons
        "\U0001F300-\U0001F5FF"  # symbols & pictographs
        "\U0001F680-\U0001F6FF"  # transport & map
        "\U0001F1E0-\U0001F1FF"  # flags
        "\U00002702-\U000027B0"  # dingbats
        "\U000024C2-\U0001F251"  # enclosed characters
        "\U0001F900-\U0001F9FF"  # supplemental symbols
        "\U0001FA00-\U0001FA6F"  # chess symbols
        "\U0001FA70-\U0001FAFF"  # symbols extended
        "\U00002600-\U000026FF"  # misc symbols
        "\U0000FE00-\U0000FE0F"  # variation selectors
        "\U0000200D"             # zero width joiner
        "\U00002764"             # heart
        "\U0000FE0F"             # variation selector
        "]+", flags=re.UNICODE
    )
    cleaned = emoji_pattern.sub('', text).strip()
    return len(cleaned) == 0

MIN_MESSAGE_LENGTH = 3  # Mínimo de caracteres para processar

# --- IN-MEMORY MESSAGE ID DEDUPLICATION ---
# Evolution API fires the same message ID multiple times (queued/sent/delivered).
# This prevents duplicate processing regardless of race conditions with Supabase.
_processed_msg_ids = []
_MAX_MSG_ID_CACHE = 500  # keep last 500 IDs to avoid unbounded memory growth

def _is_already_processed(msg_id: str) -> bool:
    """Returns True if this Evolution message ID was already processed."""
    if not msg_id:
        return False
    if msg_id in _processed_msg_ids:
        return True
    _processed_msg_ids.append(msg_id)
    if len(_processed_msg_ids) > _MAX_MSG_ID_CACHE:
        _processed_msg_ids.pop(0)  # drop oldest
    return False


# --- AI REPORT SUMMARY ---
def generate_report_summary(feedbacks, sentiment, categories, regions, total, participants):
    """Gera resumo executivo do evento usando IA"""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return "Resumo indisponível — chave OpenAI não configurada."
    
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        
        # Prepare context
        positivo_pct = round((sentiment.get('Positivo', 0) / total * 100), 1) if total > 0 else 0
        critico_count = sentiment.get('Critico', 0)
        urgente_count = sentiment.get('Urgente', 0)
        
        sample_positive = [f.get('message', '')[:80] for f in feedbacks if f.get('urgency') == 'Positivo'][:5]
        sample_negative = [f.get('message', '')[:80] for f in feedbacks if f.get('urgency') in ['Critico', 'Urgente']][:5]
        
        top_cat = max(categories.items(), key=lambda x: x[1])[0] if categories else 'N/A'
        top_region = max(regions.items(), key=lambda x: x[1])[0] if regions else 'N/A'
        
        prompt = f'''Você é um analista de eventos profissional. Gere um RESUMO EXECUTIVO do evento baseado nos dados abaixo.

DADOS DO EVENTO:
- Total de feedbacks: {total}
- Participantes únicos: {participants}
- Satisfação: {positivo_pct}% positivo
- Alertas: {critico_count} críticos, {urgente_count} urgentes
- Categoria mais mencionada: {top_cat}
- Região mais ativa: {top_region}
- Distribuição: {dict(sentiment)}
- Categorias: {dict(categories)}

Elogios recebidos:
{chr(10).join(f"- {s}" for s in sample_positive) if sample_positive else "Nenhum"}

Problemas reportados:
{chr(10).join(f"- {s}" for s in sample_negative) if sample_negative else "Nenhum"}

FORMATO:
Escreva um resumo profissional de 4-5 frases que:
1. Comece com uma avaliação geral (evento foi positivo/neutro/problemático)
2. Destaque o ponto forte principal
3. Mencione os pontos de atenção se houver
4. Dê uma recomendação prática para o próximo evento
5. Finalize com uma métrica destaque

Seja profissional mas acessível. Use dados concretos. Não use emojis demais (máximo 2-3).'''

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
            temperature=0.7
        )
        
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"❌ [REPORT-AI] Error: {e}")
        return "Não foi possível gerar o resumo automático neste momento."

# --- ROUTES ---

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated_function

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        
        # Get env vars with defaults
        admin_user = os.getenv("ADMIN_USER", "admin")
        admin_pass = os.getenv("ADMIN_PASS", "nodedata123")
        
        if username == admin_user and password == admin_pass:
            session["logged_in"] = True
            return redirect("/")
        else:
            error = "Usuário ou senha incorretos."
            
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

@app.route("/")
@login_required
def index():
    return render_template("data_node.html")

@app.route("/relatorio")
@login_required
def relatorio():
    return render_template("relatorio.html")

@app.route("/qrcode")
@login_required
def qrcode_page():
    return render_template("qrcode.html")

@app.route("/api/relatorio")
@login_required
def api_relatorio():
    """Gera dados agregados para o relatório pós-evento"""
    feedbacks = get_feedbacks()
    
    if not feedbacks:
        return jsonify({"stats": {"total": 0, "participants": 0, "dateRange": "Sem dados", "duration": "--", "perHour": 0}, 
                        "sentiment": {}, "categories": {}, "regions": {}, "timeline": {},
                        "topPositive": [], "topNegative": [], "topParticipants": [], "aiSummary": "Sem dados para análise."})
    
    # --- STATS ---
    total = len(feedbacks)
    unique_senders = set(f.get('sender', '') for f in feedbacks)
    participants = len(unique_senders)
    
    # Date range
    timestamps = []
    for f in feedbacks:
        ts = f.get('timestamp', '')
        if ts:
            try:
                timestamps.append(datetime.fromisoformat(ts.replace('Z', '+00:00').split('+')[0]))
            except:
                pass
    
    if timestamps:
        first = min(timestamps)
        last = max(timestamps)
        date_range = f"{first.strftime('%d/%m/%Y %H:%M')} — {last.strftime('%d/%m/%Y %H:%M')}"
        duration_hours = max(1, int((last - first).total_seconds() / 3600))
        duration = f"{duration_hours}h de monitoramento"
        per_hour = round(total / duration_hours, 1)
    else:
        date_range = "Data não disponível"
        duration = "--"
        per_hour = 0
    
    # --- SENTIMENT ---
    sentiment = dict(Counter(f.get('urgency', 'Neutro') for f in feedbacks))
    
    # --- CATEGORIES ---
    categories = dict(Counter(f.get('category', 'Geral') for f in feedbacks))
    # Sort by value descending
    categories = dict(sorted(categories.items(), key=lambda x: x[1], reverse=True))
    
    # --- REGIONS ---
    regions = dict(Counter(f.get('region', 'N/A') for f in feedbacks if f.get('region') and f.get('region') != 'N/A'))
    regions = dict(sorted(regions.items(), key=lambda x: x[1], reverse=True))
    
    # --- TIMELINE (by hour) ---
    timeline = defaultdict(int)
    for ts in timestamps:
        hour_key = ts.strftime('%Hh')
        timeline[hour_key] += 1
    timeline = dict(sorted(timeline.items()))
    
    # --- TOP POSITIVE (max 5) ---
    positive = [f for f in feedbacks if f.get('urgency') == 'Positivo']
    top_positive = [{"message": f.get('message', ''), "category": f.get('category', ''), "name": f.get('name', 'Anônimo')} for f in positive[:5]]
    
    # --- TOP NEGATIVE (Critico + Urgente, max 5) ---
    negative = [f for f in feedbacks if f.get('urgency') in ['Critico', 'Urgente']]
    top_negative = [{"message": f.get('message', ''), "urgency": f.get('urgency', ''), "category": f.get('category', ''), "region": f.get('region', 'N/A'), "name": f.get('name', 'Anônimo')} for f in negative[:5]]
    
    # --- TOP PARTICIPANTS ---
    sender_counts = Counter()
    sender_names = {}
    for f in feedbacks:
        sender = f.get('sender', '')
        sender_counts[sender] += 1
        if f.get('name'):
            sender_names[sender] = f['name']
    
    top_participants = [{"name": sender_names.get(sender, 'Anônimo'), "count": count} for sender, count in sender_counts.most_common(6)]
    
    # --- AI SUMMARY ---
    ai_summary = generate_report_summary(feedbacks, sentiment, categories, regions, total, participants)
    
    return jsonify({
        "stats": {"total": total, "participants": participants, "dateRange": date_range, "duration": duration, "perHour": per_hour},
        "sentiment": sentiment,
        "categories": categories,
        "regions": regions,
        "timeline": timeline,
        "topPositive": top_positive,
        "topNegative": top_negative,
        "topParticipants": top_participants,
        "aiSummary": ai_summary
    })

@app.route("/api/events")
@login_required
def get_events():
    feedbacks = get_feedbacks()
    
    # Filtros via query params
    categoria = request.args.get('categoria')
    regiao = request.args.get('regiao')
    prioridade = request.args.get('prioridade')
    status_filter = request.args.get('status')
    
    if categoria:
        feedbacks = [f for f in feedbacks if f.get('category') == categoria]
    if regiao:
        feedbacks = [f for f in feedbacks if f.get('region') == regiao]
    if prioridade:
        feedbacks = [f for f in feedbacks if f.get('urgency') == prioridade]
    if status_filter:
        feedbacks = [f for f in feedbacks if f.get('status', 'aberto') == status_filter]
    
    return jsonify(feedbacks)

# Cache para AI Pulse (evita chamadas excessivas)
ai_pulse_cache = {"data": None, "timestamp": None}

@app.route("/api/ai-pulse")
@login_required
def get_ai_pulse():
    """Retorna resumo inteligente do evento via IA"""
    global ai_pulse_cache
    
    # Verificar cache (válido por 60 segundos)
    now = datetime.utcnow()
    if ai_pulse_cache["data"] and ai_pulse_cache["timestamp"]:
        cache_age = (now - ai_pulse_cache["timestamp"]).total_seconds()
        if cache_age < 60:  # Cache de 1 minuto
            return jsonify(ai_pulse_cache["data"])
    
    # Gerar novo resumo
    feedbacks = get_feedbacks()
    result = generate_ai_pulse(feedbacks)
    result["updated_at"] = now.isoformat()
    result["feedbacks_count"] = len(feedbacks)
    
    # Atualizar cache
    ai_pulse_cache = {"data": result, "timestamp": now}
    
    return jsonify(result)

@app.route("/api/export/csv")
@login_required
def export_csv():
    """Exporta feedbacks como CSV para download"""
    feedbacks = get_feedbacks()
    
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=['id', 'message', 'category', 'urgency', 'timestamp', 'status', 'sender', 'name'])
    writer.writeheader()
    
    for fb in feedbacks:
        writer.writerow({
            'id': fb.get('id'),
            'message': fb.get('message'),
            'category': fb.get('category'),
            'urgency': fb.get('urgency'),
            'timestamp': fb.get('timestamp'),
            'status': fb.get('status', 'aberto'),
            'sender': fb.get('sender'),
            'name': fb.get('name')
        })
    
    output.seek(0)
    return output.getvalue(), 200, {
        'Content-Type': 'text/csv; charset=utf-8',
        'Content-Disposition': 'attachment; filename=feedbacks.csv'
    }

@app.route("/api/export/json")
@login_required
def export_json():
    """Exporta feedbacks como JSON para download"""
    feedbacks = get_feedbacks()
    return jsonify(feedbacks), 200, {
        'Content-Disposition': 'attachment; filename=feedbacks.json'
    }

@app.route("/api/config", methods=["GET"])
@login_required
def get_config_route():
    """Retorna config com contagens calculadas dinamicamente dos feedbacks"""
    config = get_config()
    feedbacks = get_feedbacks()
    
    # Contar feedbacks por categoria
    category_counts = {}
    region_counts = {}
    
    for fb in feedbacks:
        cat = fb.get('category', '')
        reg = fb.get('region', '')
        
        if cat:
            category_counts[cat] = category_counts.get(cat, 0) + 1
        if reg and reg != 'N/A':
            region_counts[reg] = region_counts.get(reg, 0) + 1
    
    # Atualizar contagens nas categorias
    for cat in config.get('categories', []):
        cat['count'] = category_counts.get(cat['name'], 0)
    
    # Atualizar contagens nas regiões
    for reg in config.get('regions', []):
        reg['count'] = region_counts.get(reg['name'], 0)
    
    return jsonify(config)

@app.route("/api/insights")
@login_required
def get_insights():
    """Retorna Top 3 Elogios e Problemas"""
    feedbacks = get_feedbacks()
    
    elogios = {}
    problemas = {}
    
    for fb in feedbacks:
        texto = fb.get('message', '') or fb.get('text', '')
        sentimento = fb.get('urgency', 'Neutro')
        categoria = fb.get('category', 'Outros')
        topic = fb.get('topic', texto[:20] + '...')
        
        display_text = topic if topic != 'Geral' else texto

        # Agrupar elogios
        if sentimento == 'Positivo':
            if display_text not in elogios:
                elogios[display_text] = {'count': 0, 'topic': display_text}
            elogios[display_text]['count'] += 1
        
        # Agrupar problemas
        if sentimento in ['Critico', 'Urgente', 'Crítico']:
            if display_text not in problemas:
                problemas[display_text] = {'count': 0, 'topic': display_text}
            problemas[display_text]['count'] += 1
    
    top_elogios = [v for k, v in sorted(elogios.items(), key=lambda x: x[1]['count'], reverse=True)[:3]]
    top_problemas = [v for k, v in sorted(problemas.items(), key=lambda x: x[1]['count'], reverse=True)[:3]]
    
    return jsonify({
        'top_elogios': top_elogios,
        'top_problemas': top_problemas
    })

@app.route("/api/analytics/top")
@login_required
def get_top_analytics():
    """Returns data in the format data_node.html expects"""
    res = get_insights().get_json()
    return jsonify({
        "compliments": res['top_elogios'],
        "problems": res['top_problemas']
    })

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.json
    except Exception:
        return jsonify({"error": "invalid_json"}), 400
    
    try:
        event_type = data.get("type") or data.get("event")
        
        if event_type in ["message", "messages.upsert", "MESSAGES_UPSERT"]:
            msg_data = data.get("data", {})
            print(f"DEBUG [Eventos]: Incoming event {event_type}")
            print(f"DEBUG [Eventos]: Payload message keys: {list(msg_data.get('message', {}).keys())}")

            key = msg_data.get("key", {})

            # Ignore own (sent) messages immediately
            if key.get("fromMe"):
                return jsonify({"status": "ignored_self"}), 200

            # Ignore delivery/read receipts that have no actual message content
            message_content = msg_data.get("message", {})
            if not message_content:
                return jsonify({"status": "ignored_no_content"}), 200

            # In-memory dedup by Evolution message ID (handles duplicate webhook fires)
            msg_id = key.get("id", "")
            if _is_already_processed(msg_id):
                print(f"[DEDUP] Duplicate message ID {msg_id} — ignored")
                return jsonify({"status": "ignored_duplicate_id"}), 200

            remote_jid = key.get("remoteJid")
            push_name = msg_data.get("pushName", "Desconhecido")

            
            # Identify text or audio
            text = message_content.get("conversation") or message_content.get("extendedTextMessage", {}).get("text")
            
            # Check if Evolution already provided a transcription
            native_transcription = message_content.get("transcription")
            audio_msg = message_content.get("audioMessage")
            
            # Audio Processing
            if not text and audio_msg and remote_jid:
                seconds = audio_msg.get("seconds", 0)
                if seconds > 35:
                    print(f"[AUDIO] Ignored too long: {seconds}s")
                    send_whatsapp_message(remote_jid, "⚠️ O seu áudio é muito longo. Por favor, envie áudios de no máximo 35 segundos para que eu possa processar.")
                    return jsonify({"status": "audio_too_long"}), 200
                
                if native_transcription:
                    print(f"[AUDIO] Using native transcription from Evolution: {native_transcription}")
                    text = native_transcription
                else:
                    print(f"[AUDIO] Manual transcription required for {seconds}s audio...")
                    
                    # Check if base64 is available in message_content
                    import base64
                    audio_data = None
                    
                    # Case 1: Base64 in message_content (Standard Evolution Webhook Base64)
                    if "base64" in message_content:
                        print(f"[AUDIO] Found base64 in message_content")
                        try:
                            audio_data = base64.b64decode(message_content["base64"])
                        except Exception as e:
                            print(f"❌ Error decoding base64 from message_content: {e}")

                    # Case 2: Base64 in msg_data (Legacy/Alternative)
                    if not audio_data and "base64" in msg_data:
                        print(f"[AUDIO] Found base64 in msg_data")
                        try:
                            audio_data = base64.b64decode(msg_data["base64"])
                        except Exception as e:
                            print(f"❌ Error decoding base64 from msg_data: {e}")

                    # Case 2: Base64 in message content (audioMessage) - rarer but possible
                    if not audio_data and "base64" in audio_msg:
                        print(f"[AUDIO] Found base64 in audio_msg")
                        try:
                            audio_data = base64.b64decode(audio_msg["base64"])
                        except Exception as e:
                            print(f"❌ Error decoding base64 from audio_msg: {e}")
                    
                    # Case 3: Download from API (Fallback)
                    if not audio_data:
                        print(f"[AUDIO] No base64 found, attempting download...")
                        audio_data = download_evolution_media(remote_jid, msg_data.get("key", {}).get("id"))
                    
                    if audio_data:
                        print(f"[AUDIO] Audio data ready ({len(audio_data)} bytes). Starting Whisper...")
                        text = transcribe_audio(audio_data)
                        if not text:
                            print(f"❌ Whisper transcription returned None")
                            send_whatsapp_message(remote_jid, "❌ Não consegui transcrever seu áudio no momento. Tente novamente ou digite sua mensagem.")
                            return jsonify({"status": "transcription_failed"}), 200
                    else:
                        print(f"❌ Media download failed from Evolution")
                        send_whatsapp_message(remote_jid, "❌ Erro ao baixar o áudio para transcrição. Verifique a configuração da Evolution API.")
                        return jsonify({"status": "download_failed"}), 200

            if text and remote_jid:
                # 0. SPAM PROTECTION
                # 0a. Minimum length check
                if len(text.strip()) < MIN_MESSAGE_LENGTH:
                    print(f"[SPAM] Message too short ({len(text)} chars): {text}")
                    return jsonify({"status": "ignored_too_short"}), 200
                
                # 0b. Emoji-only filter
                if is_emoji_only(text):
                    print(f"[SPAM] Emoji-only message ignored: {text}")
                    return jsonify({"status": "ignored_emoji_only"}), 200
                
                # 0c. Rate limiting
                if is_rate_limited(remote_jid):
                    print(f"[RATE-LIMIT] {remote_jid} exceeded {RATE_LIMIT_MAX} msgs in {RATE_LIMIT_WINDOW}s")
                    send_whatsapp_message(remote_jid, "⚠️ Você já enviou várias mensagens recentes. Aguarde alguns minutos antes de enviar outra.")
                    return jsonify({"status": "rate_limited"}), 200
                
                # 1. Load Data for deduplication
                feedbacks = get_feedbacks()
                
                # 2. Deduplication using Hash
                msg_hash = hashlib.md5(f"{text}{remote_jid}".encode()).hexdigest()
                existing_hashes = {hashlib.md5(f"{fb.get('message', '')}{fb.get('sender', '')}".encode()).hexdigest() for fb in feedbacks}
                
                if msg_hash in existing_hashes:
                    print(f"[CACHE] Ignored Duplicate: {text}")
                    return jsonify({"status": "ignored_duplicate"}), 200

                # --- CLASSIFY FIRST (needed for smart threading) ---
                print(f"Processing Report: {text}")
                sentimento = classificar_sentimento_ia(text)  # IA first
                if not sentimento:
                    print(f"[FALLBACK] IA unavailable, using keywords for sentiment")
                    sentimento = classificar_sentimento(text)  # Keywords fallback
                
                # Category & Region
                categoria = classificar_categoria(text)
                regiao = classificar_regiao(text)
                
                # AI enrichment for ambiguous category/region
                if categoria == 'Experiência Geral':
                    print(f"[HYBRID] Category ambiguous, trying AI for enrichment...")
                    ia_result = classificar_com_ia(text)
                    if ia_result:
                        categoria = ia_result.get('categoria', categoria)
                        regiao = ia_result.get('regiao', regiao) if ia_result.get('regiao') != 'N/A' else regiao
                        print(f"[HYBRID] IA enriched: {categoria} / {regiao}")

                # --- SMART THREADING LOGIC ---
                # Se já existe um chamado aberto deste número, verifica categoria
                active_feedback = get_active_feedback(remote_jid)
                linked_from_id = None

                if active_feedback:
                    old_category = (active_feedback.get('category') or '').strip().lower()
                    new_category = (categoria or '').strip().lower()
                    same_category = old_category == new_category

                    if same_category:
                        # MESMA CATEGORIA → append ao card existente
                        print(f"[THREADING] Same category '{categoria}' — appending to feedback {active_feedback.get('id')}")

                        current_urgency = active_feedback.get('urgency', 'Neutro')
                        priority_map = {"Critico": 3, "Urgente": 2, "Positivo": 1, "Neutro": 0}
                        upgrade_urgency = sentimento if priority_map.get(sentimento, 0) > priority_map.get(current_urgency, 0) else None

                        append_to_feedback(active_feedback['id'], active_feedback['message'], text, upgrade_urgency)

                        # Resposta para a nova informação
                        try:
                            from openai import OpenAI
                            client_ai = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
                            thread_prompt = f'''You are a fun backstage crew member at a live event. The person already sent a message before and now sent an update.
New message: "{text}"
Upgraded urgency: {upgrade_urgency or 'none'}
Detect the language and reply in the SAME LANGUAGE. Max 2 sentences, casual and fun.
If urgency was upgraded to Critico/Urgente, be urgent but still human.
Acknowledge you\'re adding this info to their ticket. Keep it short.'''
                            resp = client_ai.chat.completions.create(
                                model="gpt-4o-mini",
                                messages=[{"role": "system", "content": thread_prompt}],
                                max_tokens=80,
                                temperature=0.8,
                                timeout=15
                            )
                            thread_reply = resp.choices[0].message.content.strip()
                        except Exception:
                            thread_reply = "Anotei aqui também! Já passei pra equipe. 💪"

                        send_whatsapp_message(remote_jid, thread_reply)
                        return jsonify({"status": "updated_existing"}), 200
                    else:
                        # CATEGORIA DIFERENTE → criar card novo, linkado ao anterior
                        print(f"[THREADING] Category changed '{old_category}' → '{categoria}' — creating NEW card linked to {active_feedback.get('id')}")
                        linked_from_id = active_feedback.get('id')
                # --- FIM SMART THREADING ---

                # Simple topic extraction
                topic = "Geral"
                text_lower = text.lower()
                if categoria != 'Experiência Geral':
                    topic = f"{categoria}"
                    if "banheiro" in text_lower: topic = "Banheiro Sujo" if sentimento == "Urgente" else "Banheiro"
                    elif "show" in text_lower: topic = "Show"
                    elif "fila" in text_lower: topic = "Fila"
                    elif "comida" in text_lower: topic = "Comida"
                else:
                    topic = text if len(text.split()) <= 3 else text[:20] + "..."

                now = datetime.utcnow()
                new_report = {
                    "id": get_next_id(),
                    "sender": remote_jid,
                    "name": push_name,
                    "message": text,
                    "timestamp": now.isoformat(),
                    "updated_at": now.isoformat(),
                    "category": categoria,
                    "region": regiao,
                    "urgency": sentimento,
                    "sentiment": "Positivo" if sentimento == "Positivo" else ("Negativo" if sentimento in ["Critico", "Urgente"] else "Neutro"),
                    "topic": topic.title(),
                    "status": "aberto",
                    "resolved_at": None
                }
                if linked_from_id:
                    new_report["linked_from"] = linked_from_id
                
                # Save feedback FIRST (before AI response to avoid data loss)
                save_feedback(new_report)
                
                # Reply (AI Generated) — wrapped in try/except so failure doesn't lose the saved data
                try:
                    reply = generate_ai_response(text, categoria, sentimento)
                    send_whatsapp_message(remote_jid, reply)
                except Exception as e:
                    print(f"❌ [WEBHOOK] AI reply failed: {e}")
                    # Send fallback reply
                    fallback = "👍 Valeu pelo feedback! Já foi registrado aqui! 🎶"
                    send_whatsapp_message(remote_jid, fallback)
                
                return jsonify({"status": "processed"}), 200

        return jsonify({"status": "ignored"}), 200

    except Exception as e:
        print(f"❌❌ [WEBHOOK CRITICAL] Unhandled error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/feedback/<int:feedback_id>/status", methods=["PUT"])
@login_required
def update_feedback_status(feedback_id):
    """Atualiza o status de um feedback"""
    data = request.json
    new_status = data.get('status')
    
    if new_status not in ['aberto', 'em_andamento', 'resolvido']:
        return jsonify({"error": "Status inválido"}), 400
    
    updates = {'status': new_status}
    if new_status == 'resolvido':
        updates['resolved_at'] = datetime.utcnow().isoformat()
    else:
        updates['resolved_at'] = None
    
    if update_feedback(feedback_id, updates):
        return jsonify({"success": True, "status": new_status})
    else:
        return jsonify({"error": "Feedback não encontrado"}), 404

@app.route("/api/debug")
@login_required
def debug_env():
    """Endpoint para verificar variáveis de ambiente no Coolify"""
    return jsonify({
        "status": "online",
        "env_check": {
            "SUPABASE_URL": "OK" if os.getenv("SUPABASE_URL") else "MISSING",
            "SUPABASE_KEY": "OK" if os.getenv("SUPABASE_KEY") else "MISSING",
            "OPENAI_API_KEY": "OK" if os.getenv("OPENAI_API_KEY") else "MISSING",
            "EVOLUTION_API_URL": os.getenv("EVOLUTION_API_URL", "MISSING"),
            "EVOLUTION_INSTANCE": os.getenv("EVOLUTION_INSTANCE_NAME", "MISSING"),
            "EVOLUTION_KEY_SET": "YES" if os.getenv("EVOLUTION_API_KEY") else "NO"
        }
    })

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5001))
    print(f"Data Node V2 running on port {port}")
    if supabase:
        print("📦 Using Supabase database")
    else:
        print("📁 Using local JSON files")
    app.run(host="0.0.0.0", port=port)
