"""Server-rendered Jinja2 page routes."""

from __future__ import annotations

import json
from pathlib import Path

from flask import Blueprint, current_app, render_template, request, send_from_directory, session

from app.services.sample_library import get_scheme_by_id, search_schemes

pages_bp = Blueprint("pages", __name__)


def _get_session_id() -> str:
    if "cid" not in session:
        import uuid

        session["cid"] = uuid.uuid4().hex
    return session["cid"]


@pages_bp.route("/")
def index():
    _get_session_id()
    return render_template("index.html", active_page="home")


@pages_bp.route("/workspace")
def workspace():
    sid = _get_session_id()
    mgr = current_app.extensions["session_manager"]
    state = mgr.get_or_create(sid)
    consent = bool(session.get("consent_given") or state.consent_given)
    docs = [
        {
            "filename": d.filename,
            "total_pages": d.total_pages,
            "extracted_pages": d.extracted_pages,
            "ocr_pages": d.ocr_pages,
            "table_pages": d.table_pages,
            "skipped_image_pages": d.skipped_image_pages,
            "warnings": d.warnings,
        }
        for d in state.documents
    ]
    return render_template(
        "workspace.html",
        active_page="workspace",
        consent_given=consent,
        initial_docs=docs,
        initial_summary=state.last_summary,
        gemini_configured=bool(current_app.config.get("GEMINI_API_KEY")),
        retrieval_mode=current_app.config.get("RETRIEVAL_MODE", "hybrid"),
    )


@pages_bp.route("/eligibility")
def eligibility():
    sid = _get_session_id()
    mgr = current_app.extensions["session_manager"]
    state = mgr.get_or_create(sid)
    schemes = search_schemes(Path(current_app.config["SAMPLES_DIR"]))
    preselected_scheme = request.args.get("scheme", "")
    docs = [{"filename": d.filename, "total_pages": d.total_pages} for d in state.documents]
    return render_template(
        "eligibility.html",
        active_page="eligibility",
        schemes=schemes,
        preselected_scheme=preselected_scheme,
        session_docs=docs,
    )


@pages_bp.route("/schemes")
def schemes():
    _get_session_id()
    q = request.args.get("q", "")
    cat = request.args.get("category", "all")
    samples_dir = Path(current_app.config["SAMPLES_DIR"])
    items = search_schemes(samples_dir, query=q, category=cat)
    all_items = search_schemes(samples_dir)
    categories = sorted({item.get("category", "Other") for item in all_items})
    return render_template(
        "schemes.html",
        active_page="schemes",
        schemes=items,
        categories=categories,
        current_query=q,
        current_category=cat,
    )


@pages_bp.route("/schemes/download/<scheme_id>")
def download_scheme(scheme_id: str):
    samples_dir = Path(current_app.config["SAMPLES_DIR"])
    scheme = get_scheme_by_id(samples_dir, scheme_id)
    if not scheme:
        return render_template("errors/404.html"), 404
    filename = scheme.get("filename", "")
    if not (samples_dir / filename).exists():
        return render_template("errors/404.html"), 404
    return send_from_directory(samples_dir, filename, as_attachment=True)


@pages_bp.route("/analytics")
def analytics():
    _get_session_id()
    return render_template("analytics.html", active_page="analytics")


@pages_bp.route("/evaluation")
def evaluation():
    _get_session_id()
    eval_path = Path(current_app.config["EVAL_RESULTS_PATH"])
    eval_data = None
    if eval_path.exists():
        try:
            eval_data = json.loads(eval_path.read_text(encoding="utf-8"))
        except Exception:
            eval_data = None
    return render_template("evaluation.html", active_page="evaluation", eval_data=eval_data)


@pages_bp.route("/about")
def about():
    _get_session_id()
    return render_template("about.html", active_page="about")


@pages_bp.route("/privacy")
def privacy():
    _get_session_id()
    return render_template("privacy.html", active_page="privacy")
