"""JSON, file upload, export, insights, scheme finder, and SSE streaming API routes."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import threading
import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from flask import (
    Blueprint,
    Response,
    current_app,
    jsonify,
    request,
    send_file,
    session,
    stream_with_context,
)
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from app.extensions import db, limiter
from app.models import FeedbackLog, QueryLog, SessionLog
from app.services.eligibility_engine import evaluate_eligibility, match_all_schemes
from app.services.gemini_client import GeminiClient, GeminiUnavailableError, get_key_health
from app.services.i18n import normalize_lang
from app.services.language_service import detect_language, sanitize_input
from app.services.pdf_extractor import (
    PDFValidationError,
    _configure_tesseract,
    extract_document_bytes,
    extract_pdf_document,
)
from app.services.pii_redactor import redact_pii
from app.services.rag_service import analyze_documents, answer_question, stream_question
from app.services.sample_library import get_scheme_by_id, load_scheme_manifest
from app.services.vector_store import get_embedder, get_embeddings_backend
from app.services.verified_chat import (
    answer_from_verified_data,
    get_cached_answer,
    put_cached_answer,
)

logger = logging.getLogger(__name__)
api_bp = Blueprint("api", __name__)

_DAILY_CAP_LOCK = threading.Lock()
_DAILY_CAP_STATE = {"date": "", "count": 0}


def get_budget_status() -> dict:
    cap = int(current_app.config.get("DAILY_GEMINI_CAP", 500))
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    with _DAILY_CAP_LOCK:
        if _DAILY_CAP_STATE["date"] != today:
            _DAILY_CAP_STATE["date"] = today
            _DAILY_CAP_STATE["count"] = 0
        used = _DAILY_CAP_STATE["count"]
    pct = round((used / cap) * 100.0, 1) if cap > 0 else 0.0
    at_cap = cap > 0 and used >= cap
    return {
        "used_today": used,
        "daily_cap": cap,
        "pct": pct,
        "at_cap": at_cap,
        "high_usage": cap > 0 and used >= int(cap * 0.8),
    }


def _consume_daily_gemini_quota() -> bool:
    """Global daily Gemini call cap to protect free-tier quota on public deployments."""
    cap = int(current_app.config.get("DAILY_GEMINI_CAP", 500))
    if cap <= 0:
        return True
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    with _DAILY_CAP_LOCK:
        if _DAILY_CAP_STATE["date"] != today:
            _DAILY_CAP_STATE["date"] = today
            _DAILY_CAP_STATE["count"] = 0
        if _DAILY_CAP_STATE["count"] >= cap:
            return False
        _DAILY_CAP_STATE["count"] += 1
        return True


def _session_id() -> str:
    if "cid" not in session:
        session["cid"] = uuid.uuid4().hex
    return session["cid"]


def _build_gemini() -> GeminiClient:
    return GeminiClient(
        api_key=current_app.config.get("GEMINI_API_KEY", ""),
        model=current_app.config.get("GEMINI_MODEL", "gemini-3.8-flash"),
    )


def _upsert_session_log(sid: str, state) -> None:
    ttl = int(current_app.config.get("SESSION_TTL_MINUTES", 60))
    now = datetime.now(UTC)
    row = db.session.get(SessionLog, sid)
    meta_files = [{"filename": d.filename, "pages": d.total_pages} for d in state.documents]
    if row is None:
        row = SessionLog(
            id=sid,
            created_at=now,
            last_active_at=now,
            expires_at=now + timedelta(minutes=ttl),
            doc_count=len(state.documents),
            total_pages=sum(d.total_pages for d in state.documents),
            total_chunks=len(state.chunks),
            filenames_json=json.dumps(meta_files),
            is_cleared=False,
        )
        db.session.add(row)
    else:
        row.last_active_at = now
        row.expires_at = now + timedelta(minutes=ttl)
        row.doc_count = len(state.documents)
        row.total_pages = sum(d.total_pages for d in state.documents)
        row.total_chunks = len(state.chunks)
        row.filenames_json = json.dumps(meta_files)
        row.is_cleared = False
    db.session.commit()


def _log_query(
    sid: str,
    mode: str,
    category: str,
    language: str,
    retrieval_mode: str,
    ret_ms: float,
    llm_ms: float,
    total_ms: float,
    chunks_retrieved: int,
    sources: list[dict],
    is_not_found: bool,
) -> int:
    if db.session.get(SessionLog, sid) is None:
        mgr = current_app.extensions["session_manager"]
        _upsert_session_log(sid, mgr.get_or_create(sid))
    qlog = QueryLog(
        session_id=sid,
        mode=mode,
        category=category,
        language=language,
        retrieval_mode=retrieval_mode,
        retrieval_latency_ms=ret_ms,
        llm_latency_ms=llm_ms,
        total_latency_ms=total_ms,
        chunks_retrieved=chunks_retrieved,
        cited_files_json=json.dumps(sources),
        is_not_found=is_not_found,
    )
    db.session.add(qlog)
    db.session.commit()
    return qlog.id


@api_bp.route("/healthz", methods=["GET"])
def healthz():
    db_ok = True
    try:
        db.session.execute(db.text("SELECT 1"))
    except Exception:
        db_ok = False

    backend = get_embeddings_backend()
    embedder_loaded = True
    if backend == "local":
        try:
            get_embedder(current_app.config["EMBEDDING_MODEL"])
        except Exception:
            embedder_loaded = False

    gemini = _build_gemini()
    return jsonify(
        {
            "status": "ok" if db_ok else "degraded",
            "database": "ok" if db_ok else "error",
            "embeddings_backend": backend,
            "embedder_ready": embedder_loaded,
            "gemini_configured": gemini.is_configured,
            "gemini_model": gemini.model,
            "tesseract_available": _configure_tesseract(
                current_app.config.get("TESSERACT_CMD", "")
            ),
            "retrieval_mode": current_app.config.get("RETRIEVAL_MODE", "hybrid"),
        }
    ), (200 if db_ok else 503)


@api_bp.route("/admin/status", methods=["GET"])
def admin_status():
    admin_key = current_app.config.get("ADMIN_KEY", "")
    provided = request.args.get("key", "") or request.headers.get("X-Admin-Key", "")
    if not admin_key or provided != admin_key:
        return jsonify({"ok": False, "code": "not_found", "message": "Page not found."}), 404
    gemini = _build_gemini()
    budget = get_budget_status()
    key_health = get_key_health(current_app.config.get("GEMINI_API_KEY", ""))
    mode = "verified_data" if (key_health != "ok" or budget["at_cap"]) else "ai"
    return jsonify(
        {
            "ok": True,
            "key_health": key_health,
            "active_model": gemini.model,
            "usage_today": budget["used_today"],
            "daily_cap": budget["daily_cap"],
            "usage_pct": budget["pct"],
            "mode": mode,
        }
    )


@api_bp.route("/api/consent", methods=["POST"])
def record_consent():
    sid = _session_id()
    payload = request.get_json(silent=True) or {}
    accepted = bool(payload.get("accepted", True))
    session["consent_given"] = accepted
    mgr = current_app.extensions["session_manager"]
    state = mgr.get_or_create(sid)
    state.consent_given = accepted
    return jsonify({"consent_given": accepted, "session_id": sid})


@api_bp.route("/api/upload", methods=["POST"])
@limiter.limit("10 per hour")
def upload_pdfs():
    sid = _session_id()
    mgr = current_app.extensions["session_manager"]
    state = mgr.get_or_create(sid)
    session["consent_given"] = True
    state.consent_given = True

    files = request.files.getlist("files")
    if not files or all(not f.filename for f in files):
        return jsonify({"error": "No PDF or photo files were selected."}), 400

    max_files = int(current_app.config["MAX_FILES_PER_SESSION"])
    if len(state.documents) + len(files) > max_files:
        return jsonify({"error": f"You can upload at most {max_files} files per session."}), 400

    new_docs: list[tuple] = []
    duplicates: list[str] = []
    seen_batch_hashes: set[str] = set()
    errors: list[str] = []

    for f in files:
        if not f or not f.filename:
            continue
        raw_bytes = f.read()
        content_hash = hashlib.sha256(raw_bytes).hexdigest()
        if content_hash in state.content_hashes or content_hash in seen_batch_hashes:
            duplicates.append(f.filename)
            continue
        seen_batch_hashes.add(content_hash)

        try:
            doc = extract_document_bytes(
                raw_bytes,
                f.filename,
                enable_ocr_fallback=current_app.config["ENABLE_OCR_FALLBACK"],
                tesseract_cmd=current_app.config.get("TESSERACT_CMD", ""),
                max_file_size_bytes=current_app.config["MAX_FILE_SIZE_BYTES"],
                max_pages=current_app.config["MAX_PAGES_PER_PDF"],
            )
            new_docs.append((doc, content_hash))
        except PDFValidationError as exc:
            errors.append(str(exc))

    if not new_docs and not duplicates and errors:
        return jsonify({"error": " ".join(errors)}), 400

    state, rebuilt, extra_dups = mgr.add_or_update_citizen_docs(
        sid,
        new_docs,
        chunk_size=current_app.config["CHUNK_SIZE"],
        chunk_overlap=current_app.config["CHUNK_OVERLAP"],
        replace=False,
    )
    all_duplicates = duplicates + [d for d in extra_dups if d not in duplicates]
    _upsert_session_log(sid, state)
    redacted = redact_pii("\n".join(state.raw_texts_by_file.values())).redacted_counts

    return jsonify(
        {
            "rebuilt": rebuilt,
            "chat_cleared": rebuilt,
            "total_chunks": len(state.chunks),
            "duplicates": all_duplicates,
            "warnings": errors + [w for d in state.documents for w in d.warnings],
            "documents": [d.to_dict() for d in state.documents],
            "scheme_documents": [s.to_dict() for s in state.scheme_documents.values()],
            "insights": [i.to_dict() for i in state.insights],
            "profile": state.get_profile(),
            "redacted_counts": redacted,
        }
    )


@api_bp.route("/api/load-demo-docs", methods=["POST"])
@limiter.limit("20 per minute")
def load_demo_docs():
    """Load fictional sample citizen documents (never mixing scheme PDFs into citizen store)."""
    sid = _session_id()
    mgr = current_app.extensions["session_manager"]
    state = mgr.get_or_create(sid)
    session["consent_given"] = True
    state.consent_given = True

    samples_dir = Path(current_app.config["SAMPLES_DIR"])
    target_files = [
        samples_dir / "sample_citizen_marksheet.pdf",
        samples_dir / "sample_citizen_resume.pdf",
        samples_dir / "sample_income_certificate.pdf",
    ]

    new_docs = []
    for path in target_files:
        if not path.exists():
            continue
        raw = path.read_bytes()
        content_hash = hashlib.sha256(raw).hexdigest()
        doc = extract_pdf_document(
            raw,
            path.name,
            enable_table_extraction=current_app.config["ENABLE_TABLE_EXTRACTION"],
            enable_ocr_fallback=current_app.config["ENABLE_OCR_FALLBACK"],
        )
        new_docs.append((doc, content_hash))

    if not new_docs:
        return jsonify({"error": "Sample documents not found on disk."}), 404

    state, rebuilt, duplicates = mgr.add_or_update_citizen_docs(
        sid,
        new_docs,
        chunk_size=current_app.config["CHUNK_SIZE"],
        chunk_overlap=current_app.config["CHUNK_OVERLAP"],
        replace=True,
    )
    _upsert_session_log(sid, state)
    redacted = redact_pii("\n".join(state.raw_texts_by_file.values())).redacted_counts

    return jsonify(
        {
            "rebuilt": rebuilt,
            "duplicates": duplicates,
            "total_chunks": len(state.chunks),
            "documents": [d.to_dict() for d in state.documents],
            "insights": [i.to_dict() for i in state.insights],
            "profile": state.get_profile(),
            "redacted_counts": redacted,
        }
    )


@api_bp.route("/api/profile/override", methods=["POST"])
def update_profile_override():
    """Save user edits from the Detected Details panel before eligibility or Scheme Finder runs."""
    sid = _session_id()
    mgr = current_app.extensions["session_manager"]
    state = mgr.get_or_create(sid)
    payload = request.get_json(silent=True) or {}
    overrides = payload.get("overrides") or {}
    if isinstance(overrides, dict):
        for k, v in overrides.items():
            if v in (None, ""):
                state.profile_overrides.pop(k, None)
            else:
                state.profile_overrides[k] = v
    return jsonify({"profile": state.get_profile()})


@api_bp.route("/api/document-page", methods=["GET"])
def get_document_page():
    """Return extracted text of a specific (filename, page) for the in-app PDF page viewer."""
    sid = _session_id()
    mgr = current_app.extensions["session_manager"]
    state = mgr.get_or_create(sid)
    filename = request.args.get("filename", "").strip()
    page_num = int(request.args.get("page", "1") or "1")

    pages = state.pages_by_file.get(filename)
    if not pages:
        return jsonify({"error": f"Document '{filename}' is not loaded in this session."}), 404

    target = next((p for p in pages if int(p["page"]) == page_num), pages[0])
    return jsonify(
        {
            "filename": filename,
            "page": int(target["page"]),
            "total_pages": len(pages),
            "text": target["text"],
            "ocr": bool(target.get("ocr", False)),
            "has_table": bool(target.get("has_table", False)),
        }
    )


@api_bp.route("/api/analyze", methods=["POST"])
@limiter.limit("15 per minute")
def analyze():
    sid = _session_id()
    mgr = current_app.extensions["session_manager"]
    state = mgr.get_or_create(sid)
    if not state.chunks:
        return jsonify({"error": "Please upload at least one PDF before analyzing."}), 400

    payload = request.get_json(silent=True) or {}
    language = payload.get("language", "en")
    gemini = _build_gemini()

    try:
        result = analyze_documents(state, gemini, language=language)
    except GeminiUnavailableError:
        fields = (state.get_profile() or {}).get("fields", {})
        personal = ", ".join(f"{f['label']}: {f['display']}" for f in fields.values()) or "Not found in uploaded documents"
        result = {
            "sections": [
                {"key": "personal_information", "label": "Personal Information", "content": personal},
                {"key": "education", "label": "Education", "content": (fields.get("course") or {}).get("display", "Not found in uploaded documents")},
                {"key": "skills", "label": "Skills", "content": "Not found in uploaded documents"},
                {"key": "certifications", "label": "Certifications", "content": "Not found in uploaded documents"},
                {"key": "projects", "label": "Projects", "content": "Not found in uploaded documents"},
                {"key": "achievements", "label": "Achievements", "content": "Not found in uploaded documents"},
                {"key": "important_dates", "label": "Important Dates", "content": (fields.get("dob") or {}).get("display", "Not found in uploaded documents")},
            ],
            "sources": [{"filename": d.filename, "page": 1} for d in state.documents],
            "total_chunks": len(state.chunks),
            "latency_ms": 0.0,
        }

    qlog_id = _log_query(
        sid=sid,
        mode="analyze",
        category="Document Summary",
        language=language,
        retrieval_mode="all_chunks",
        ret_ms=0.0,
        llm_ms=result["latency_ms"],
        total_ms=result["latency_ms"],
        chunks_retrieved=result["total_chunks"],
        sources=result["sources"],
        is_not_found=False,
    )
    result["query_log_id"] = qlog_id
    return jsonify(result)


@api_bp.route("/api/chat", methods=["POST"])
@limiter.limit("30 per hour")
def chat():
    sid = _session_id()
    mgr = current_app.extensions["session_manager"]
    state = mgr.get_or_create(sid)

    payload = request.get_json(silent=True) or {}
    question = sanitize_input(payload.get("question", ""))
    if not question:
        return jsonify({"ok": False, "code": "empty_question", "message": "Please enter a question.", "error": "Please enter a question."}), 400

    retrieval_mode = payload.get("retrieval_mode") or current_app.config["RETRIEVAL_MODE"]
    if retrieval_mode not in {"baseline", "hybrid"}:
        retrieval_mode = "hybrid"
    lang_override = payload.get("language")
    if lang_override == "auto":
        lang_override = None

    schemes = load_scheme_manifest(
        Path(current_app.config["SAMPLES_DIR"]),
        schemes_path=Path(current_app.config["SCHEMES_PATH"]),
    )
    has_docs = bool(state.documents or state.pages_by_file)
    lang_detected = detect_language(question, lang_override)

    # 1. Check 24h LRU cache for non-personal queries
    if not has_docs:
        cached = get_cached_answer(question, lang_detected)
        if cached:
            cached["cached"] = True
            return jsonify(cached)

    gemini = _build_gemini()
    use_verified_only = (not gemini.is_configured) or (not _consume_daily_gemini_quota())
    if not use_verified_only:
        try:
            res = answer_question(
                state,
                question,
                gemini,
                retrieval_mode=retrieval_mode,
                top_k_max=current_app.config["TOP_K_MAX"],
                history_window=current_app.config["HISTORY_WINDOW"],
                enable_reranker=current_app.config["ENABLE_RERANKER"],
                reranker_model=current_app.config["RERANKER_MODEL"],
                language_override=lang_override,
                enable_multilingual=current_app.config["ENABLE_MULTILINGUAL"],
                schemes=schemes,
            )
            sources_dicts = [s.to_dict() for s in res.sources]
            qlog_id = _log_query(
                sid=sid,
                mode="qa",
                category=res.category,
                language=res.language,
                retrieval_mode=res.retrieval_mode,
                ret_ms=res.retrieval_latency_ms,
                llm_ms=res.llm_latency_ms,
                total_ms=res.total_latency_ms,
                chunks_retrieved=res.chunks_retrieved,
                sources=sources_dicts,
                is_not_found=res.is_not_found,
            )
            out = {
                "ok": True,
                "answer": res.answer,
                "sources": sources_dicts,
                "scheme_cards": [],
                "is_not_found": res.is_not_found,
                "intent": res.intent,
                "followups": res.followups,
                "category": res.category,
                "language": res.language,
                "mode": "ai",
                "query_log_id": qlog_id,
            }
            if not has_docs and not res.is_not_found:
                put_cached_answer(question, res.language, out)
            return jsonify(out)
        except GeminiUnavailableError:
            pass

    vres = answer_from_verified_data(question, schemes, state, lang_override)
    qlog_id = _log_query(
        sid=sid,
        mode="qa",
        category="Scholarship / Scheme",
        language=lang_detected,
        retrieval_mode="verified_data",
        ret_ms=0.0,
        llm_ms=0.0,
        total_ms=0.0,
        chunks_retrieved=0,
        sources=[],
        is_not_found=vres.is_not_found,
    )
    return jsonify(
        {
            "ok": True,
            "answer": vres.answer,
            "sources": [],
            "scheme_cards": vres.scheme_cards,
            "is_not_found": vres.is_not_found,
            "intent": vres.intent,
            "followups": vres.followups,
            "category": "Scholarship / Scheme",
            "language": lang_detected,
            "mode": "verified_data",
            "query_log_id": qlog_id,
        }
    )


@api_bp.route("/api/chat/stream", methods=["POST"])
@limiter.limit("30 per hour")
def chat_stream():
    sid = _session_id()
    mgr = current_app.extensions["session_manager"]
    state = mgr.get_or_create(sid)

    payload = request.get_json(silent=True) or {}
    question = sanitize_input(payload.get("question", ""))
    if not question:
        return jsonify({"ok": False, "code": "empty_question", "message": "Please enter a question.", "error": "Please enter a question."}), 400

    retrieval_mode = payload.get("retrieval_mode") or current_app.config["RETRIEVAL_MODE"]
    if retrieval_mode not in {"baseline", "hybrid"}:
        retrieval_mode = "hybrid"
    lang_override = payload.get("language")
    if lang_override == "auto":
        lang_override = None

    schemes = load_scheme_manifest(
        Path(current_app.config["SAMPLES_DIR"]),
        schemes_path=Path(current_app.config["SCHEMES_PATH"]),
    )
    has_docs = bool(state.documents or state.pages_by_file)
    lang_detected = detect_language(question, lang_override)
    gemini = _build_gemini()
    app_obj = current_app._get_current_object()

    def event_stream():
        # 1. Cache hit for non-personal queries
        if not has_docs:
            cached = get_cached_answer(question, lang_detected)
            if cached:
                yield f"event: token\ndata: {json.dumps({'text': cached['answer']})}\n\n"
                yield f"event: done\ndata: {json.dumps(cached)}\n\n"
                return

        # 2. Try Gemini if configured & within daily cap
        if gemini.is_configured and _consume_daily_gemini_quota():
            emitted_any = False
            errored = False
            for evt in stream_question(
                state,
                question,
                gemini,
                retrieval_mode=retrieval_mode,
                top_k_max=app_obj.config["TOP_K_MAX"],
                history_window=app_obj.config["HISTORY_WINDOW"],
                enable_reranker=app_obj.config["ENABLE_RERANKER"],
                reranker_model=app_obj.config["RERANKER_MODEL"],
                language_override=lang_override,
                enable_multilingual=app_obj.config["ENABLE_MULTILINGUAL"],
                schemes=schemes,
            ):
                name = evt["event"]
                data = evt["data"]
                if name == "error":
                    errored = True
                    break
                if name == "token":
                    emitted_any = True
                if name == "done":
                    with app_obj.app_context():
                        qlog_id = _log_query(
                            sid=sid,
                            mode="qa",
                            category=data["category"],
                            language=data["language"],
                            retrieval_mode=data["retrieval_mode"],
                            ret_ms=data["retrieval_latency_ms"],
                            llm_ms=data["llm_latency_ms"],
                            total_ms=data["total_latency_ms"],
                            chunks_retrieved=data["chunks_retrieved"],
                            sources=data["sources"],
                            is_not_found=data["is_not_found"],
                        )
                        data["query_log_id"] = qlog_id
                    if not has_docs and not data.get("is_not_found"):
                        put_cached_answer(question, data["language"], data)
                yield f"event: {name}\ndata: {json.dumps(data)}\n\n"
            if not errored or emitted_any:
                return

        # 3. Verified-data fallback (zero errors ever reach visitor)
        vres = answer_from_verified_data(question, schemes, state, lang_override)
        yield f"event: token\ndata: {json.dumps({'text': vres.answer})}\n\n"
        done_payload = {
            "ok": True,
            "answer": vres.answer,
            "sources": [],
            "scheme_cards": vres.scheme_cards,
            "is_not_found": vres.is_not_found,
            "intent": vres.intent,
            "followups": vres.followups,
            "category": "Scholarship / Scheme",
            "language": lang_detected,
            "mode": "verified_data",
        }
        yield f"event: done\ndata: {json.dumps(done_payload)}\n\n"

    return Response(
        stream_with_context(event_stream()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@api_bp.route("/api/eligibility", methods=["POST"])
@limiter.limit("25 per minute")
def check_eligibility():
    sid = _session_id()
    mgr = current_app.extensions["session_manager"]
    state = mgr.get_or_create(sid)
    samples_dir = Path(current_app.config["SAMPLES_DIR"])
    schemes_path = Path(current_app.config["SCHEMES_PATH"])

    scheme_id = request.form.get("scheme_id", "").strip()
    language = request.form.get("language", "en").strip()
    use_sample_citizen = request.form.get("use_sample_citizen", "false").lower() == "true"
    clear_uploaded = request.form.get("clear_uploaded_scheme", "false").lower() == "true"

    if clear_uploaded:
        mgr.clear_uploaded_scheme(sid)

    scheme_file = request.files.get("scheme_file")
    scheme_name = ""
    scheme_text = ""
    structured_scheme = None
    checked_source = "library"
    duplicate_scheme = False

    # Rule: An uploaded scheme file overrides the dropdown and is stored in scheme_documents
    if scheme_file and scheme_file.filename:
        raw_bytes = scheme_file.read()
        content_hash = hashlib.sha256(raw_bytes).hexdigest()
        try:
            doc = extract_pdf_document(
                raw_bytes,
                scheme_file.filename,
                enable_table_extraction=current_app.config["ENABLE_TABLE_EXTRACTION"],
                enable_ocr_fallback=current_app.config["ENABLE_OCR_FALLBACK"],
            )
            sdoc, duplicate_scheme = mgr.store_scheme_doc(sid, doc, content_hash)
            scheme_name = sdoc.filename
            scheme_text = sdoc.text
            checked_source = "uploaded_pdf"
        except PDFValidationError as exc:
            return jsonify({"error": str(exc)}), 400
    elif state.active_uploaded_scheme and not scheme_id:
        sdoc = state.scheme_documents[state.active_uploaded_scheme]
        scheme_name = sdoc.filename
        scheme_text = sdoc.text
        checked_source = "uploaded_pdf"
    elif scheme_id:
        mgr.clear_uploaded_scheme(sid)
        scheme = get_scheme_by_id(samples_dir, scheme_id, schemes_path=schemes_path)
        if not scheme:
            return jsonify({"error": "Selected scheme was not found."}), 404
        scheme_name = scheme.get("name") or scheme.get("title", "")
        structured_scheme = scheme if isinstance(scheme.get("rules"), dict) else None
        filename = scheme.get("filename", "")
        if filename and (samples_dir / filename).exists():
            doc = extract_pdf_document(
                (samples_dir / filename).read_bytes(),
                filename,
                enable_table_extraction=current_app.config["ENABLE_TABLE_EXTRACTION"],
                enable_ocr_fallback=False,
            )
            scheme_text = "\n\n".join(p.text for p in doc.pages)
        else:
            scheme_text = "\n".join(scheme.get("eligibility_text") or [scheme.get("summary", "")])
    else:
        return jsonify({"error": "Please select a scheme or upload a scheme guideline PDF."}), 400

    citizen_texts = dict(state.raw_texts_by_file)
    if use_sample_citizen and not citizen_texts:
        for sample_fn in [
            "sample_citizen_marksheet.pdf",
            "sample_citizen_resume.pdf",
            "sample_income_certificate.pdf",
        ]:
            p = samples_dir / sample_fn
            if p.exists():
                d = extract_pdf_document(p.read_bytes(), p.name, enable_ocr_fallback=False)
                citizen_texts[d.filename] = "\n\n".join(pg.text for pg in d.pages)

    if not citizen_texts:
        return jsonify(
            {
                "error": "No citizen documents in session. Upload your documents first or "
                "enable 'Use sample citizen documents'."
            }
        ), 400

    gemini = _build_gemini()
    result = evaluate_eligibility(
        scheme_name=scheme_name,
        scheme_text=scheme_text,
        citizen_texts_by_file=citizen_texts,
        gemini=gemini,
        language=language,
        structured_scheme=structured_scheme,
        profile_overrides=state.profile_overrides,
    )
    result["checked_scheme_source"] = checked_source
    result["checked_scheme_label"] = (
        f"Uploaded PDF: {scheme_name} (overrides dropdown)"
        if checked_source == "uploaded_pdf"
        else f"Library Scheme: {scheme_name}"
    )
    result["duplicate_scheme"] = duplicate_scheme
    result["citizen_documents"] = [d.to_dict() for d in state.documents]
    result["scheme_documents"] = [s.to_dict() for s in state.scheme_documents.values()]

    _log_query(
        sid=sid,
        mode="eligibility",
        category="Scholarship / Scheme",
        language=language,
        retrieval_mode="deterministic",
        ret_ms=0.0,
        llm_ms=0.0,
        total_ms=0.0,
        chunks_retrieved=len(citizen_texts),
        sources=[{"filename": fn, "page": 1} for fn in citizen_texts],
        is_not_found=False,
    )
    return jsonify(result)


@api_bp.route("/api/scheme-finder", methods=["POST"])
@api_bp.route("/api/scheme-match", methods=["POST"])
@limiter.limit("25 per minute")
def scheme_finder():
    """One-click Scheme Finder: match citizen profile against every scheme in the library."""
    sid = _session_id()
    mgr = current_app.extensions["session_manager"]
    state = mgr.get_or_create(sid)
    samples_dir = Path(current_app.config["SAMPLES_DIR"])
    schemes_path = Path(current_app.config["SCHEMES_PATH"])

    payload = request.get_json(silent=True) or {}
    use_sample = bool(payload.get("use_sample_citizen", False))
    citizen_texts = dict(state.raw_texts_by_file)

    if use_sample and not citizen_texts:
        for sample_fn in [
            "sample_citizen_marksheet.pdf",
            "sample_citizen_resume.pdf",
            "sample_income_certificate.pdf",
        ]:
            p = samples_dir / sample_fn
            if p.exists():
                d = extract_pdf_document(p.read_bytes(), p.name, enable_ocr_fallback=False)
                citizen_texts[d.filename] = "\n\n".join(pg.text for pg in d.pages)

    merged_overrides = dict(state.profile_overrides)
    merged_overrides.update(state.wizard_answers)
    if isinstance(payload.get("answers"), dict):
        merged_overrides.update(payload["answers"])
        state.wizard_answers = dict(payload["answers"])

    if not citizen_texts and not merged_overrides:
        return jsonify(
            {"error": "Answer a few quick questions or upload your documents first to find matching schemes."}
        ), 400

    lang = normalize_lang(payload.get("lang") or session.get("lang", "en"))
    schemes = load_scheme_manifest(samples_dir, schemes_path=schemes_path)
    matches = match_all_schemes(
        schemes=schemes,
        citizen_texts_by_file=citizen_texts,
        profile_overrides=merged_overrides,
        lang=lang,
    )
    counts = Counter(m["tier"] for m in matches)
    return jsonify(
        {
            "profile": state.get_profile(),
            "answers": state.wizard_answers,
            "checked_docs": state.checked_docs,
            "total_schemes": len(matches),
            "counts": {
                "eligible": counts.get("Eligible", 0),
                "likely": counts.get("Likely eligible", 0),
                "needs_info": counts.get("Needs more info", 0),
                "not_eligible": counts.get("Not eligible", 0),
            },
            "matches": matches,
        }
    )


@api_bp.route("/api/language", methods=["POST"])
def set_language():
    payload = request.get_json(silent=True) or {}
    lang = normalize_lang(payload.get("lang"))
    session["lang"] = lang
    sid = _session_id()
    mgr = current_app.extensions["session_manager"]
    state = mgr.get_or_create(sid)
    state.language = lang
    return jsonify({"lang": lang})


@api_bp.route("/api/wizard/save", methods=["POST"])
def save_wizard_answers():
    sid = _session_id()
    mgr = current_app.extensions["session_manager"]
    state = mgr.get_or_create(sid)
    payload = request.get_json(silent=True) or {}
    answers = payload.get("answers")
    if isinstance(answers, dict):
        state.wizard_answers = {k: v for k, v in answers.items() if v not in (None, "")}
    return jsonify({"answers": state.wizard_answers})


@api_bp.route("/api/scheme-preview-count", methods=["POST"])
def scheme_preview_count():
    sid = _session_id()
    mgr = current_app.extensions["session_manager"]
    state = mgr.get_or_create(sid)
    payload = request.get_json(silent=True) or {}
    answers = payload.get("answers") or {}
    samples_dir = Path(current_app.config["SAMPLES_DIR"])
    schemes_path = Path(current_app.config["SCHEMES_PATH"])
    schemes = load_scheme_manifest(samples_dir, schemes_path=schemes_path)
    merged = dict(state.profile_overrides)
    merged.update(answers)
    matches = match_all_schemes(
        schemes=schemes,
        citizen_texts_by_file=dict(state.raw_texts_by_file),
        profile_overrides=merged,
    )
    qualifying = sum(1 for m in matches if m["group"] in {"qualify", "check"})
    return jsonify({"matching_count": qualifying, "total": len(matches)})


@api_bp.route("/api/wizard/checklist", methods=["POST"])
def save_wizard_checklist():
    sid = _session_id()
    mgr = current_app.extensions["session_manager"]
    state = mgr.get_or_create(sid)
    payload = request.get_json(silent=True) or {}
    scheme_id = str(payload.get("scheme_id") or "").strip()
    checked = payload.get("checked")
    if scheme_id and isinstance(checked, list):
        state.checked_docs[scheme_id] = [str(x) for x in checked]
    return jsonify({"checked_docs": state.checked_docs})


@api_bp.route("/api/export/checklist", methods=["POST"])
def export_scheme_checklist():
    payload = request.get_json(silent=True) or {}
    fmt = str(payload.get("format") or "pdf").lower()
    scheme_name = str(payload.get("name") or payload.get("scheme_name") or "Government Scheme")
    benefit = str(payload.get("benefit") or "")
    url = str(payload.get("official_url") or "")
    docs = payload.get("required_documents") or []
    checked = set(payload.get("checked") or [])
    steps = payload.get("how_to_apply_steps") or []

    if fmt == "md":
        lines = [f"# Eligibility Checklist — {scheme_name}\n"]
        if benefit:
            lines.append(f"**Benefit:** {benefit}\n")
        if docs:
            lines.append("## Document Checklist")
            for d in docs:
                mark = "[x]" if d in checked else "[ ]"
                lines.append(f"- {mark} {d}")
        for av in payload.get("available_documents") or []:
            lines.append(f"- [x] {av.get('document', '')} ({av.get('supporting_filename', '')})")
        for ms in payload.get("missing_documents") or []:
            lines.append(f"- [ ] {ms}")
        if steps:
            lines.append("\n## How to Apply")
            for idx, st in enumerate(steps, 1):
                lines.append(f"{idx}. {st}")
        if url:
            lines.append(f"\nOfficial Website: {url}")
        return Response(
            "\n".join(lines),
            mimetype="text/markdown",
            headers={"Content-Disposition": "attachment; filename=scheme_checklist.md"},
        )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    styles = getSampleStyleSheet()
    story = [
        Paragraph(f"AI Citizen Assistant — {scheme_name}", styles["Title"]),
        Spacer(1, 10),
    ]
    if benefit:
        story.append(Paragraph(f"<b>Benefit:</b> {benefit}", styles["BodyText"]))
        story.append(Spacer(1, 8))
    if docs:
        story.append(Paragraph("Document Checklist", styles["Heading2"]))
        for d in docs:
            mark = "[Ready]" if d in checked else "[Needed]"
            story.append(Paragraph(f"{mark} {d}", styles["BodyText"]))
        story.append(Spacer(1, 8))
    if steps:
        story.append(Paragraph("How to Apply", styles["Heading2"]))
        for idx, st in enumerate(steps, 1):
            story.append(Paragraph(f"{idx}. {st}", styles["BodyText"]))
        story.append(Spacer(1, 8))
    if url:
        story.append(Paragraph(f"<b>Official Website:</b> {url}", styles["BodyText"]))
    doc.build(story)
    buf.seek(0)
    return send_file(
        buf,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="scheme_checklist.pdf",
    )


@api_bp.route("/api/feedback", methods=["POST"])
def submit_feedback():
    sid = _session_id()
    payload = request.get_json(silent=True) or {}
    rating = payload.get("rating")
    if rating not in (1, -1):
        return jsonify({"error": "Rating must be 1 or -1."}), 400
    query_log_id = payload.get("query_log_id")
    fb = FeedbackLog(session_id=sid, query_log_id=query_log_id, rating=int(rating))
    db.session.add(fb)
    db.session.commit()
    return jsonify({"status": "recorded", "id": fb.id})


@api_bp.route("/api/session/clear", methods=["POST"])
def clear_session_data():
    sid = _session_id()
    mgr = current_app.extensions["session_manager"]
    mgr.clear_session(sid)
    row = db.session.get(SessionLog, sid)
    if row is not None:
        row.is_cleared = True
        db.session.commit()
    session.pop("consent_given", None)
    return jsonify({"status": "cleared"})


@api_bp.route("/api/export/summary", methods=["POST"])
def export_summary():
    payload = request.get_json(silent=True) or {}
    fmt = payload.get("format", "md").lower()
    sections = payload.get("sections", [])
    sources = payload.get("sources", [])

    if fmt == "pdf":
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4)
        styles = getSampleStyleSheet()
        story = [
            Paragraph("AI Citizen Assistant - Document Summary", styles["Title"]),
            Spacer(1, 12),
        ]
        for sec in sections:
            story.append(Paragraph(sec.get("label", ""), styles["Heading2"]))
            content = (sec.get("content", "") or "").replace("\n", "<br/>")
            story.append(Paragraph(content, styles["BodyText"]))
            story.append(Spacer(1, 8))
        if sources:
            story.append(Paragraph("Cited Sources", styles["Heading2"]))
            src_line = ", ".join(f"{s['filename']} (Page {s['page']})" for s in sources)
            story.append(Paragraph(src_line, styles["BodyText"]))
        doc.build(story)
        buf.seek(0)
        return send_file(
            buf,
            mimetype="application/pdf",
            as_attachment=True,
            download_name="citizen_document_summary.pdf",
        )

    lines = ["# AI Citizen Assistant - Document Summary\n"]
    for sec in sections:
        lines.append(f"## {sec.get('label', '')}\n{sec.get('content', '')}\n")
    if sources:
        lines.append("## Sources")
        for s in sources:
            lines.append(f"- {s['filename']} (Page {s['page']})")
    return Response(
        "\n".join(lines),
        mimetype="text/markdown",
        headers={"Content-Disposition": "attachment; filename=citizen_document_summary.md"},
    )


@api_bp.route("/api/export/checklist", methods=["POST"])
def export_checklist():
    payload = request.get_json(silent=True) or {}
    fmt = payload.get("format", "md").lower()
    scheme_name = payload.get("scheme_name", "Scheme Checklist")
    verdict = payload.get("rule_based_verdict", "")
    available = payload.get("available_documents", [])
    missing = payload.get("missing_documents", [])

    if fmt == "pdf":
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4)
        styles = getSampleStyleSheet()
        story = [
            Paragraph(f"Eligibility Checklist: {scheme_name}", styles["Title"]),
            Paragraph(f"Rule-Based Verdict: <b>{verdict}</b>", styles["Heading3"]),
            Spacer(1, 10),
            Paragraph("Available Documents", styles["Heading2"]),
        ]
        for item in available:
            story.append(
                Paragraph(
                    f"[AVAILABLE] {item['document']} — Supporting file: {item['supporting_filename']}",
                    styles["BodyText"],
                )
            )
        story.append(Spacer(1, 8))
        story.append(Paragraph("Missing Documents", styles["Heading2"]))
        for m in missing or ["None"]:
            story.append(Paragraph(f"[MISSING] {m}", styles["BodyText"]))
        doc.build(story)
        buf.seek(0)
        return send_file(
            buf,
            mimetype="application/pdf",
            as_attachment=True,
            download_name="scheme_eligibility_checklist.pdf",
        )

    lines = [
        f"# Eligibility Checklist: {scheme_name}",
        f"**Rule-Based Verdict:** {verdict}\n",
        "## Available Documents",
    ]
    for item in available:
        lines.append(
            f"- [x] {item['document']} *(Supporting file: {item['supporting_filename']})*"
        )
    if not available:
        lines.append("- None detected")
    lines.append("\n## Missing Documents")
    for m in missing:
        lines.append(f"- [ ] {m}")
    if not missing:
        lines.append("- None missing")

    return Response(
        "\n".join(lines),
        mimetype="text/markdown",
        headers={"Content-Disposition": "attachment; filename=scheme_eligibility_checklist.md"},
    )


@api_bp.route("/api/analytics", methods=["GET"])
def analytics_data():
    include_demo = request.args.get("include_demo", "true").lower() != "false"
    s_query = SessionLog.query if include_demo else SessionLog.query.filter_by(is_demo=False)
    q_query = QueryLog.query if include_demo else QueryLog.query.filter_by(is_demo=False)
    f_query = FeedbackLog.query if include_demo else FeedbackLog.query.filter_by(is_demo=False)

    sessions = s_query.all()
    queries = q_query.order_by(QueryLog.created_at.desc()).all()
    feedbacks = f_query.all()

    total_sessions = len(sessions)
    total_docs = sum(s.doc_count for s in sessions)
    total_queries = len(queries)
    has_demo_data = (
        SessionLog.query.filter_by(is_demo=True).count() > 0
        or QueryLog.query.filter_by(is_demo=True).count() > 0
    )

    avg_latency = (
        round(sum(q.total_latency_ms for q in queries) / total_queries, 1)
        if total_queries
        else 0.0
    )
    not_found_count = sum(1 for q in queries if q.is_not_found)
    grounding_rate = (
        round(((total_queries - not_found_count) / total_queries) * 100.0, 1)
        if total_queries
        else 0.0
    )
    not_found_rate = (
        round((not_found_count / total_queries) * 100.0, 1) if total_queries else 0.0
    )

    up_votes = sum(1 for f in feedbacks if f.rating == 1)
    total_votes = len(feedbacks)
    thumbs_up_ratio = round((up_votes / total_votes) * 100.0, 1) if total_votes else 0.0

    by_day: dict[str, int] = defaultdict(int)
    by_category: Counter[str] = Counter()
    cited_counter: Counter[str] = Counter()
    latency_points: list[dict] = []

    for q in queries:
        day_str = q.created_at.strftime("%Y-%m-%d") if q.created_at else "unknown"
        by_day[day_str] += 1
        by_category[q.category] += 1
        try:
            for src in json.loads(q.cited_files_json or "[]"):
                fn = src.get("filename")
                if fn:
                    cited_counter[fn] += 1
        except Exception:
            pass
        if len(latency_points) < 40:
            latency_points.append(
                {
                    "retrieval_ms": round(q.retrieval_latency_ms, 1),
                    "llm_ms": round(q.llm_latency_ms, 1),
                    "mode": q.retrieval_mode,
                }
            )

    sorted_days = sorted(by_day.items())
    recent_activity = [
        {
            "id": q.id,
            "timestamp": q.created_at.strftime("%Y-%m-%d %H:%M") if q.created_at else "",
            "mode": q.mode,
            "category": q.category,
            "language": q.language,
            "retrieval_mode": q.retrieval_mode,
            "total_latency_ms": round(q.total_latency_ms, 1),
            "is_not_found": q.is_not_found,
            "is_demo": q.is_demo,
        }
        for q in queries[:15]
    ]

    return jsonify(
        {
            "kpis": {
                "total_sessions": total_sessions,
                "documents_processed": total_docs,
                "questions_asked": total_queries,
                "avg_latency_ms": avg_latency,
                "grounding_rate": grounding_rate,
                "not_found_rate": not_found_rate,
                "thumbs_up_ratio": thumbs_up_ratio,
                "total_feedback": total_votes,
                "has_demo_data": has_demo_data,
            },
            "questions_per_day": {
                "labels": [d for d, _ in sorted_days],
                "counts": [c for _, c in sorted_days],
            },
            "top_categories": {
                "labels": [k for k, _ in by_category.most_common(6)],
                "counts": [v for _, v in by_category.most_common(6)],
            },
            "latency_series": latency_points[::-1],
            "most_cited_docs": [
                {"filename": fn, "count": cnt} for fn, cnt in cited_counter.most_common(8)
            ],
            "recent_activity": recent_activity,
        }
    )


@api_bp.route("/api/demo-insights", methods=["POST"])
def toggle_demo_insights():
    """Load or clear clearly-labelled sample usage data for the Insights page."""
    from scripts.seed_demo import clear_demo_data, seed_demo_data

    payload = request.get_json(silent=True) or {}
    action = payload.get("action", "seed")
    if action == "clear":
        removed = clear_demo_data()
        return jsonify({"status": "cleared", "removed": removed})
    seed_demo_data()
    return jsonify({"status": "seeded"})


@api_bp.route("/api/eval", methods=["GET"])
def eval_data():
    eval_path = Path(current_app.config["EVAL_RESULTS_PATH"])
    if not eval_path.exists():
        legacy = Path(current_app.root_path).parent / "eval" / "results.json"
        if legacy.exists():
            eval_path = legacy
    if not eval_path.exists():
        return jsonify({"available": False, "results": None})
    try:
        return jsonify(
            {"available": True, "results": json.loads(eval_path.read_text(encoding="utf-8"))}
        )
    except Exception as exc:
        return jsonify({"available": False, "error": str(exc)}), 500
