import os
import requests
import json
import hashlib
import hmac
import csv
import logging
import re
import secrets
from io import StringIO
from functools import wraps
from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from dotenv import load_dotenv
from datetime import datetime
from collections import Counter, defaultdict
from time import time as time_now
from event_store import EventStore
from meta_whatsapp import parse_webhook, verify_webhook_signature

# Load environment variables
load_dotenv()

app = Flask(__name__, static_folder='static', static_url_path='/static')
app.secret_key = os.getenv("SECRET_KEY") or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Strict",
    SESSION_COOKIE_SECURE=os.getenv("FLASK_ENV") == "production",
)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

REQUIRED_PRODUCTION_ENV = (
    "SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
    "PII_HASH_SECRET",
    "META_APP_SECRET",
    "META_VERIFY_TOKEN",
    "META_PHONE_NUMBER_ID",
    "SECRET_KEY",
    "ADMIN_USER",
    "ADMIN_PASS",
)

# Config
EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY")
EVOLUTION_INSTANCE_NAME = os.getenv("EVOLUTION_INSTANCE_NAME")
META_APP_SECRET = os.getenv("META_APP_SECRET", "")
META_VERIFY_TOKEN = os.getenv("META_VERIFY_TOKEN", "")
META_PHONE_NUMBER_ID = os.getenv("META_PHONE_NUMBER_ID", "")
ENABLE_EVOLUTION_WEBHOOK = os.getenv("ENABLE_EVOLUTION_WEBHOOK", "false").lower() == "true"

# Supabase Config
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
EVENT_STORE = EventStore()

# Initialize Supabase client (if configured)
supabase = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        from supabase import create_client, Client
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        logger.info("Cliente Supabase inicializado")
    except Exception as e:
        logger.error("Falha ao inicializar Supabase: %s", type(e).__name__)
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
            logger.info("Cliente Supabase reinicializado")
        except Exception as e:
            logger.error("Falha ao reinicializar Supabase: %s", type(e).__name__)
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
    
    logger.info("Solicitando mídia à Evolution")
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        logger.info("Resposta de mídia Evolution | status=%d", response.status_code)
        
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
    """Retorna somente feedbacks do evento configurado."""
    sb = get_supabase()
    if sb:
        try:
            response = (
                sb.table('feedbacks')
                .select('*')
                .eq('event_id', EVENT_STORE.event_id())
                .order('updated_at', desc=True)
                .limit(1000)
                .execute()
            )
            return response.data
        except Exception as e:
            logger.error("Falha ao consultar feedbacks: %s", type(e).__name__)
            # Try reconnecting once
            sb = _reconnect_supabase()
            if sb:
                try:
                    response = (
                        sb.table('feedbacks')
                        .select('*')
                        .eq('event_id', EVENT_STORE.event_id())
                        .order('updated_at', desc=True)
                        .limit(1000)
                        .execute()
                    )
                    return response.data
                except Exception as e2:
                    logger.error("Retry de feedbacks falhou: %s", type(e2).__name__)
    return []

def save_feedback(feedback_data):
    """Salva feedback no evento atual usando a sequence do PostgreSQL."""
    sb = get_supabase()
    if sb:
        try:
            payload = dict(feedback_data)
            payload.pop("id", None)
            payload.setdefault("event_id", EVENT_STORE.event_id())
            payload.setdefault("source", "evolution")
            sb.table('feedbacks').insert(payload).execute()
            return True
        except Exception as e:
            logger.error("Falha ao inserir feedback: %s", type(e).__name__)
            # Try reconnecting once
            sb = _reconnect_supabase()
            if sb:
                try:
                    sb.table('feedbacks').insert(payload).execute()
                    return True
                except Exception as e2:
                    logger.error("Retry de inserção falhou: %s", type(e2).__name__)
    return False

def update_feedback(feedback_id, updates):
    """Atualiza feedback somente dentro do evento configurado."""
    sb = get_supabase()
    if sb:
        try:
            response = (
                sb.table('feedbacks')
                .update(updates)
                .eq('id', feedback_id)
                .eq('event_id', EVENT_STORE.event_id())
                .execute()
            )
            return bool(response.data)
        except Exception as e:
            logger.error("Falha ao atualizar feedback: %s", type(e).__name__)
            sb = _reconnect_supabase()
            if sb:
                try:
                    response = (
                        sb.table('feedbacks')
                        .update(updates)
                        .eq('id', feedback_id)
                        .eq('event_id', EVENT_STORE.event_id())
                        .execute()
                    )
                    return bool(response.data)
                except Exception as e2:
                    logger.error("Retry de atualização falhou: %s", type(e2).__name__)
    return False

def get_active_feedback(remote_jid):
    """Verifica se existe um chamado Aberto ou Em Andamento para este número"""
    sb = get_supabase()
    if sb:
        try:
            response = sb.table('feedbacks')\
                .select("*")\
                .eq('event_id', EVENT_STORE.event_id())\
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
                        .eq('event_id', EVENT_STORE.event_id())\
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
            event_id = EVENT_STORE.event_id()
            categories_resp = sb.table('config').select('*').eq('event_id', event_id).eq('type', 'category').execute()
            regions_resp = sb.table('config').select('*').eq('event_id', event_id).eq('type', 'region').execute()
            return {
                "categories": [{"name": c['name'], "color": c.get('color', '#8b5cf6')} for c in categories_resp.data],
                "regions": [{"name": r['name']} for r in regions_resp.data]
            }
        except Exception as e:
            print(f"Supabase config error: {e}")
            sb = _reconnect_supabase()
            if sb:
                try:
                    event_id = EVENT_STORE.event_id()
                    categories_resp = sb.table('config').select('*').eq('event_id', event_id).eq('type', 'category').execute()
                    regions_resp = sb.table('config').select('*').eq('event_id', event_id).eq('type', 'region').execute()
                    return {
                        "categories": [{"name": c['name'], "color": c.get('color', '#8b5cf6')} for c in categories_resp.data],
                        "regions": [{"name": r['name']} for r in regions_resp.data]
                    }
                except Exception as e2:
                    print(f"Supabase config retry failed: {e2}")
            return {"categories": [], "regions": []}
    return {"categories": [], "regions": []}

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
                logger.info("Classificação de sentimento concluída | resultado=%s", v)
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
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        logger.info("Resposta enviada pela Evolution | status=%d", response.status_code)
    except Exception as e:
        logger.error("Falha ao enviar pela Evolution: %s", type(e).__name__)

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

@app.after_request
def add_security_headers(response):
    """Aplica headers defensivos sem interferir no webhook da Meta."""

    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


def public_feedback(feedback):
    """Remove identificadores pessoais antes de responder APIs do dashboard."""

    safe = {
        key: value
        for key, value in feedback.items()
        if key not in {"sender", "sender_hash", "name", "metadata", "inbox_message_id"}
    }
    safe["name"] = "Anônimo"
    participant_hash = feedback.get("sender_hash")
    safe["participant"] = participant_hash[:12] if participant_hash else None
    return safe


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated_function


@app.route("/health")
def health():
    """Health check usado pelo Coolify para web e dependência principal."""

    configuration_ok = all(os.getenv(name) for name in REQUIRED_PRODUCTION_ENV)
    database_ok = EVENT_STORE.healthcheck()
    return jsonify({
        "status": "ok" if database_ok and configuration_ok else "degraded",
        "configuration": "ok" if configuration_ok else "incomplete",
        "database": "ok" if database_ok else "unavailable",
    }), 200 if database_ok and configuration_ok else 503


@app.route("/webhook", methods=["GET"])
def meta_webhook_verify():
    """Responde ao challenge de configuração do webhook da Meta."""

    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token", "")
    challenge = request.args.get("hub.challenge")
    if (
        mode == "subscribe"
        and META_VERIFY_TOKEN
        and hmac.compare_digest(token, META_VERIFY_TOKEN)
        and challenge is not None
    ):
        return challenge, 200, {"Content-Type": "text/plain"}
    logger.warning("Challenge de webhook rejeitado")
    return jsonify({"error": "forbidden"}), 403


@app.route("/webhook", methods=["POST"])
def meta_webhook():
    """Valida, normaliza e persiste; processamento pesado fica no worker."""

    raw_body = request.get_data(cache=True)
    if not verify_webhook_signature(
        raw_body,
        request.headers.get("X-Hub-Signature-256"),
        META_APP_SECRET,
    ):
        logger.warning("Webhook Meta com assinatura inválida")
        return jsonify({"error": "invalid_signature"}), 401

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "invalid_json"}), 400

    try:
        messages, statuses = parse_webhook(payload)
        if META_PHONE_NUMBER_ID:
            messages = [
                message
                for message in messages
                if message.channel_account_id == META_PHONE_NUMBER_ID
            ]
        inserted = EVENT_STORE.ingest_messages(messages)
        EVENT_STORE.apply_message_statuses(statuses)
        logger.info(
            "Webhook Meta persistido | recebidas=%d novas=%d status=%d",
            len(messages),
            inserted,
            len(statuses),
        )
        return jsonify({"status": "accepted"}), 200
    except Exception as exc:
        # Um 503 faz a Meta repetir a entrega; retornar 200 perderia a mensagem.
        logger.error("Falha ao persistir webhook Meta: %s", type(exc).__name__)
        return jsonify({"error": "temporarily_unavailable"}), 503

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        
        admin_user = os.getenv("ADMIN_USER")
        admin_pass = os.getenv("ADMIN_PASS")
        
        if (
            admin_user
            and admin_pass
            and username
            and password
            and hmac.compare_digest(username, admin_user)
            and hmac.compare_digest(password, admin_pass)
        ):
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
    unique_senders = {
        f.get('sender_hash') or f.get('sender')
        for f in feedbacks
        if f.get('sender_hash') or f.get('sender')
    }
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
        sender = f.get('sender_hash') or f.get('sender', '')
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
    
    return jsonify([public_feedback(feedback) for feedback in feedbacks])

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
    writer = csv.DictWriter(output, fieldnames=['id', 'message', 'category', 'urgency', 'timestamp', 'status', 'region'])
    writer.writeheader()
    
    for fb in feedbacks:
        writer.writerow({
            'id': fb.get('id'),
            'message': fb.get('message'),
            'category': fb.get('category'),
            'urgency': fb.get('urgency'),
            'timestamp': fb.get('timestamp'),
            'status': fb.get('status', 'aberto'),
            'region': fb.get('region')
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
    return jsonify([public_feedback(feedback) for feedback in feedbacks]), 200, {
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

@app.route("/webhook/evolution", methods=["POST"])
def evolution_webhook():
    """Compatibilidade temporária, desativada por padrão e protegida por segredo."""

    if not ENABLE_EVOLUTION_WEBHOOK:
        return jsonify({"status": "disabled"}), 410
    configured_secret = os.getenv("EVOLUTION_WEBHOOK_SECRET", "")
    provided_secret = request.headers.get("X-Webhook-Secret", "")
    if (
        not configured_secret
        or not hmac.compare_digest(configured_secret, provided_secret)
    ):
        return jsonify({"error": "unauthorized"}), 401
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
                            logger.error("Base64 inválido: %s", type(e).__name__)

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
                    logger.info("Mensagem curta ignorada | tamanho=%d", len(text))
                    return jsonify({"status": "ignored_too_short"}), 200
                
                # 0b. Emoji-only filter
                if is_emoji_only(text):
                    logger.info("Mensagem somente com emoji ignorada")
                    return jsonify({"status": "ignored_emoji_only"}), 200
                
                # 0c. Rate limiting
                if is_rate_limited(remote_jid):
                    logger.info("Remetente limitado por excesso de mensagens")
                    send_whatsapp_message(remote_jid, "⚠️ Você já enviou várias mensagens recentes. Aguarde alguns minutos antes de enviar outra.")
                    return jsonify({"status": "rate_limited"}), 200
                
                # 1. Load Data for deduplication
                feedbacks = get_feedbacks()
                
                # 2. Deduplication using Hash
                msg_hash = hashlib.md5(f"{text}{remote_jid}".encode()).hexdigest()
                existing_hashes = {hashlib.md5(f"{fb.get('message', '')}{fb.get('sender', '')}".encode()).hexdigest() for fb in feedbacks}
                
                if msg_hash in existing_hashes:
                    logger.info("Mensagem duplicada ignorada")
                    return jsonify({"status": "ignored_duplicate"}), 200

                # --- CLASSIFY FIRST (needed for smart threading) ---
                logger.info("Processando mensagem legada")
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
        logger.exception("Falha crítica no webhook legado")
        return jsonify({"status": "error"}), 500

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
            "SUPABASE_SERVICE_ROLE_KEY": "OK" if os.getenv("SUPABASE_SERVICE_ROLE_KEY") else "MISSING",
            "OPENAI_API_KEY": "OK" if os.getenv("OPENAI_API_KEY") else "MISSING",
            "META_APP_SECRET": "OK" if os.getenv("META_APP_SECRET") else "MISSING",
            "META_ACCESS_TOKEN": "OK" if os.getenv("META_ACCESS_TOKEN") else "MISSING",
            "META_PHONE_NUMBER_ID": "OK" if os.getenv("META_PHONE_NUMBER_ID") else "MISSING",
            "EVENT_SLUG": os.getenv("EVENT_SLUG", "tropicadelia-2026")
        }
    })

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5001))
    print(f"Data Node V2 running on port {port}")
    app.run(host="0.0.0.0", port=port)
