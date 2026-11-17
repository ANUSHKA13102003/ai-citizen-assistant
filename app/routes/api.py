"""JSON, file upload, export, analytics, and SSE streaming API routes."""

from __future__ import annotations

import hashlib
import io
import json
import logging
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
from app.services.chunker import chunk_documents
from app.services.eligibility_engine import evaluate_eligibility
from app.services.gemini_client import GeminiClient, GeminiUnavailableError
from app.services.language_service import sanitize_input
from app.services.pdf_extractor import (
    PDFValidationError,
    _configure_tesseract,
    extract_pdf_document,
)
from app.services.rag_service import analyze_documents, answer_question, stream_question
from app.services.sample_library import get_scheme_by_id
from app.services.vector_store import get_embedder

logger = logging.getLogger(__name__)
api_bp = Blueprint("api", __name__)


def _session_id() -> str:
    if "cid" not in session:
        session["cid"] = uuid.uuid4().hex
    return session["cid"]


def _build_gemini() -> GeminiClient:
    return GeminiClient(
        api_key=current_app.config.get("GEMINI_API_KEY", ""),
        model=current_app.config.get("GEMINI_MODEL", "gemini-2.5-flash"),
    )


def _upsert_session_log(sid: str, state) -> None:
    ttl = int(current_app.config.get("SESSION_TTL_MINUTES", 60))
    now = datetime.now(UTC)
    row = db.session.get(SessionLog, sid)
    meta_files = [
        {"filename": d.filename, "pages": d.total_pages} for d in state.documents
    ]
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


def _log_query(sid: str, mode: str, category: str, language: str, retrieval_mode: str, ret_ms: float, llm_ms: float, total_ms: float, chunks_retrieved: int, sources: list[dict], is_not_found: bool) -> int:
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

    embedder_loaded = True
    try:
        get_embedder(current_app.config["EMBEDDING_MODEL"])
    except Exception:
        embedder_loaded = False

    return jsonify(
        {
            "status": "ok" if db_ok else "degraded",
            "database": "ok" if db_ok else "error",
            "embedder_ready": embedder_loaded,
            "gemini_configured": bool(current_app.config.get("GEMINI_API_KEY")),
            "gemini_model": current_app.config.get("GEMINI_MODEL"),
            "tesseract_available": _configure_tesseract(
                current_app.config.get("TESSERACT_CMD", "")
            ),
            "retrieval_mode": current_app.config.get("RETRIEVAL_MODE", "hybrid"),
        }
    ), (200 if db_ok else 503)


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
@limiter.limit("20 per minute")
def upload_pdfs():
    sid = _session_id()
    mgr = current_app.extensions["session_manager"]
    state = mgr.get_or_create(sid)

    if not (session.get("consent_given") or state.consent_given):
        return jsonify(
            {"error": "Please accept the privacy notice before uploading documents."}
        ), 400

    files = request.files.getlist("files")
    if not files or all(not f.filename for f in files):
        return jsonify({"error": "No PDF files were selected."}), 400

    max_files = int(current_app.config["MAX_FILES_PER_SESSION"])
    if len(files) > max_files:
        return jsonify({"error": f"You can upload at most {max_files} PDFs per session."}), 400

    extracted_docs = []
    file_hashes = []
    errors = []

    for f in files:
        if not f or not f.filename:
            continue
        raw_bytes = f.read()
        file_hashes.append(hashlib.sha256(raw_bytes + f.filename.encode("utf-8")).hexdigest())
        try:
            doc = extract_pdf_document(
                raw_bytes,
                f.filename,
                enable_table_extraction=current_app.config["ENABLE_TABLE_EXTRACTION"],
                enable_ocr_fallback=current_app.config["ENABLE_OCR_FALLBACK"],
                tesseract_cmd=current_app.config.get("TESSERACT_CMD", ""),
                max_file_size_bytes=current_app.config["MAX_FILE_SIZE_BYTES"],
                max_pages=current_app.config["MAX_PAGES_PER_PDF"],
            )
            extracted_docs.append(doc)
        except PDFValidationError as exc:
            errors.append(str(exc))

    if not extracted_docs:
        return jsonify({"error": " ".join(errors) or "Failed to extract any PDF pages."}), 400

    chunks = chunk_documents(
        extracted_docs,
        chunk_size=current_app.config["CHUNK_SIZE"],
        chunk_overlap=current_app.config["CHUNK_OVERLAP"],
    )
    state, rebuilt = mgr.update_documents(sid, extracted_docs, chunks, file_hashes)
    _upsert_session_log(sid, state)

    return jsonify(
        {
            "rebuilt": rebuilt,
            "chat_cleared": rebuilt,
            "total_chunks": len(chunks),
            "warnings": errors + [w for d in extracted_docs for w in d.warnings],
            "documents": [
                {
                    "filename": d.filename,
                    "total_pages": d.total_pages,
                    "extracted_pages": d.extracted_pages,
                    "ocr_pages": d.ocr_pages,
                    "table_pages": d.table_pages,
                    "skipped_image_pages": d.skipped_image_pages,
                }
                for d in state.documents
            ],
        }
    )


@api_bp.route("/api/load-demo-docs", methods=["POST"])
@limiter.limit("15 per minute")
def load_demo_docs():
    """Load synthetic sample citizen marksheet + resume + selected scheme into session."""
    sid = _session_id()
    mgr = current_app.extensions["session_manager"]
    state = mgr.get_or_create(sid)
    session["consent_given"] = True
    state.consent_given = True

    samples_dir = Path(current_app.config["SAMPLES_DIR"])
    payload = request.get_json(silent=True) or {}
    include_scheme_id = payload.get("scheme_id", "nsp_post_matric")

    target_files = [
        samples_dir / "sample_citizen_marksheet.pdf",
        samples_dir / "sample_citizen_resume.pdf",
        samples_dir / "sample_income_certificate.pdf",
    ]
    scheme = get_scheme_by_id(samples_dir, include_scheme_id)
    if scheme:
        target_files.append(samples_dir / scheme["filename"])

    extracted_docs = []
    file_hashes = []
    for path in target_files:
        if not path.exists():
            continue
        raw = path.read_bytes()
        file_hashes.append(hashlib.sha256(raw + path.name.encode("utf-8")).hexdigest())
        doc = extract_pdf_document(
            raw,
            path.name,
            enable_table_extraction=current_app.config["ENABLE_TABLE_EXTRACTION"],
            enable_ocr_fallback=current_app.config["ENABLE_OCR_FALLBACK"],
        )
        extracted_docs.append(doc)

    if not extracted_docs:
        return jsonify({"error": "Sample documents not found on disk."}), 404

    chunks = chunk_documents(
        extracted_docs,
        chunk_size=current_app.config["CHUNK_SIZE"],
        chunk_overlap=current_app.config["CHUNK_OVERLAP"],
    )
    state, rebuilt = mgr.update_documents(sid, extracted_docs, chunks, file_hashes)
    _upsert_session_log(sid, state)

    return jsonify(
        {
            "rebuilt": rebuilt,
            "total_chunks": len(chunks),
            "documents": [
                {
                    "filename": d.filename,
                    "total_pages": d.total_pages,
                    "extracted_pages": d.extracted_pages,
                    "ocr_pages": d.ocr_pages,
                    "table_pages": d.table_pages,
                    "skipped_image_pages": d.skipped_image_pages,
                }
                for d in state.documents
            ],
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
    except GeminiUnavailableError as exc:
        return jsonify({"error": str(exc)}), 503

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
@limiter.limit("30 per minute")
def chat():
    sid = _session_id()
    mgr = current_app.extensions["session_manager"]
    state = mgr.get_or_create(sid)

    payload = request.get_json(silent=True) or {}
    question = sanitize_input(payload.get("question", ""))
    if not question:
        return jsonify({"error": "Please enter a question."}), 400
    if not state.chunks:
        return jsonify({"error": "Please upload at least one PDF document first."}), 400

    retrieval_mode = payload.get("retrieval_mode") or current_app.config["RETRIEVAL_MODE"]
    if retrieval_mode not in {"baseline", "hybrid"}:
        retrieval_mode = "hybrid"
    lang_override = payload.get("language")
    if lang_override == "auto":
        lang_override = None

    gemini = _build_gemini()
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
        )
    except GeminiUnavailableError as exc:
        return jsonify({"error": str(exc)}), 503

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
    return jsonify(
        {
            "answer": res.answer,
            "sources": sources_dicts,
            "is_not_found": res.is_not_found,
            "category": res.category,
            "language": res.language,
            "retrieval_mode": res.retrieval_mode,
            "retrieval_latency_ms": res.retrieval_latency_ms,
            "llm_latency_ms": res.llm_latency_ms,
            "total_latency_ms": res.total_latency_ms,
            "query_log_id": qlog_id,
        }
    )


@api_bp.route("/api/chat/stream", methods=["POST"])
@limiter.limit("30 per minute")
def chat_stream():
    sid = _session_id()
    mgr = current_app.extensions["session_manager"]
    state = mgr.get_or_create(sid)

    payload = request.get_json(silent=True) or {}
    question = sanitize_input(payload.get("question", ""))
    if not question:
        return jsonify({"error": "Please enter a question."}), 400
    if not state.chunks:
        return jsonify({"error": "Please upload at least one PDF document first."}), 400

    retrieval_mode = payload.get("retrieval_mode") or current_app.config["RETRIEVAL_MODE"]
    if retrieval_mode not in {"baseline", "hybrid"}:
        retrieval_mode = "hybrid"
    lang_override = payload.get("language")
    if lang_override == "auto":
        lang_override = None

    gemini = _build_gemini()
    app_obj = current_app._get_current_object()

    def event_stream():
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
        ):
            name = evt["event"]
            data = evt["data"]
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
            yield f"event: {name}\ndata: {json.dumps(data)}\n\n"

    return Response(
        stream_with_context(event_stream()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@api_bp.route("/api/eligibility", methods=["POST"])
@limiter.limit("20 per minute")
def check_eligibility():
    sid = _session_id()
    mgr = current_app.extensions["session_manager"]
    state = mgr.get_or_create(sid)
    samples_dir = Path(current_app.config["SAMPLES_DIR"])

    scheme_id = request.form.get("scheme_id", "").strip()
    language = request.form.get("language", "en").strip()
    use_sample_citizen = request.form.get("use_sample_citizen", "false").lower() == "true"

    scheme_file = request.files.get("scheme_file")
    scheme_name = ""
    scheme_text = ""

    if scheme_file and scheme_file.filename:
        try:
            doc = extract_pdf_document(
                scheme_file.read(),
                scheme_file.filename,
                enable_table_extraction=current_app.config["ENABLE_TABLE_EXTRACTION"],
                enable_ocr_fallback=current_app.config["ENABLE_OCR_FALLBACK"],
            )
            scheme_name = doc.filename
            scheme_text = "\n\n".join(p.text for p in doc.pages)
        except PDFValidationError as exc:
            return jsonify({"error": str(exc)}), 400
    elif scheme_id:
        scheme = get_scheme_by_id(samples_dir, scheme_id)
        if not scheme:
            return jsonify({"error": "Selected scheme was not found."}), 404
        pdf_path = samples_dir / scheme["filename"]
        if not pdf_path.exists():
            return jsonify({"error": "Scheme PDF file is missing on disk."}), 404
        doc = extract_pdf_document(
            pdf_path.read_bytes(),
            scheme["filename"],
            enable_table_extraction=current_app.config["ENABLE_TABLE_EXTRACTION"],
            enable_ocr_fallback=False,
        )
        scheme_name = scheme["title"]
        scheme_text = "\n\n".join(p.text for p in doc.pages)
    else:
        return jsonify({"error": "Please select a scheme or upload a scheme guideline PDF."}), 400

    citizen_texts = dict(state.raw_texts_by_file)
    # Remove any scheme file if it happens to also be in session docs
    for fn in list(citizen_texts.keys()):
        if "scheme" in fn.lower() or "guideline" in fn.lower():
            del citizen_texts[fn]

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
                "error": "No citizen documents in session. Upload documents in Workspace first or "
                "enable 'Use Sample Citizen Documents'."
            }
        ), 400

    gemini = _build_gemini()
    result = evaluate_eligibility(
        scheme_name=scheme_name,
        scheme_text=scheme_text,
        citizen_texts_by_file=citizen_texts,
        gemini=gemini,
        language=language,
    )

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
        story = [Paragraph("AI Citizen Assistant - Document Summary", styles["Title"]), Spacer(1, 12)]
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
        lines.append(f"- [x] {item['document']} *(Supporting file: {item['supporting_filename']})*")
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
    sessions = SessionLog.query.all()
    queries = QueryLog.query.order_by(QueryLog.created_at.desc()).all()
    feedbacks = FeedbackLog.query.all()

    total_sessions = len(sessions)
    total_docs = sum(s.doc_count for s in sessions)
    total_queries = len(queries)
    has_demo_data = any(s.is_demo for s in sessions) or any(q.is_demo for q in queries)

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

    # Questions per day
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


@api_bp.route("/api/eval", methods=["GET"])
def eval_data():
    eval_path = Path(current_app.config["EVAL_RESULTS_PATH"])
    if not eval_path.exists():
        return jsonify({"available": False, "results": None})
    try:
        return jsonify({"available": True, "results": json.loads(eval_path.read_text(encoding="utf-8"))})
    except Exception as exc:
        return jsonify({"available": False, "error": str(exc)}), 500
