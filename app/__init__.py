"""Flask application factory with blueprints, security headers, and session management."""

from __future__ import annotations

import logging
import os

from flask import Flask, jsonify, render_template, request
from flask_wtf.csrf import CSRFError

from app.config import CONFIG_MAP
from app.extensions import csrf, db, limiter
from app.routes.api import api_bp
from app.routes.pages import pages_bp
from app.services.session_manager import SessionManager

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


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

    @app.after_request
    def apply_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
        )
        return response

    @app.errorhandler(CSRFError)
    def handle_csrf_error(err):
        if request.path.startswith("/api/"):
            return jsonify({"error": f"Security token invalid or expired: {err.description}"}), 400
        return render_template("errors/500.html"), 400

    @app.errorhandler(404)
    def handle_404(_err):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Endpoint not found."}), 404
        return render_template("errors/404.html"), 404

    @app.errorhandler(429)
    def handle_429(_err):
        return jsonify({"error": "Rate limit exceeded. Please wait a moment and retry."}), 429

    @app.errorhandler(500)
    def handle_500(_err):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Internal server error."}), 500
        return render_template("errors/500.html"), 500

    return app
