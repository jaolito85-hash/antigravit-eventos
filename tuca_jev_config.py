"""Credenciais privadas e cliente TypeSafe exclusivo do laboratório TUCA."""

import json
import math
import os
import re
import tempfile
from pathlib import Path
import requests

API = "https://api.typesafe.ai/v1/systemone"
DEFAULTS = {
    "model": "jev-1.13.0",
    "intent_threshold": 0.75,
    "location_threshold": 0.90,
    "source_threshold": 0.85,
    "timeout": 12,
}


class JevError(RuntimeError):
    pass


def config_path():
    return Path(
        os.environ.get("TUCA_JEV_CONFIG_FILE")
        or Path(__file__).parent / "instance" / "tuca-jev.json"
    )


def read_private():
    try:
        data = json.loads(config_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except (ValueError, OSError):
        raise JevError("Não foi possível ler a configuração privada do JEV.") from None


def settings():
    private = read_private()
    return validate({**DEFAULTS, **{k: private[k] for k in DEFAULTS if k in private}})


def api_key():
    # A chave salva no painel substitui a variável até ser removida pelo administrador.
    return (
        read_private().get("api_key") or os.environ.get("TYPESAFE_API_KEY", "").strip()
    )


def public_config():
    return {
        **settings(),
        "configured": bool(api_key()),
        "key_source": (
            "painel"
            if read_private().get("api_key")
            else ("ambiente" if api_key() else "ausente")
        ),
    }


def validate(data):
    result = {}
    model = data.get("model", DEFAULTS["model"])
    if not isinstance(model, str) or not re.fullmatch(
        r"jev-(?:latest|preview|\d+\.\d+(?:\.\d+)?)", model
    ):
        raise ValueError("Informe um modelo JEV válido, como jev-1.13.0.")
    result["model"] = model
    for field in ("intent_threshold", "location_threshold", "source_threshold"):
        value = data.get(field, DEFAULTS[field])
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not 0.5 <= value <= 0.99
        ):
            raise ValueError("Os limites devem ficar entre 0,50 e 0,99.")
        result[field] = value
    timeout = data.get("timeout", DEFAULTS["timeout"])
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, int)
        or not 3 <= timeout <= 20
    ):
        raise ValueError("O tempo limite deve ficar entre 3 e 20 segundos.")
    result["timeout"] = timeout
    return result


def save_config(data):
    updated = validate(data)
    private = read_private()
    key = data.get("api_key", "")
    if not isinstance(key, str) or len(key) > 4096 or any(c.isspace() for c in key):
        raise ValueError("A chave deve ser um texto sem espaços.")
    if key:
        updated["api_key"] = key
    elif private.get("api_key") and not data.get("remove_key"):
        updated["api_key"] = private["api_key"]
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".jev-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(updated, stream)
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return public_config()


def ask(state, questions, config):
    key = api_key()
    if not key:
        raise JevError("JEV sem chave. Configure a chave na seção Configurar JEV.")
    payload = {"model": config["model"], "state": state, "questions": questions}
    if len(json.dumps(payload, ensure_ascii=False)) > 70000:
        raise JevError("Contexto grande demais para este teste JEV. Reduza as fichas.")
    try:
        # Endpoint fixo, sem redirecionamento de credenciais e sem repetição silenciosa.
        with requests.post(
            API,
            json=payload,
            headers={"Authorization": "Bearer " + key},
            timeout=(3, config["timeout"]),
            allow_redirects=False,
        ) as response:
            if response.status_code != 200:
                reasons = {
                    401: "Chave JEV inválida.",
                    403: "Chave JEV sem acesso.",
                    429: "Limite da API JEV atingido.",
                    422: "Modelo ou perguntas rejeitados pelo JEV.",
                }
                raise JevError(
                    reasons.get(response.status_code, "API JEV indisponível.")
                )
            value = response.json()
        if not isinstance(value, dict) or not isinstance(value.get("answers"), dict):
            raise JevError("Resposta JEV inválida.")
        return value
    except (requests.RequestException, ValueError):
        raise JevError("JEV sem resposta válida no tempo disponível.") from None


def probability(value):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0 <= value <= 1
    ):
        raise JevError("Probabilidade inválida recebida do JEV.")
    return value


def checked_answers(response, questions):
    clean = {}
    for name, question in questions.items():
        answer = response["answers"].get(name)
        if not isinstance(answer, dict) or answer.get("type") != question["type"]:
            raise JevError("Resposta JEV incompleta ou com tipo incorreto.")
        if question["type"] == "noul":
            clean[name] = {"type": "noul", "noul": probability(answer.get("noul"))}
        else:
            choice = answer.get("choice")
            probs = answer.get("probabilities")
            if (
                not isinstance(choice, str)
                or choice not in question["criteria"]
                or not isinstance(probs, dict)
                or set(probs) != set(question["criteria"])
            ):
                raise JevError("O JEV devolveu uma opção fora da lista.")
            probs = {k: probability(v) for k, v in probs.items()}
            if (
                abs(sum(probs.values()) - 1) > 0.02
                or probs[choice] < max(probs.values()) - 0.001
            ):
                raise JevError("Distribuição JEV inválida.")
            clean[name] = {
                "type": "choice",
                "choice": choice,
                "confidence": probability(answer.get("confidence")),
                "probabilities": probs,
            }
    return clean
