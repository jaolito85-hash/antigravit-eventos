import os
import json
import hmac
import csv
import logging
import re
import secrets
from io import StringIO
from functools import wraps
from flask import Flask, request, jsonify, render_template, session, redirect
from dotenv import load_dotenv
from datetime import datetime, timezone
from collections import Counter, defaultdict
from typing import Any
from event_store import EventStore
from meta_whatsapp import (
    MetaWhatsAppClient,
    graph_api_version,
    parse_webhook,
    verify_webhook_signature,
)

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

# Momento em que este processo subiu. Serve para saber se um deploy entrou:
# sem isso não há como distinguir código novo de container antigo ainda no ar.
PROCESS_STARTED_AT = datetime.now(timezone.utc).isoformat()

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
META_APP_SECRET = os.getenv("META_APP_SECRET", "")
META_VERIFY_TOKEN = os.getenv("META_VERIFY_TOKEN", "")
META_PHONE_NUMBER_ID = os.getenv("META_PHONE_NUMBER_ID", "")

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

# --- TRANSCRIÇÃO DE ÁUDIO ---

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

# --- ACESSO A DADOS DO DASHBOARD ---

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


def get_config():
    """Retorna categorias e regiões configuradas para o evento atual."""
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
    # "falta cerveja" usa o presente; a lista antiga tinha só faltou/faltando
    # e o worker de produção classifica só por keywords (sem IA).
    if re.search(r"\bfalta(m)?\b", texto_lower):
        return 'Urgente'
    if re.search(r"\b(ta|tá|esta|está)\s+sem\b", texto_lower):
        return 'Urgente'

    palavras_urgentes = [
        # Problemas estruturais
        'sujo', 'sujeira', 'alagado', 'alagamento', 'quebrado', 'quebrou',
        'nao funciona', 'não funciona', 'pifou', 'estragou', 'travou',
        'acabou', 'acabando', 'faltando', 'faltou', 'zerou', 'esgotou',
        'nao tem mais', 'não tem mais', 'sem cerveja', 'sem chopp',
        'sem agua', 'sem água', 'sem copo', 'sem gelo', 'sem comida',
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
OPENAI_CLASSIFY_TIMEOUT = 15
# Verificado na API em 19/09/2026: esta chave devolve 403 para gpt-5.6-luna.
# gpt-5.4-mini responde e aceita tanto temperature quanto reasoning_effort.
DEFAULT_OPENAI_MODEL = "gpt-5.4-mini"


def _openai_model() -> str:
    return os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)


def _uses_reasoning_model(model: str) -> bool:
    """GPT-5.6 Luna/Terra/Sol não aceitam temperature; usam reasoning_effort."""
    name = model.lower()
    return name.startswith(("gpt-5", "gpt-6", "o1", "o3", "o4"))


def _openai_chat_client():
    """Cliente OpenAI só para classificação. Timeout evita travar o worker da Meta."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    from openai import OpenAI
    return OpenAI(api_key=api_key, timeout=OPENAI_CLASSIFY_TIMEOUT)


def _chat_completion_kwargs(messages, max_output_tokens: int, temperature: float = 0):
    """Monta o payload compatível com gpt-4o-mini e com gpt-5.6-luna."""
    model = _openai_model()
    kwargs = {"model": model, "messages": messages}
    if _uses_reasoning_model(model):
        kwargs["max_completion_tokens"] = max_output_tokens
        kwargs["reasoning_effort"] = "none"
    else:
        kwargs["max_tokens"] = max_output_tokens
        kwargs["temperature"] = temperature
    return kwargs


TIPOS_MENSAGEM = ("conversa", "relato")
URGENCIAS = ("Critico", "Urgente", "Positivo", "Neutro")


def triar_mensagem_ia(texto):
    """Uma chamada decide o tipo e a urgência da mensagem.

    Tipo separa conversa de relato, que é o que evita a fila de trabalho
    encher de "oi, tudo bem". Isso é julgamento de linguagem, então quem
    decide é a IA: lista de palavras em português não cobre a gíria de
    festival. Devolve None se a IA estiver fora, e aí o chamador usa o
    caminho determinístico.
    """

    client = _openai_chat_client()
    if not client:
        return None

    try:
        system = (
            "Você tria mensagens de WhatsApp de um festival. "
            "Interprete o SENTIDO, não procure palavras-chave.\n\n"
            "Responda APENAS com JSON: {\"tipo\": \"...\", \"urgencia\": \"...\"}\n\n"
            "tipo = conversa quando a pessoa só cumprimenta, agradece, se despede, "
            "puxa assunto ou testa o canal, sem informar nada e sem perguntar nada "
            "que a produção precise responder. Exemplos: \"oi\", \"salve, tudo bem?\", "
            "\"qual foi\", \"tmj\", \"obrigado!\", \"tchau\", \"teste\".\n"
            "tipo = relato quando a mensagem diz ALGO sobre o evento: estrutura, "
            "atendimento, atração, problema, pedido ou dúvida.\n"
            "ELOGIO É SEMPRE relato, nunca conversa, porque conta na satisfação "
            "do festival. \"show incrível\", \"amei o palco\" e \"a comida tá ótima\" "
            "são relato com urgencia Positivo.\n"
            "Cumprimento MAIS conteúdo é relato: \"bom dia, faltou cerveja\".\n"
            "Na dúvida entre os dois, escolha relato.\n\n"
            "urgencia = Critico para emergência, violência, acidente ou risco à vida.\n"
            "urgencia = Urgente para problema ou reclamação que a operação precisa "
            "resolver, incluindo falta de item, fila, sujeira, quebra e atraso.\n"
            "urgencia = Positivo para elogio, gratidão e satisfação.\n"
            "urgencia = Neutro para pergunta, informação ou conversa sem problema."
        )
        response = client.chat.completions.create(
            **_chat_completion_kwargs(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": texto},
                ],
                max_output_tokens=64,
            )
        )
        bruto = (response.choices[0].message.content or "").strip()
        if bruto.startswith("```"):
            bruto = bruto.split("```")[1]
            if bruto.startswith("json"):
                bruto = bruto[4:]

        dados = json.loads(bruto)
        tipo = str(dados.get("tipo", "")).strip().lower()
        urgencia = str(dados.get("urgencia", "")).strip()

        if tipo not in TIPOS_MENSAGEM:
            tipo = "relato"
        escolhida = next(
            (u for u in URGENCIAS if u.lower() == urgencia.lower()),
            None,
        )
        if not escolhida:
            logger.warning("Urgência inesperada da IA, usando fallback")
            return None

        logger.info("Triagem concluída | tipo=%s urgencia=%s", tipo, escolhida)
        return {"tipo": tipo, "urgencia": escolhida}
    except (ValueError, KeyError, TypeError):
        logger.warning("JSON inesperado na triagem, usando fallback")
        return None
    except Exception:
        logger.exception("Falha na triagem por IA, usando fallback")
        return None


def classificar_sentimento_ia(texto):
    """Só a urgência, para quem não precisa do tipo."""

    resultado = triar_mensagem_ia(texto)
    return resultado["urgencia"] if resultado else None


def triar_mensagem(texto):
    """Triagem com IA e caminho determinístico de reserva.

    Com a IA fora, o tipo sai do vocabulário de cortesia e a urgência das
    palavras-chave. É pior, mas ninguém fica sem resposta.
    """

    resultado = triar_mensagem_ia(texto)
    if resultado:
        return resultado
    return {
        "tipo": "conversa" if _is_greeting(texto) else "relato",
        "urgencia": classificar_sentimento(texto),
    }


def classificar_urgencia(texto: str) -> str:
    """IA no worker da Meta; palavras-chave só se a OpenAI estiver fora."""
    ia = classificar_sentimento_ia(texto)
    if ia:
        return ia
    return classificar_sentimento(texto)

# --- AI FULL CLASSIFICATION (LEGACY FALLBACK) ---
def classificar_com_ia(texto):
    """Usa IA para classificar categoria/regiao quando keywords são ambíguas"""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    
    try:
        client = _openai_chat_client()
        
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
- Urgente = problemas operacionais, reclamações, falta/escassez de itens
- Positivo = elogios
- Neutro = somente perguntas ou informações, nunca relato de problema'''

        response = client.chat.completions.create(
            **_chat_completion_kwargs(
                [{"role": "user", "content": prompt}],
                max_output_tokens=100,
                temperature=0,
            )
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
def generate_ai_response(text, category, urgency, sector_name=None, official_answer=None):
    """Generates a fun response using AI, like a friend who works at the event"""
    api_key = os.getenv("OPENAI_API_KEY")

    # Fallback if AI unavailable
    if not api_key:
        emoji_map = {"Positivo": "🎉", "Neutro": "👍", "Critico": "🚨", "Urgente": "⚠️"}
        emoji = emoji_map.get(urgency, "✅")
        return f"{emoji} Recebido! Obrigado pelo feedback!"
    
    try:
        client = _openai_chat_client()
        
        system_msg = '''You are ChatBob, a fun backstage crew member at the Tropicadelia festival in Brazil. You MUST detect the language of the participant's message and ALWAYS reply in THAT SAME LANGUAGE. This is your #1 rule.

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

        sector_line = f'\nThe participant scanned a QR code at this festival sector: "{sector_name}". Mention the place naturally in your reply (translated to their language if needed).' if sector_name else ''

        # Informacao oficial cadastrada pela producao: o conteudo e obrigatorio,
        # o jeito de dizer fica com a IA.
        official_line = ''
        if official_answer:
            official_line = (
                '\n\nOFFICIAL ANSWER FROM THE FESTIVAL STAFF (you MUST convey this '
                'information, keeping every fact exactly right, but say it in your own '
                f'voice and in the participant language):\n"{official_answer}"'
            )

        # Tom de voz extra configurado no painel.
        persona_line = ''
        try:
            persona = (EVENT_STORE.bot_settings() or {}).get('persona')
        except Exception:  # noqa: BLE001
            persona = None
        if persona:
            persona_line = f'\n\nEXTRA INSTRUCTIONS FROM THE ORGANIZERS:\n{persona}'
        user_msg = f'''Sentiment: {urgency}
Category: {category}
Participant message: "{text}"{sector_line}

Generate ONE creative, unique reply (do NOT copy the examples). Reply in the SAME LANGUAGE as the participant's message:'''
        user_msg += official_line + persona_line

        response = client.chat.completions.create(
            **_chat_completion_kwargs(
                [
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ],
                max_output_tokens=120,
                temperature=0.9,
            )
        )
        
        reply = response.choices[0].message.content.strip()
        
        # Remove quotes if AI added them
        if reply.startswith('"') and reply.endswith('"'):
            reply = reply[1:-1]

        # O WhatsApp usa *negrito* com um asterisco; **assim** apareceria cru.
        reply = re.sub(r"\*{2,}([^*]+)\*{2,}", r"*\1*", reply)
        reply = re.sub(r"_{2,}([^_]+)_{2,}", r"_\1_", reply)
        # Às vezes o modelo abre ênfase e não escreve nada dentro. Sobra um
        # "**" solto no meio da frase, então a marcação vazia é removida.
        reply = re.sub(r"[*_]+[\s\u200b\u200c\u200d]*[*_]+", " ", reply)
        reply = re.sub(r"[ \t]{2,}", " ", reply).strip()
        
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


# --- AI EVENT PULSE ---
def generate_ai_pulse(feedbacks):
    """Gera resumo inteligente do evento usando IA"""
    api_key = os.getenv("OPENAI_API_KEY")
    
    if not api_key or not feedbacks:
        return {"summary": "Aguardando feedbacks para análise...", "status": "waiting"}
    
    try:
        client = _openai_chat_client()
        
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
            **_chat_completion_kwargs(
                [{"role": "user", "content": prompt}],
                max_output_tokens=100,
                temperature=0.7,
            )
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

# --- FILTRO DE CONTEÚDO ---

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


# --- AI REPORT SUMMARY ---
def generate_report_summary(feedbacks, sentiment, categories, regions, total, participants):
    """Gera resumo executivo do evento usando IA"""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return "Resumo indisponível: chave OpenAI não configurada."
    
    try:
        client = _openai_chat_client()
        
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
            **_chat_completion_kwargs(
                [{"role": "user", "content": prompt}],
                max_output_tokens=300,
                temperature=0.7,
            )
        )
        
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"❌ [REPORT-AI] Error: {e}")
        return "Não foi possível gerar o resumo automático neste momento."

# --- BASE DE PERGUNTAS E RESPOSTAS ---

def _normalize(text):
    """Baixa caixa e remove acento para o casamento não depender de digitação."""

    import unicodedata

    lowered = str(text or "").lower()
    decomposed = unicodedata.normalize("NFD", lowered)
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def match_knowledge(content, entries=None):
    """Acha a resposta oficial para a mensagem, se existir uma cadastrada.

    Casamento determinístico de propósito: o operador precisa conseguir prever
    o que o bot vai responder. A IA entra depois, só para dar o tom.
    """

    if entries is None:
        try:
            entries = EVENT_STORE.knowledge()
        except Exception as e:
            logger.error("Base do bot indisponível: %s", type(e).__name__)
            return None

    alvo = _normalize(content)
    if not alvo:
        return None

    melhor = None
    melhor_peso = 0
    for entry in entries or []:
        if not entry.get("active", True):
            continue
        gatilhos = [g for g in (entry.get("keywords") or []) if g]
        # A própria pergunta cadastrada também serve de gatilho, pelas
        # palavras com mais de três letras que ela contém.
        termos = [t for t in _normalize(entry.get("question")).split() if len(t) > 3]

        peso = 0
        for gatilho in gatilhos:
            if _normalize(gatilho) in alvo:
                # Gatilho explícito vale mais que palavra solta da pergunta.
                peso += 10 + len(gatilho)
        if not peso:
            # Segundo nível: as palavras do gatilho, para "como pago" pegar
            # "como eu pago". Vale menos que o gatilho inteiro.
            palavras_alvo = set(alvo.split())
            for gatilho in gatilhos:
                partes = [w for w in _normalize(gatilho).split() if len(w) > 3]
                # Exige duas palavras: senão "show de" viraria só "show" e
                # pegaria qualquer elogio ao show.
                if len(partes) >= 2 and all(w in palavras_alvo for w in partes):
                    peso = max(peso, 5 + len(partes))

        if not peso and termos:
            # Terceiro nível: metade das palavras da própria pergunta.
            acertos = sum(1 for t in termos if t in alvo)
            if acertos >= max(2, len(termos) // 2):
                peso = acertos

        if peso:
            peso += int(entry.get("priority") or 0) / 100
            if peso > melhor_peso:
                melhor_peso = peso
                melhor = entry

    return melhor


# --- COMPORTAMENTO DO BOT (usado pelo worker e pelo simulador) ---

SECTOR_PATTERN = re.compile(
    r"^\s*#SETOR:([A-Z0-9][A-Z0-9_-]{0,49})\s*(?:\r?\n|\|)?\s*",
    flags=re.IGNORECASE,
)

# Saudação e agradecimento não viram card: são conversa, não informação
# operacional. A regra é de vocabulário, não de frase exata, porque no festival
# a pessoa escreve "oi tudo bem", "salve galera", "boa noite pessoal".
CUMPRIMENTOS = {
    "oi", "oie", "oii", "oiii", "ola", "opa", "opaa", "eae", "eai", "salve",
    "fala", "hey", "hei", "hi", "hello", "hola", "alo", "alow", "yo",
    "menu", "ajuda", "help", "start", "comecar", "iniciar",
}

# Agradecimento e despedida também são conversa, não chamado.
CORTESIAS = {
    "obrigado", "obrigada", "obrigadao", "brigado", "brigada", "valeu", "vlw",
    "tchau", "falou", "abraco", "abracos", "bjs", "beijos",
    "tudo", "bem", "bom", "boa", "td", "tb", "beleza", "blz", "suave",
    "firmeza", "tranquilo", "tranquila", "boaa", "como", "vai", "esta", "estao",
    "voce", "voces", "vc", "vcs", "ai", "la", "de", "e",
    "pessoal", "galera", "gente", "time", "equipe", "amigo", "amiga", "amigos",
    "mocada", "rapaziada", "povo", "chatbob", "bot", "por", "favor", "pfv",
    "dia", "tarde", "noite", "sim", "nao", "ok", "okay", "certo",
}

# Cumprimentos de duas palavras: a checagem por token isolado nao pega "bom
# dia" nem "e ai", porque nenhuma das palavras sozinha e um cumprimento.
CUMPRIMENTOS_COMPOSTOS = (
    "bom dia", "boa tarde", "boa noite", "boa madrugada",
    "e ai", "e ae", "fala ai", "fala tu", "tudo bem", "tudo bom",
    "como vai", "como vao", "beleza ai",
)

GREETING_MAX_LENGTH = 60


def _is_greeting(content: str) -> bool:
    """Diz se a mensagem é só cumprimento, agradecimento ou cortesia.

    Basta uma palavra fora do vocabulário, como "banheiro" ou "perdi", para a
    mensagem deixar de ser saudação e virar chamado.
    """

    if not content or len(content) > GREETING_MAX_LENGTH:
        return False

    # Normaliza e quebra em palavras, descartando pontuação e números.
    limpo = _normalize(content)
    palavras = [p for p in re.split(r"[^a-z]+", limpo) if p]
    if not palavras:
        return False

    AGRADECIMENTOS = {"obrigado", "obrigada", "obrigadao", "valeu", "vlw",
                      "brigado", "brigada", "tchau", "falou"}
    tem_cumprimento = (
        any(p in CUMPRIMENTOS or p in AGRADECIMENTOS for p in palavras)
        or any(frase in limpo for frase in CUMPRIMENTOS_COMPOSTOS)
    )
    if not tem_cumprimento:
        return False

    return all(p in CUMPRIMENTOS or p in CORTESIAS for p in palavras)


WELCOME_MESSAGE = (
    "🌴🔥 Bem-vindo(a) ao *ChatBob*, o canal oficial da *Tropicadelia 2026*!\n\n"
    "Eu levo sua voz direto para a sala de controle do festival. "
    "Me manda *texto ou áudio* contando:\n"
    "🚻 um problema (fila, banheiro, som, limpeza...)\n"
    "🎶 um elogio para o show ou para a estrutura\n"
    "🎒 algo que você perdeu ou encontrou\n\n"
    "⚡ Sua mensagem chega *na hora* para a equipe certa.\n\n"
    "🔒 *Dica de ouro:* o ChatBob é 100% gratuito e *NUNCA* pede Pix, "
    "senha ou pagamento."
)

def _extract_sector(content: str) -> tuple[str | None, str]:
    """Extrai o código do QR e devolve somente a mensagem do participante."""

    match = SECTOR_PATTERN.match(content)
    if not match:
        return None, content.strip()
    return match.group(1).upper(), content[match.end():].strip()


def welcome_text() -> str:
    """Boas-vindas configurada no painel, ou a padrão do produto."""

    try:
        custom = (EVENT_STORE.bot_settings() or {}).get("welcome")
    except Exception:  # noqa: BLE001
        custom = None
    return custom or WELCOME_MESSAGE


def _sector_prompt(sector: dict[str, Any] | None) -> str:
    """Convida a pessoa a relatar algo usando o CTA cadastrado do setor."""

    if not sector:
        return "Conte em poucas palavras (ou num áudio 🎤) o que aconteceu ou o que podemos melhorar."
    metadata = sector.get("metadata") or {}
    cta = metadata.get("cta") or "Conte o que está acontecendo por aí."
    return f"📍 Você está em *{sector['name']}*!\n{cta}\nPode mandar texto ou áudio 🎤"


def _topic(content: str, category: str, urgency: str) -> str:
    """Gera um rótulo curto e determinístico para o dashboard."""

    lowered = content.lower()
    if "banheiro" in lowered:
        return "Banheiro Sujo" if urgency == "Urgente" else "Banheiro"
    if "fila" in lowered:
        return "Fila"
    if "show" in lowered or "palco" in lowered:
        return "Show"
    if "comida" in lowered or "bebida" in lowered:
        return "Alimentação"
    return category if category != "Experiência Geral" else content[:80]


def _reply(urgency: str) -> str:
    """Responde sem prometer uma ação humana que ainda não foi confirmada."""

    if urgency == "Critico":
        return (
            "🚨 Recebemos seu alerta e ele foi marcado como prioridade máxima. "
            "Se houver risco imediato, procure agora a segurança ou equipe médica mais próxima."
        )
    if urgency == "Urgente":
        return "⚠️ Recebemos e destacamos sua mensagem para a equipe do evento. Obrigado por avisar!"
    if urgency == "Positivo":
        return "🎉 Que bom receber isso! Obrigado pelo feedback e aproveite o evento!"
    # Neutro costuma ser pergunta: não faz sentido agradecer por um relato
    # que a pessoa não fez.
    return (
        "✅ Recebi sua mensagem! Se for uma dúvida, a equipe do evento responde por aqui. "
        "Qualquer coisa, me chama de novo."
    )


def _classify(
    content: str,
    sector: dict[str, Any] | None,
    urgency: str | None = None,
) -> tuple[str, str, str]:
    """Classifica urgência, categoria e região com IA e fallback determinístico."""

    # Quando a triagem ja decidiu a urgencia, nao se paga outra chamada de IA.
    if not urgency:
        urgency = classificar_urgencia(content)

    category = classificar_categoria(content)
    region = str(sector["name"]) if sector else classificar_regiao(content)

    # Categoria ambígua: a IA tenta enriquecer sem substituir o setor do QR.
    if category == "Experiência Geral":
        try:
            enriched = classificar_com_ia(content)
        except Exception:  # noqa: BLE001
            enriched = None
        if enriched:
            category = enriched.get("categoria") or category
            if not sector and enriched.get("regiao") not in (None, "N/A"):
                region = enriched["regiao"]

    return urgency, category, region


def compose_smalltalk(content: str) -> str:
    """Responde um cumprimento no tom do bot, sem abrir chamado.

    A pessoa só puxou assunto. O bot cumprimenta de volta e diz em uma linha
    para que serve o canal. O texto de boas-vindas configurado no painel entra
    quando a IA estiver fora, para ninguém ficar sem resposta.
    """

    convite = welcome_text()
    client = _openai_chat_client()
    if not client:
        return convite

    try:
        system = (
            "Você é o ChatBob, atendente animado da Tropicadelia 2026, festival "
            "em Londrina. A pessoa só te cumprimentou ou agradeceu, não relatou "
            "nada.\n"
            "Responda em no máximo 2 frases curtas, no idioma da pessoa, com a "
            "energia de quem trabalha nos bastidores do festival. Use 1 ou 2 "
            "emojis.\n"
            "Cumprimente de volta e diga em UMA linha que ela pode te mandar "
            "problema, elogio ou dúvida do evento, por texto ou áudio, que você "
            "leva para a equipe.\n"
            "Nunca diga que é robô, IA ou sistema. Nunca peça Pix, senha ou "
            "pagamento."
        )
        persona = (EVENT_STORE.bot_settings() or {}).get("persona")
        if persona:
            system += f"\n\nINSTRUÇÕES DOS ORGANIZADORES:\n{persona}"

        response = client.chat.completions.create(
            **_chat_completion_kwargs(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": content},
                ],
                max_output_tokens=120,
                temperature=0.9,
            )
        )
        reply = (response.choices[0].message.content or "").strip()
        if reply.startswith('"') and reply.endswith('"'):
            reply = reply[1:-1]
        reply = re.sub(r"\*{2,}([^*]+)\*{2,}", r"*\1*", reply)
        reply = re.sub(r"[*_]+[\s\u200b\u200c\u200d]*[*_]+", " ", reply)
        return re.sub(r"[ \t]{2,}", " ", reply).strip() or convite
    except Exception as exc:  # noqa: BLE001 - conversa nunca derruba o fluxo
        logger.error("IA de conversa indisponível | erro=%s", type(exc).__name__)
        return convite


def _compose_reply(
    content: str,
    category: str,
    urgency: str,
    sector: dict[str, Any] | None,
    transcribed: bool,
) -> str:
    """Monta a resposta: crítico é sempre o protocolo fixo, o resto ganha IA."""

    prefix = "🎤 *Ouvi seu áudio!*\n\n" if transcribed else ""
    if urgency == "Critico":
        return prefix + _reply(urgency)

    # Elogio não é pergunta: a base de perguntas não entra aí, senão um
    # "show incrível" voltaria com o horário do line-up.
    known = match_knowledge(content) if urgency != "Positivo" else None
    sector_name = str(sector["name"]) if sector else None
    try:
        reply = generate_ai_response(
            content, category, urgency, sector_name,
            official_answer=(known or {}).get("answer"),
        )
        if reply:
            return prefix + reply
    except Exception as exc:  # noqa: BLE001 - resposta criativa é opcional
        logger.error("IA de resposta indisponível | erro=%s", type(exc).__name__)

    if known:
        # Sem IA, o texto oficial vai como está: é melhor soar formal do que
        # deixar a pergunta sem a informação correta.
        return prefix + known["answer"]
    return prefix + _reply(urgency)


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
        "started_at": PROCESS_STARTED_AT,
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

@app.route("/telao")
@login_required
def telao():
    """Modo telão da sala de controle: planta ao vivo em tela cheia."""
    return render_template("telao.html")

# Ordem de gravidade usada para pintar cada setor no mapa da planta.
_URGENCY_RANK = {"Critico": 3, "Urgente": 2, "Neutro": 1, "Positivo": 0}


def aggregate_sectors(feedbacks):
    """Cruza os feedbacks com os setores da planta.

    Usada pelo mapa ao vivo e pelo relatório pós-evento, para os dois nunca
    divergirem na conta.
    """
    try:
        sectors = EVENT_STORE.list_sectors()
    except Exception as e:
        logger.error("Falha ao listar setores: %s", type(e).__name__)
        return []

    # Índices por sector_id e por nome (fallback para feedbacks sem QR)
    by_sector_id = defaultdict(list)
    by_region_name = defaultdict(list)
    for fb in feedbacks:
        if fb.get("sector_id"):
            by_sector_id[str(fb["sector_id"])].append(fb)
        elif fb.get("region") and fb.get("region") != "N/A":
            by_region_name[fb["region"]].append(fb)

    result = []
    for sector in sectors:
        metadata = sector.get("metadata") or {}
        matched = list(by_sector_id.get(str(sector.get("id")), []))
        matched += by_region_name.get(sector.get("name"), [])

        open_items = [f for f in matched if (f.get("status") or "aberto") != "resolvido"]
        counts = Counter(f.get("urgency", "Neutro") for f in matched)
        open_counts = Counter(f.get("urgency", "Neutro") for f in open_items)

        worst = "ok"
        if open_counts:
            worst = max(open_counts, key=lambda u: _URGENCY_RANK.get(u, 0))
            if _URGENCY_RANK.get(worst, 0) == 0 and len(open_counts) == 1:
                worst = "Positivo"

        last_ts = None
        for f in matched:
            ts = f.get("updated_at") or f.get("timestamp")
            if ts and (last_ts is None or ts > last_ts):
                last_ts = ts

        result.append({
            "code": sector.get("code"),
            "name": sector.get("name"),
            "zone": metadata.get("zone"),
            "coord": metadata.get("coord"),
            "team": metadata.get("team"),
            "cta": metadata.get("cta"),
            "total": len(matched),
            "open": len(open_items),
            "counts": dict(counts),
            "openCounts": dict(open_counts),
            "worst": worst,
            "statusCounts": dict(Counter(
                f.get("status") or "aberto" for f in matched
            )),
            "lastAt": last_ts,
            # O painel de detalhe cruza estes ids com /api/events, em vez
            # de repetir no JavaScript a regra de casamento por setor.
            "feedbackIds": [f.get("id") for f in matched if f.get("id") is not None],
        })

    return result


@app.route("/api/sectors")
@login_required
def api_sectors():
    """Setores da planta com termômetro operacional agregado dos feedbacks."""
    return jsonify({
        "sectors": aggregate_sectors(get_feedbacks()),
        "generatedAt": datetime.utcnow().isoformat(),
    })


@app.route("/api/relatorio")
@login_required
def api_relatorio():
    """Gera dados agregados para o relatório pós-evento"""
    feedbacks = get_feedbacks()
    
    if not feedbacks:
        return jsonify({"stats": {"total": 0, "participants": 0, "dateRange": "Sem dados", "duration": "--", "perHour": 0}, 
                        "sentiment": {}, "categories": {}, "regions": {}, "timeline": {},
                        "topPositive": [], "topNegative": [], "topParticipants": [],
                        "sectors": [], "zones": [], "aiSummary": "Sem dados para análise."})
    
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
        date_range = f"{first.strftime('%d/%m/%Y %H:%M')} a {last.strftime('%d/%m/%Y %H:%M')}"
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
    
    # --- DESEMPENHO POR SETOR DA PLANTA ---
    sector_rows = [s for s in aggregate_sectors(feedbacks) if s["total"] > 0]
    sector_rows.sort(key=lambda s: (-s["total"], s["name"]))

    sectors_report = []
    for sector in sector_rows:
        counts = sector["counts"]
        negativos = counts.get("Critico", 0) + counts.get("Crítico", 0) + counts.get("Urgente", 0)
        positivos = counts.get("Positivo", 0)
        sectors_report.append({
            "name": sector["name"],
            "zone": sector["zone"],
            "total": sector["total"],
            "positive": positivos,
            "negative": negativos,
            "critical": counts.get("Critico", 0) + counts.get("Crítico", 0),
            "open": sector["open"],
            # Percentual de aprovação do setor, para ranquear o que funcionou.
            "approval": round(positivos / sector["total"] * 100) if sector["total"] else 0,
        })

    # --- CONSOLIDADO POR MACROZONA ---
    zone_totals = defaultdict(lambda: {"total": 0, "positive": 0, "negative": 0, "sectors": 0})
    for sector in sectors_report:
        zone = sector["zone"] or "Sem zona"
        bucket = zone_totals[zone]
        bucket["total"] += sector["total"]
        bucket["positive"] += sector["positive"]
        bucket["negative"] += sector["negative"]
        bucket["sectors"] += 1

    zones_report = [
        {
            "name": name,
            "total": data["total"],
            "positive": data["positive"],
            "negative": data["negative"],
            "sectors": data["sectors"],
            "approval": round(data["positive"] / data["total"] * 100) if data["total"] else 0,
        }
        for name, data in sorted(zone_totals.items(), key=lambda kv: -kv[1]["total"])
    ]

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
        "sectors": sectors_report,
        "zones": zones_report,
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
    setor = request.args.get('setor')
    topico = request.args.get('topico')
    atendimento = request.args.get('atendimento')

    if setor:
        # Usa a mesma agregacao do mapa para o filtro nao divergir do pin.
        alvo = next(
            (s for s in aggregate_sectors(feedbacks) if s["code"] == setor),
            None,
        )
        permitidos = set(alvo["feedbackIds"]) if alvo else set()
        feedbacks = [f for f in feedbacks if f.get('id') in permitidos]
    
    if categoria:
        feedbacks = [f for f in feedbacks if f.get('category') == categoria]
    if regiao:
        feedbacks = [f for f in feedbacks if f.get('region') == regiao]
    if prioridade:
        feedbacks = [f for f in feedbacks if f.get('urgency') == prioridade]
    if status_filter:
        feedbacks = [f for f in feedbacks if f.get('status', 'aberto') == status_filter]
    if topico:
        feedbacks = [f for f in feedbacks if f.get('topic') == topico]
    
    # Quem esta em atendimento humano precisa aparecer no proprio chamado,
    # senao a equipe responde por cima de uma conversa que alguem assumiu.
    try:
        modos = EVENT_STORE.conversation_modes()
    except Exception as e:
        logger.error("Falha ao ler modos de atendimento: %s", type(e).__name__)
        modos = {}

    if atendimento == 'humano':
        feedbacks = [
            f for f in feedbacks
            if modos.get(f.get('sender_hash')) == 'human'
        ]

    saida = []
    for feedback in feedbacks:
        item = public_feedback(feedback)
        item['humanAttended'] = modos.get(feedback.get('sender_hash')) == 'human'
        saida.append(item)
    return jsonify(saida)

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

# --- CHAMADO COMPLETO ---

@app.route("/api/feedback/<int:feedback_id>")
@login_required
def feedback_detail(feedback_id):
    """Chamado com a mensagem inteira e o que o bot respondeu.

    A lista do painel mostra o essencial; aqui vem o texto completo, as
    atualizações que a pessoa mandou depois e a resposta enviada, com o
    estado de entrega. É o que o operador precisa para entender o caso.
    """

    try:
        feedback = EVENT_STORE.feedback_by_id(feedback_id)
    except Exception as e:
        logger.error("Falha ao carregar chamado: %s", type(e).__name__)
        return jsonify({"error": "unavailable"}), 503

    if not feedback:
        return jsonify({"error": "not_found"}), 404

    try:
        replies = EVENT_STORE.replies_for_feedback(feedback_id)
    except Exception as e:
        logger.error("Falha ao carregar respostas: %s", type(e).__name__)
        replies = []

    return jsonify({
        "feedback": public_feedback(feedback),
        "replies": replies,
        # O painel abre a conversa desta pessoa a partir daqui.
        "hasConversation": bool(feedback.get("sender_hash")),
    })


# --- SIMULADOR E CONFIGURAÇÃO DO CHATBOB ---

MAX_SIMULATE_LENGTH = 900


@app.route("/chatbob")
@login_required
def chatbob_page():
    """Tela para testar e configurar o bot."""

    return render_template("chatbob.html")


@app.route("/api/simulate", methods=["POST"])
@login_required
def api_simulate():
    """Responde como o bot responderia no WhatsApp, sem gravar nem enviar.

    Usa exatamente as mesmas funções do worker, então o que aparece aqui é o
    que o participante receberia. Nenhum feedback é criado e nada sai para a
    Meta: é uma simulação para os sócios experimentarem o bot.
    """

    payload = request.get_json(silent=True) or {}
    content_raw = str(payload.get("content") or "").strip()
    sector_code = (payload.get("setor") or "").strip().upper() or None

    if not content_raw:
        return jsonify({"error": "escreva uma mensagem"}), 400
    if len(content_raw) > MAX_SIMULATE_LENGTH:
        return jsonify({"error": "mensagem muito longa"}), 400

    # O QR do setor entra como o participante enviaria, na primeira linha.
    if sector_code and not content_raw.upper().startswith("#SETOR:"):
        content_raw = f"#SETOR:{sector_code}\n{content_raw}"

    code, content = _extract_sector(content_raw)
    sector = None
    if code:
        try:
            sector = EVENT_STORE.sector_by_code(code)
        except Exception as e:
            logger.error("Falha ao resolver setor na simulação: %s", type(e).__name__)

    triagem = triar_mensagem(content)
    if triagem["tipo"] == "conversa":
        return jsonify({
            "reply": compose_smalltalk(content),
            "kind": "conversa",
            "explain": "A IA entendeu que é só conversa, sem relato: o bot responde no tom "
                       "dele e não abre chamado.",
            "sector": sector["name"] if sector else None,
            "createsCard": False,
        })

    if len(content) < 3 or is_emoji_only(content):
        return jsonify({
            "reply": _sector_prompt(sector),
            "kind": "convite",
            "explain": "Mensagem curta ou só emoji: o bot convida a pessoa a contar o que houve.",
            "sector": sector["name"] if sector else None,
            "createsCard": False,
        })

    urgency, category, region = _classify(content, sector, urgency=triagem["urgencia"])
    known = match_knowledge(content) if urgency != "Positivo" else None
    reply = _compose_reply(content, category, urgency, sector, False)

    if urgency == "Critico":
        explain = "Crítico: o bot usa o protocolo fixo e orienta procurar a equipe, sem texto criativo."
    elif known:
        explain = f'Respondido pela base: "{known["question"]}".'
    else:
        explain = "Sem pergunta cadastrada para isso: o bot responde no tom dele e registra o chamado."

    return jsonify({
        "reply": reply,
        "kind": "chamado",
        "urgency": urgency,
        "category": category,
        "region": region,
        "sector": sector["name"] if sector else None,
        "topic": _topic(content, category, urgency),
        "matched": {"question": known["question"], "id": known["id"]} if known else None,
        "explain": explain,
        "createsCard": True,
    })


@app.route("/api/bot/knowledge", methods=["GET"])
@login_required
def list_knowledge():
    """Base completa, inclusive as perguntas desativadas."""

    try:
        return jsonify({"entries": EVENT_STORE.knowledge(only_active=False)})
    except Exception as e:
        logger.error("Falha ao listar base do bot: %s", type(e).__name__)
        return jsonify({"error": "unavailable"}), 503


@app.route("/api/bot/knowledge", methods=["POST"])
@login_required
def save_knowledge_route():
    """Cria ou atualiza uma pergunta e resposta."""

    payload = request.get_json(silent=True) or {}
    question = str(payload.get("question") or "").strip()
    answer = str(payload.get("answer") or "").strip()
    if len(question) < 3:
        return jsonify({"error": "escreva a pergunta"}), 400
    if not answer:
        return jsonify({"error": "escreva a resposta"}), 400

    keywords = payload.get("keywords")
    if isinstance(keywords, str):
        keywords = [k.strip() for k in keywords.split(",")]

    try:
        entry = EVENT_STORE.save_knowledge({
            "id": payload.get("id"),
            "question": question,
            "answer": answer,
            "keywords": keywords or [],
            "priority": payload.get("priority", 50),
            "active": payload.get("active", True),
        })
    except Exception as e:
        logger.error("Falha ao salvar pergunta: %s", type(e).__name__)
        return jsonify({"error": "não foi possível salvar"}), 503
    return jsonify({"success": True, "entry": entry})


@app.route("/api/bot/knowledge/<entry_id>", methods=["DELETE"])
@login_required
def delete_knowledge_route(entry_id):
    """Remove uma pergunta da base."""

    try:
        removido = EVENT_STORE.delete_knowledge(entry_id)
    except Exception as e:
        logger.error("Falha ao remover pergunta: %s", type(e).__name__)
        return jsonify({"error": "unavailable"}), 503
    if not removido:
        return jsonify({"error": "not_found"}), 404
    return jsonify({"success": True})


@app.route("/api/bot/settings", methods=["GET", "PUT"])
@login_required
def bot_settings_route():
    """Tom de voz e boas-vindas do bot."""

    if request.method == "GET":
        try:
            settings = EVENT_STORE.bot_settings() or {}
        except Exception as e:
            logger.error("Falha ao ler ajustes do bot: %s", type(e).__name__)
            settings = {}
        return jsonify({
            "persona": settings.get("persona") or "",
            "welcome": settings.get("welcome") or "",
            "defaultWelcome": WELCOME_MESSAGE,
        })

    payload = request.get_json(silent=True) or {}
    try:
        EVENT_STORE.save_bot_settings(
            payload.get("persona"),
            payload.get("welcome"),
        )
    except Exception as e:
        logger.error("Falha ao salvar ajustes do bot: %s", type(e).__name__)
        return jsonify({"error": "não foi possível salvar"}), 503
    return jsonify({"success": True})


# --- ATENDIMENTO HUMANO (handon / handoff) ---

# A conversa e identificada pelo hash HMAC do remetente. O telefone fica no
# servidor: e usado para enfileirar o envio e nunca sai nas respostas da API.

MAX_OPERATOR_MESSAGE = 900


def _conversation_payload(sender_hash):
    """Monta a conversa com o estado de atendimento para o painel."""

    thread = EVENT_STORE.conversation_thread(sender_hash)
    thread["conversationId"] = sender_hash
    thread["participant"] = sender_hash[:12]
    return thread


@app.route("/api/conversations/by-feedback/<int:feedback_id>")
@login_required
def conversation_by_feedback(feedback_id):
    """Abre a conversa a partir de um chamado clicado no dashboard."""

    try:
        sender_hash = EVENT_STORE.sender_hash_for_feedback(feedback_id)
    except Exception as e:
        logger.error("Falha ao resolver conversa: %s", type(e).__name__)
        return jsonify({"error": "unavailable"}), 503
    if not sender_hash:
        return jsonify({"error": "not_found"}), 404
    return jsonify(_conversation_payload(sender_hash))


@app.route("/api/conversations/<conversation_id>")
@login_required
def conversation_detail(conversation_id):
    """Histórico da conversa nos dois sentidos."""

    try:
        return jsonify(_conversation_payload(conversation_id))
    except Exception as e:
        logger.error("Falha ao carregar conversa: %s", type(e).__name__)
        return jsonify({"error": "unavailable"}), 503


@app.route("/api/conversations/<conversation_id>/mode", methods=["PUT"])
@login_required
def conversation_mode_route(conversation_id):
    """Assume o atendimento (human) ou devolve ao ChatBob (bot)."""

    mode = (request.get_json(silent=True) or {}).get("mode")
    if mode not in ("bot", "human"):
        return jsonify({"error": "modo inválido"}), 400

    operator = os.getenv("ADMIN_USER") or "operador"
    try:
        EVENT_STORE.set_conversation_mode(conversation_id, mode, operator)
    except Exception as e:
        logger.error("Falha ao trocar modo da conversa: %s", type(e).__name__)
        return jsonify({"error": "unavailable"}), 503

    logger.info("Atendimento alterado | modo=%s", mode)
    if mode == "human":
        # Avisa o participante para ele não achar que falou com o vazio.
        try:
            EVENT_STORE.enqueue_operator_message(
                conversation_id,
                "👋 Aqui é a equipe da Tropicadelia assumindo a conversa. "
                "Pode falar direto comigo!",
            )
        except Exception as e:
            logger.error("Falha ao avisar troca de atendimento: %s", type(e).__name__)

    return jsonify({"success": True, "mode": mode})


@app.route("/api/conversations/<conversation_id>/message", methods=["POST"])
@login_required
def conversation_send(conversation_id):
    """Enfileira a mensagem escrita no painel; o worker entrega pela Meta."""

    content = ((request.get_json(silent=True) or {}).get("content") or "").strip()
    if not content:
        return jsonify({"error": "mensagem vazia"}), 400
    if len(content) > MAX_OPERATOR_MESSAGE:
        return jsonify({"error": "mensagem muito longa"}), 400

    try:
        mode = EVENT_STORE.conversation_mode(conversation_id)
        if mode != "human":
            return jsonify({
                "error": "assuma o atendimento antes de responder",
            }), 409
        enviado = EVENT_STORE.enqueue_operator_message(conversation_id, content)
    except Exception as e:
        logger.error("Falha ao enfileirar mensagem do operador: %s", type(e).__name__)
        return jsonify({"error": "unavailable"}), 503

    if not enviado:
        return jsonify({
            "error": "Esta conversa não tem mensagem recebida pelo WhatsApp, "
                     "então não há número para responder.",
        }), 404
    return jsonify({"success": True})


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

def _meta_channel_check() -> str:
    """Pergunta à Meta se token e número estão de pé, sem enviar mensagem.

    É o teste que separa problema de credencial de problema de destinatário,
    porque é uma leitura do próprio número e não depende de janela nem de
    lista de destinatários.
    """

    try:
        cliente = MetaWhatsAppClient(
            access_token=os.getenv("META_ACCESS_TOKEN", ""),
            phone_number_id=os.getenv("META_PHONE_NUMBER_ID", ""),
            graph_api_version=graph_api_version(),
        )
    except ValueError:
        return "configuração incompleta: falta token, ID do número ou versão"
    return cliente.check_credentials()


@app.route("/api/debug")
@login_required
def debug_env():
    """Endpoint para verificar variáveis de ambiente no Coolify"""
    return jsonify({
        "status": "online",
        "started_at": PROCESS_STARTED_AT,
        "graph_api_version": graph_api_version(),
        "meta_channel": _meta_channel_check(),
        "env_check": {
            "SUPABASE_URL": "OK" if os.getenv("SUPABASE_URL") else "MISSING",
            "SUPABASE_SERVICE_ROLE_KEY": "OK" if os.getenv("SUPABASE_SERVICE_ROLE_KEY") else "MISSING",
            "OPENAI_API_KEY": "OK" if os.getenv("OPENAI_API_KEY") else "MISSING",
            "OPENAI_MODEL": _openai_model(),
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
