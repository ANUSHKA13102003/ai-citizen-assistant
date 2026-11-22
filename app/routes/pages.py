"""Server-rendered Jinja2 page routes for AI Citizen Assistant."""

from __future__ import annotations

import uuid
from pathlib import Path

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)

from app.services.doc_intel import STATES
from app.services.i18n import normalize_lang
from app.services.sample_library import (
    build_apply_steps,
    get_scheme_by_id,
    get_scheme_by_slug,
    search_schemes,
)
from app.services.verified_chat import load_explainers

pages_bp = Blueprint("pages", __name__)


def _get_session_id() -> str:
    if "cid" not in session:
        session["cid"] = uuid.uuid4().hex
    return session["cid"]


def _current_lang() -> str:
    return normalize_lang(session.get("lang", "en"))


@pages_bp.route("/")
def index():
    _get_session_id()
    samples_dir = Path(current_app.config["SAMPLES_DIR"])
    schemes_path = Path(current_app.config["SCHEMES_PATH"])
    all_schemes = search_schemes(samples_dir, schemes_path=schemes_path)
    categories = sorted({item.get("category", "") for item in all_schemes if item.get("category")})
    verified_dates = [s.get("last_verified", "") for s in all_schemes if s.get("last_verified")]
    last_verified = max(verified_dates) if verified_dates else "2026-11-19"
    return render_template(
        "index.html",
        active_page="home",
        categories=categories,
        scheme_count=len(all_schemes),
        last_verified=last_verified,
    )


@pages_bp.route("/find-schemes")
def find_schemes():
    sid = _get_session_id()
    mgr = current_app.extensions["session_manager"]
    state = mgr.get_or_create(sid)
    profile = state.get_profile()
    fields = profile.get("fields", {})
    merged_answers = dict(state.wizard_answers)
    for key in (
        "state",
        "age",
        "category",
        "gender",
        "annual_income_inr",
        "marks_percent",
        "education_level",
        "occupation",
    ):
        val = (fields.get(key) or {}).get("value")
        if key not in merged_answers and val not in (None, ""):
            merged_answers[key] = val

    is_example = request.args.get("example") == "1"
    if is_example:
        merged_answers = {
            "state": "Uttar Pradesh",
            "age": 19,
            "occupation": "student",
            "category": "General",
            "gender": "female",
            "annual_income_inr": 240000,
            "education_level": "undergraduate",
            "marks_percent": 78,
            "has_disability": False,
        }
    elif request.args.get("role"):
        merged_answers["occupation"] = request.args.get("role", "").strip().lower()
        if request.args.get("disability") == "1":
            merged_answers["has_disability"] = True

    return render_template(
        "find_schemes.html",
        active_page="find_schemes",
        initial_answers=merged_answers,
        checked_docs=state.checked_docs,
        docs_count=len(state.documents),
        auto_results=(request.args.get("results") == "1" or is_example),
        is_example=is_example,
        preselected_scheme=request.args.get("scheme", ""),
        all_states=STATES,
    )


@pages_bp.route("/documents")
def documents():
    sid = _get_session_id()
    mgr = current_app.extensions["session_manager"]
    state = mgr.get_or_create(sid)
    docs = [d.to_dict() for d in state.documents]
    insights = [i.to_dict() for i in state.insights]
    profile = state.get_profile()
    return render_template(
        "documents.html",
        active_page="documents",
        initial_docs=docs,
        initial_insights=insights,
        initial_profile=profile,
        initial_summary=state.last_summary,
        gemini_configured=bool(current_app.config.get("GEMINI_API_KEY")),
    )


@pages_bp.route("/workspace")
def workspace_redirect():
    ask_scheme = request.args.get("ask_scheme", "").strip()
    if ask_scheme:
        return redirect(url_for("pages.ask", scheme=ask_scheme))
    return redirect(url_for("pages.documents"))


@pages_bp.route("/eligibility")
def eligibility_redirect():
    scheme = request.args.get("scheme", "").strip()
    if scheme:
        return redirect(url_for("pages.scheme_detail", slug=scheme))
    return redirect(url_for("pages.find_schemes"))


@pages_bp.route("/ask")
def ask():
    sid = _get_session_id()
    mgr = current_app.extensions["session_manager"]
    state = mgr.get_or_create(sid)
    ask_scheme_slug = (request.args.get("scheme") or request.args.get("ask_scheme") or "").strip()
    ask_scheme = None
    if ask_scheme_slug:
        ask_scheme = get_scheme_by_slug(
            ask_scheme_slug,
            samples_dir=Path(current_app.config["SAMPLES_DIR"]),
            schemes_path=Path(current_app.config["SCHEMES_PATH"]),
        )
    return render_template(
        "ask.html",
        active_page="ask",
        ask_scheme=ask_scheme,
        initial_docs=[d.to_dict() for d in state.documents],
        chat_history=state.chat_history,
        gemini_configured=bool(current_app.config.get("GEMINI_API_KEY")),
    )


@pages_bp.route("/schemes")
def schemes():
    _get_session_id()
    q = request.args.get("q", "")
    cat = request.args.get("category", "all")
    lvl = request.args.get("level", "all")
    samples_dir = Path(current_app.config["SAMPLES_DIR"])
    schemes_path = Path(current_app.config["SCHEMES_PATH"])
    items = search_schemes(samples_dir, query=q, category=cat, level=lvl, schemes_path=schemes_path)
    all_items = search_schemes(samples_dir, schemes_path=schemes_path)
    categories = sorted({item.get("category", "") for item in all_items if item.get("category")})
    return render_template(
        "schemes.html",
        active_page="schemes",
        schemes=items,
        categories=categories,
        current_query=q,
        current_category=cat,
        current_level=lvl,
    )


@pages_bp.route("/schemes/<slug>")
def scheme_detail(slug: str):
    _get_session_id()
    samples_dir = Path(current_app.config["SAMPLES_DIR"])
    schemes_path = Path(current_app.config["SCHEMES_PATH"])
    scheme = get_scheme_by_slug(slug, samples_dir=samples_dir, schemes_path=schemes_path)
    if not scheme:
        return render_template("errors/404.html"), 404
    apply_steps = build_apply_steps(scheme, lang=_current_lang())
    explainer = load_explainers().get(scheme.get("id", ""), {})
    return render_template(
        "scheme_detail.html",
        active_page="schemes",
        scheme=scheme,
        apply_steps=apply_steps,
        explainer=explainer,
    )


@pages_bp.route("/schemes/download/<scheme_id>")
def download_scheme(scheme_id: str):
    samples_dir = Path(current_app.config["SAMPLES_DIR"])
    schemes_path = Path(current_app.config["SCHEMES_PATH"])
    scheme = get_scheme_by_id(samples_dir, scheme_id, schemes_path=schemes_path)
    if not scheme:
        return render_template("errors/404.html"), 404
    filename = scheme.get("filename", "")
    if filename and (samples_dir / filename).exists():
        return send_from_directory(samples_dir, filename, as_attachment=True)
    if scheme.get("official_url"):
        return redirect(scheme["official_url"])
    return render_template("errors/404.html"), 404


@pages_bp.route("/admin/insights")
def admin_insights():
    admin_key = current_app.config.get("ADMIN_KEY", "")
    provided = request.args.get("key", "") or request.headers.get("X-Admin-Key", "")
    if not admin_key or provided != admin_key:
        abort(404)
    return render_template("analytics.html", active_page="admin")


@pages_bp.route("/help")
def help_page():
    _get_session_id()
    return render_template("help.html", active_page="help")


@pages_bp.route("/privacy")
def privacy():
    _get_session_id()
    return render_template("privacy.html", active_page="privacy")


@pages_bp.route("/robots.txt")
def robots_txt():
    base = request.url_root.rstrip("/")
    body = f"User-agent: *\nAllow: /\nDisallow: /admin/\nSitemap: {base}/sitemap.xml\n"
    return Response(body, mimetype="text/plain")


@pages_bp.route("/sitemap.xml")
def sitemap_xml():
    base = request.url_root.rstrip("/")
    samples_dir = Path(current_app.config["SAMPLES_DIR"])
    schemes_path = Path(current_app.config["SCHEMES_PATH"])
    all_schemes = search_schemes(samples_dir, schemes_path=schemes_path)
    urls = [
        f"{base}/",
        f"{base}/find-schemes",
        f"{base}/documents",
        f"{base}/ask",
        f"{base}/schemes",
        f"{base}/help",
        f"{base}/privacy",
    ]
    for s in all_schemes:
        slug = s.get("slug") or s.get("id")
        if slug:
            urls.append(f"{base}/schemes/{slug}")
    xml_items = "\n".join(f"  <url><loc>{u}</loc></url>" for u in urls)
    xml = f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{xml_items}\n</urlset>\n'
    return Response(xml, mimetype="application/xml")
