"""Diagnostico do numero da Cloud API antes de trocar o numero em producao.

Le as credenciais do .env e pergunta a Meta, sem enviar mensagem para ninguem:

1. Que tipo de token e esse (usuario do sistema, usuario comum ou App Token)
2. Se o numero existe, qual o display_phone_number e se esta no Cloud API
3. Se o numero pertence ao WABA configurado
4. Se algum app esta assinado no WABA para receber os webhooks

Uso:
    python scripts/check_meta_number.py                 # usa o .env
    python scripts/check_meta_number.py 1312359605299142  # testa outro numero
"""

from __future__ import annotations

import os
import sys
from typing import Any, Optional

import requests
from dotenv import load_dotenv

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

load_dotenv()

TIMEOUT = 15
VERSION = (os.getenv("META_GRAPH_API_VERSION") or "v26.0").strip()
TOKEN = (os.getenv("META_ACCESS_TOKEN") or "").strip()
APP_ID = (os.getenv("META_APP_ID") or "").strip()
APP_SECRET = (os.getenv("META_APP_SECRET") or "").strip()
WABA_ID = (os.getenv("META_WABA_ID") or "").strip()
PHONE_ID = (sys.argv[1] if len(sys.argv) > 1 else os.getenv("META_PHONE_NUMBER_ID") or "").strip()

BASE = f"https://graph.facebook.com/{VERSION}"


def mascara(valor: str) -> str:
    """Mostra so as pontas de um segredo, para o log nao virar vazamento."""
    if not valor:
        return "(vazio)"
    if len(valor) <= 12:
        return valor[:2] + "..." + valor[-2:]
    return valor[:6] + "..." + valor[-4:]


def consulta(caminho: str, params: Optional[dict] = None) -> tuple[bool, Any]:
    """Faz um GET na Graph API e devolve (deu_certo, corpo)."""
    p = {"access_token": TOKEN}
    p.update(params or {})
    try:
        r = requests.get(f"{BASE}/{caminho}", params=p, timeout=TIMEOUT)
    except requests.RequestException as e:
        return False, {"erro_local": str(e)}
    try:
        corpo = r.json()
    except ValueError:
        corpo = {"corpo_nao_json": r.text[:300]}
    return r.ok, corpo


def erro(corpo: Any) -> str:
    """Resume o erro da Meta em uma linha legivel."""
    if isinstance(corpo, dict):
        e = corpo.get("error") or {}
        if e:
            return f"code {e.get('code')} | {e.get('message')}"
        if "erro_local" in corpo:
            return corpo["erro_local"]
    return str(corpo)[:200]


def titulo(texto: str) -> None:
    print()
    print(texto)
    print("-" * len(texto))


def main() -> int:
    print("=" * 58)
    print("DIAGNOSTICO DO NUMERO NA CLOUD API")
    print("=" * 58)
    print(f"Graph API        : {VERSION}")
    print(f"Phone Number ID  : {PHONE_ID or '(vazio)'}")
    print(f"WABA ID          : {WABA_ID or '(vazio)'}")
    print(f"Access Token     : {mascara(TOKEN)}")

    if not TOKEN:
        print()
        print("META_ACCESS_TOKEN vazio no .env. Sem ele nao da para perguntar nada a Meta.")
        return 1
    if not PHONE_ID:
        print()
        print("META_PHONE_NUMBER_ID vazio. Passe o ID como argumento ou preencha o .env.")
        return 1

    problemas: list[str] = []

    titulo("1. Que tipo de token e esse")
    if APP_ID and APP_SECRET:
        ok, corpo = consulta(
            "debug_token",
            {"input_token": TOKEN, "access_token": f"{APP_ID}|{APP_SECRET}"},
        )
        dados = (corpo or {}).get("data") or {}
        if ok and dados:
            tipo = dados.get("type", "?")
            expira = dados.get("expires_at")
            escopos = dados.get("scopes") or []
            print(f"Tipo            : {tipo}")
            print(f"Valido          : {dados.get('is_valid')}")
            print(f"Expira em       : {'nunca' if expira in (0, None) else expira}")
            print(f"Permissoes      : {', '.join(escopos) if escopos else '(nenhuma)'}")
            if tipo == "APP":
                problemas.append(
                    "O token e um App Token (app_id|app_secret). A Cloud API recusa envio com ele."
                )
            if expira not in (0, None):
                problemas.append(
                    "O token tem data de expiracao. Para producao use token permanente de usuario do sistema."
                )
            if "whatsapp_business_messaging" not in escopos:
                problemas.append(
                    "Falta a permissao whatsapp_business_messaging. Sem ela o envio falha com erro generico."
                )
        else:
            print(f"Nao deu para inspecionar: {erro(corpo)}")
    else:
        print("META_APP_ID ou META_APP_SECRET vazios, pulando a inspecao do token.")

    titulo("2. O numero responde")
    ok, corpo = consulta(
        PHONE_ID,
        {
            "fields": "id,display_phone_number,verified_name,quality_rating,"
            "platform_type,code_verification_status,status,name_status"
        },
    )
    if ok:
        for campo in (
            "display_phone_number",
            "verified_name",
            "quality_rating",
            "platform_type",
            "code_verification_status",
            "status",
            "name_status",
        ):
            print(f"{campo:26}: {corpo.get(campo, '(nao veio)')}")
        if corpo.get("platform_type") not in (None, "CLOUD_API"):
            problemas.append(
                f"platform_type = {corpo.get('platform_type')}. O numero nao esta na Cloud API."
            )
        if corpo.get("code_verification_status") not in (None, "VERIFIED", "EXPIRED"):
            problemas.append(
                f"code_verification_status = {corpo.get('code_verification_status')}. "
                "O numero nao completou a verificacao."
            )
    else:
        print(f"FALHOU: {erro(corpo)}")
        problemas.append("O token nao consegue ler o proprio numero. Ou o ID esta errado, ou o token nao tem acesso a ele.")

    if WABA_ID:
        titulo("3. O numero esta no WABA configurado")
        ok, corpo = consulta(f"{WABA_ID}/phone_numbers", {"fields": "id,display_phone_number,verified_name"})
        if ok:
            numeros = corpo.get("data") or []
            achou = False
            for n in numeros:
                marca = "  <= configurado" if n.get("id") == PHONE_ID else ""
                achou = achou or n.get("id") == PHONE_ID
                print(f"{n.get('id')}  {n.get('display_phone_number')}  {n.get('verified_name')}{marca}")
            if not achou:
                problemas.append(
                    "O numero configurado nao aparece nesse WABA. META_WABA_ID e META_PHONE_NUMBER_ID nao combinam."
                )
        else:
            print(f"FALHOU: {erro(corpo)}")

        titulo("4. Algum app esta assinado para receber os webhooks")
        ok, corpo = consulta(f"{WABA_ID}/subscribed_apps")
        if ok:
            apps = corpo.get("data") or []
            if not apps:
                problemas.append("Nenhum app assinado nesse WABA. O webhook nao vai receber mensagem nenhuma.")
                print("(nenhum)")
            for a in apps:
                app = a.get("whatsapp_business_api_data") or {}
                print(f"{app.get('id')}  {app.get('name')}")
        else:
            print(f"FALHOU: {erro(corpo)}")
    else:
        print()
        print("META_WABA_ID vazio, pulando os testes 3 e 4.")

    titulo("Resultado")
    if problemas:
        for p in problemas:
            print(f"[ ! ] {p}")
        return 2
    print("[ OK ] Token, numero e WABA respondem e combinam entre si.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
