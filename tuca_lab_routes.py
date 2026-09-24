"""Rotas autenticadas do laboratório. Estado assinado, sem tabelas novas."""

import copy
import hashlib
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from flask import request, session, jsonify, render_template
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
import tuca_lab
import tuca_jev_config as jev


def register_lab(app, login_required):
    def serializer():
        return URLSafeTimedSerializer(app.secret_key, salt="tuca-lab-v1")

    def revision():
        root = Path(__file__).parent
        return hashlib.sha256(
            b"".join(
                (root / f).read_bytes()
                for f in [
                    "server.py",
                    "worker.py",
                    "tuca_experimental.py",
                    "tuca_lab.py",
                    "tuca_jev.py",
                    "tuca_jev_config.py",
                    "tuca_lab_routes.py",
                    "tuca_enxuto.py",
                ]
            )
        ).hexdigest()[:12]

    def body():
        if not request.is_json or (request.content_length or 0) > 350000:
            raise ValueError("Requisição inválida ou muito grande.")
        origin = request.headers.get("Origin")
        # TLS can terminate at the reverse proxy while Flask receives HTTP.
        allowed_origins = {request.host_url.rstrip("/"), f"https://{request.host}"}
        if origin and origin.rstrip("/") not in allowed_origins:
            raise ValueError("Origem não permitida.")
        value = request.get_json(silent=True)
        if not isinstance(value, dict):
            raise ValueError("Envie um objeto JSON válido.")
        return value

    @app.get("/tuca/laboratorio")
    @login_required
    def tuca_lab_page():
        return render_template("tuca_lab.html")

    @app.get("/api/tuca-lab/jev-config")
    @login_required
    def tuca_jev_config_get():
        try:
            response = jsonify(jev.public_config())
            response.headers["Cache-Control"] = "no-store"
            return response
        except jev.JevError as exc:
            return jsonify(error=str(exc)), 503

    @app.post("/api/tuca-lab/jev-config")
    @login_required
    def tuca_jev_config_save():
        try:
            data = body()
            result = jev.save_config(data)
            response = jsonify(result)
            response.headers["Cache-Control"] = "no-store"
            return response
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        except (jev.JevError, OSError):
            return (
                jsonify(
                    error="Não foi possível salvar. Verifique a permissão da pasta privada do servidor."
                ),
                503,
            )

    @app.post("/api/tuca-lab/jev-test")
    @login_required
    def tuca_jev_test():
        try:
            body()
            questions = {
                "connection": {
                    "type": "noul",
                    "instructions": "Does message greet the assistant?",
                }
            }
            result = jev.ask({"message": "Olá, Tuca!"}, questions, jev.settings())
            jev.checked_answers(result, questions)
            return jsonify(
                ok=True,
                model=result.get("model"),
                message="Conexão confirmada com o JEV.",
            )
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        except jev.JevError as exc:
            return jsonify(error=str(exc)), 503

    @app.post("/api/tuca-lab/start")
    @login_required
    def tuca_lab_start():
        import server

        try:
            data = body()
            mode = data.get("mode", "published")
            if mode not in ("published", "draft"):
                raise ValueError("Configuração inválida.")
            if mode == "published":
                config = server.EVENT_STORE.live_config()
            else:
                config = server.EVENT_STORE.draft_payload()
            if not isinstance(config, dict) or "knowledge" not in config:
                raise RuntimeError("Configuração indisponível")
            snapshot = {
                "config": copy.deepcopy(config),
                "sectors": server.EVENT_STORE.list_sectors(),
                "window": list(server.EVENT_STORE.event_window()),
                "clock": datetime.now(timezone.utc).isoformat(),
                "mode": mode,
                "revision": revision(),
                "jev_settings": jev.settings(),
            }
            owner = session.setdefault("tuca_lab_owner", secrets.token_urlsafe(24))
            shared = {
                "snapshot": snapshot,
                "owner": owner,
                "batch": secrets.token_hex(8),
                "started_at": snapshot["clock"],
            }
            tokens = {
                e: serializer().dumps({**shared, "engine": e, "state": {"turns": 0}})
                for e in ("current", "experimental", "jev", "enxuto")
            }
            return jsonify(
                tokens=tokens,
                revision=snapshot["revision"],
                snapshot=tuca_lab.fingerprint(snapshot),
                mode=mode,
                created_at=snapshot["clock"],
                version=tuca_lab.VERSION,
                jev=jev.public_config(),
                sectors=[
                    {"code": s["code"], "name": s["name"]} for s in snapshot["sectors"]
                ],
            )
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        except Exception:
            app.logger.exception("Falha ao iniciar laboratório")
            return (
                jsonify(
                    error="Não foi possível carregar a configuração. Tente novamente."
                ),
                503,
            )

    @app.post("/api/tuca-lab/turn")
    @login_required
    def tuca_lab_turn():
        try:
            data = body()
            token = data.get("token")
            content = data.get("content")
            kind = data.get("kind", "text")
            if not isinstance(token, str) or len(token) > 300000:
                raise ValueError("Sessão de teste inválida.")
            if (
                not isinstance(content, str)
                or not content.strip()
                or len(content) > 2000
            ):
                raise ValueError("Use uma mensagem de 1 a 2.000 caracteres.")
            if kind not in ("text", "location"):
                raise ValueError("Tipo de mensagem não suportado neste laboratório.")
            payload = serializer().loads(token, max_age=1800)
            if (
                datetime.now(timezone.utc)
                - datetime.fromisoformat(payload["started_at"])
            ).total_seconds() > 1800:
                return (
                    jsonify(
                        error="A comparação expirou após 30 minutos. Inicie outra."
                    ),
                    409,
                )
            if payload.get("owner") != session.get("tuca_lab_owner"):
                raise ValueError(
                    "Esta sessão pertence a outro acesso. Inicie uma nova comparação."
                )
            if payload["snapshot"]["revision"] != revision():
                return jsonify(error="O código mudou. Inicie uma nova comparação."), 409
            if payload["state"].get("turns", 0) >= tuca_lab.MAX_TURNS:
                return (
                    jsonify(
                        error="Limite de 60 rodadas atingido. Inicie uma nova comparação."
                    ),
                    409,
                )
            updated = copy.deepcopy(payload)
            result = tuca_lab.run_turn(
                updated["engine"],
                updated["state"],
                updated["snapshot"],
                content.strip(),
                kind,
            )
            return jsonify(result=result, token=serializer().dumps(updated))
        except SignatureExpired:
            return (
                jsonify(error="A comparação expirou após 30 minutos. Inicie outra."),
                409,
            )
        except BadSignature:
            return (
                jsonify(error="Estado de teste inválido. Inicie uma nova comparação."),
                400,
            )
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        except Exception:
            app.logger.exception("Falha em uma variante do laboratório")
            return (
                jsonify(
                    error="Esta variante não respondeu. Você pode tentar novamente sem perder as outras respostas."
                ),
                503,
            )
