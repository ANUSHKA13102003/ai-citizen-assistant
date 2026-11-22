"""Flask application factory with blueprints, security headers, and session management."""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from flask import Flask, jsonify, render_template, request, session
from flask_wtf.csrf import CSRFError

from app.config import CONFIG_MAP
from app.extensions import csrf, db, limiter
from app.routes.api import api_bp
from app.routes.pages import pages_bp
from app.services.i18n import load_locale, normalize_lang
from app.services.session_manager import SessionManager

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def _get_build_id() -> str:
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(Path(__file__).resolve().parent.parent),
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        ).strip()
        if sha:
            return sha
    except Exception:
        pass
    return os.getenv("RENDER_GIT_COMMIT", "local")[:7] or "local"


_BUILD_ID = _get_build_id()


def create_app(config_name: str | None = None) -> Flask:
    """Create and configure the AI Citizen Assistant Flask application."""
    env_name = (config_name or os.getenv("FLASK_ENV", "development")).lower()
    cfg_cls = CONFIG_MAP.get(env_name, CONFIG_MAP["development"])

    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_object(cfg_cls)

    db.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    app.extensions["session_manager"] = SessionManager(
        embedding_model=app.config["EMBEDDING_MODEL"],
        collection_prefix=app.config["CHROMA_COLLECTION_PREFIX"],
        ttl_minutes=app.config["SESSION_TTL_MINUTES"],
    )

    app.register_blueprint(pages_bp)
    app.register_blueprint(api_bp)

    with app.app_context():
        db.create_all()

    @app.context_processor
    def inject_i18n():
        q_lang = request.args.get("lang")
        if q_lang:
            session["lang"] = normalize_lang(q_lang)
        lang = normalize_lang(session.get("lang", "en"))
        return {
            "lang": lang,
            "t": load_locale(lang),
            "build_id": _BUILD_ID,
            "build_stamp": f"v1.0.0 · {_BUILD_ID}",
        }

    @app.after_request
    def apply_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(self), camera=(self)"
        )
        if response.content_type and "text/html" in response.content_type:
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
        return response

    @app.errorhandler(CSRFError)
    def handle_csrf_error(err):
        if request.path.startswith("/api/"):
            msg = f"Security token invalid or expired: {err.description}"
            return jsonify({"ok": False, "code": "csrf_error", "message": msg, "error": msg}), 400
        return render_template("errors/500.html"), 400

    @app.errorhandler(404)
    def handle_404(_err):
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "code": "not_found", "message": "Endpoint not found.", "error": "Endpoint not found."}), 404
        return render_template("errors/404.html"), 404

    @app.errorhandler(429)
    def handle_429(_err):
        msg = "Busy right now — please wait a moment and try again."
        return jsonify({"ok": False, "code": "rate_limited", "message": msg, "error": msg}), 429

    @app.errorhandler(500)
    def handle_500(_err):
        if request.path.startswith("/api/"):
            msg = "Something went wrong. Please try again."
            return jsonify({"ok": False, "code": "server_error", "message": msg, "error": msg}), 500
        return render_template("errors/500.html"), 500

    return app
