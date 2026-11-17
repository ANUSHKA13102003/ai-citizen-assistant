"""RAG orchestration for Mode 1 (7-section summary) and Mode 2 (grounded Q&A + SSE)."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Iterator
from dataclasses import dataclass, field

from app.services.chunker import DocumentChunk
from app.services.gemini_client import GeminiClient, GeminiUnavailableError
from app.services.language_service import (
    FIXED_NOT_FOUND_EN,
    FIXED_NOT_FOUND_HI,
    categorize_query,
    detect_language,
)
from app.services.session_manager import SessionState
from app.services.vector_store import RetrievedChunk

SUMMARY_SECTIONS = [
    ("personal_information", "Personal Information"),
    ("education", "Education"),
    ("skills", "Skills"),
    ("certifications", "Certifications"),
    ("projects", "Projects"),
    ("achievements", "Achievements"),
    ("important_dates", "Important Dates"),
]

_SCHEME_KEYWORDS = (
    "scheme",
    "scholarship",
    "eligible",
    "eligibility",
    "available document",
    "missing document",
    "required document",
    "documents needed",
    "checklist",
    "yojana",
    "छात्रवृत्ति",
    "योजना",
    "दस्तावेज़",
)


@dataclass
class SourceCitation:
    filename: str
    page: int

    def to_dict(self) -> dict:
        return {"filename": self.filename, "page": self.page}


@dataclass
class RAGResponse:
    answer: str
    sources: list[SourceCitation] = field(default_factory=list)
    is_not_found: bool = False
    category: str = "General"
    language: str = "en"
    retrieval_mode: str = "hybrid"
    retrieval_latency_ms: float = 0.0
    llm_latency_ms: float = 0.0
    total_latency_ms: float = 0.0
    chunks_retrieved: int = 0


def deduplicate_sources(chunks: list[RetrievedChunk] | list[DocumentChunk]) -> list[SourceCitation]:
    """Return sorted distinct (filename, page) citations."""
    seen: set[tuple[str, int]] = set()
    sources: list[SourceCitation] = []
    for ch in chunks:
        key = (ch.filename, int(ch.page))
        if key not in seen:
            seen.add(key)
            sources.append(SourceCitation(filename=key[0], page=key[1]))
    sources.sort(key=lambda s: (s.filename.lower(), s.page))
    return sources


def _format_context_blocks(chunks: list[RetrievedChunk] | list[DocumentChunk]) -> str:
    blocks = []
    for ch in chunks:
        blocks.append(f"[Source: {ch.filename}, Page {ch.page}]\n{ch.text}")
    return "\n\n---\n\n".join(blocks)


def _is_scheme_question(question: str) -> bool:
    q = (question or "").lower()
    return any(kw in q for kw in _SCHEME_KEYWORDS)


def _build_qa_system_prompt(language: str, is_scheme: bool, uploaded_filenames: list[str]) -> str:
    lang_instruction = (
        "Respond in Hindi (Devanagari script), keeping exact document names, numbers, and "
        "citations accurate."
        if language == "hi"
        else "Respond clearly in English."
    )
    not_found_exact = FIXED_NOT_FOUND_HI if language == "hi" else FIXED_NOT_FOUND_EN

    scheme_rule = ""
    if is_scheme:
        files_str = ", ".join(uploaded_filenames) if uploaded_filenames else "None"
        scheme_rule = (
            "\nSTANDING SCHEME RULE (MANDATORY for scheme/document comparison questions):\n"
            f"Currently uploaded filenames in this session: [{files_str}].\n"
            "You MUST output three clearly labelled sections:\n"
            "1. **Available Documents**\n"
            "2. **Missing Documents**\n"
            "3. **Supporting Filename per Available Item**\n"
            "NEVER claim a required document is available unless concrete evidence for it exists "
            "in the uploaded documents above.\n"
        )

    return (
        "You are AI Citizen Assistant, a strictly grounded document intelligence assistant for "
        "Indian citizens.\n"
        "RULES:\n"
        "1. Answer ONLY using facts explicitly stated in the provided Context Chunks.\n"
        "2. Do NOT use outside knowledge, assumptions, or guesswork.\n"
        f'3. If the answer cannot be verified from the Context Chunks, reply ONLY with:\n'
        f'"{not_found_exact}"\n'
        "4. Cite supporting facts inline as (filename, Page X) where helpful.\n"
        f"5. {lang_instruction}\n"
        f"{scheme_rule}"
    )


def analyze_documents(
    session_state: SessionState,
    gemini: GeminiClient,
    language: str = "en",
) -> dict:
    """Mode 1: Send all chunks and extract the 7 structured sections from the paper."""
    if not session_state.chunks:
        raise ValueError("No documents uploaded in this session.")

    t0 = time.perf_counter()
    context_text = _format_context_blocks(session_state.chunks)
    section_keys = [k for k, _ in SUMMARY_SECTIONS]

    system_prompt = (
        "You are AI Citizen Assistant performing Mode 1: Analyze My Documents.\n"
        "Extract information strictly from the uploaded citizen document chunks.\n"
        "Return a valid JSON object with EXACTLY these 7 keys:\n"
        f"{json.dumps(section_keys)}\n"
        "For each key, provide a concise bullet-point summary or structured text grounded ONLY "
        "in the chunks (include filename and page in parentheses). If a section has no "
        'information in the chunks, set its value to exact string: '
        '"Not found in uploaded documents".\n'
        + (
            "Write the summary values in Hindi (except keep 'Not found in uploaded documents' "
            "or include it alongside Hindi if missing)."
            if language == "hi"
            else "Write the summary values in English."
        )
    )
    user_prompt = f"Uploaded Document Chunks:\n\n{context_text}"

    raw = gemini.generate(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.1,
        response_mime_type="application/json",
    )

    parsed: dict[str, str] = {}
    try:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.DOTALL)
        data = json.loads(cleaned)
        if isinstance(data, dict):
            for key, _label in SUMMARY_SECTIONS:
                val = data.get(key)
                if isinstance(val, list):
                    val = "\n".join(f"- {item}" for item in val if str(item).strip())
                elif isinstance(val, dict):
                    val = "\n".join(f"- {k}: {v}" for k, v in val.items())
                parsed[key] = str(val).strip() if val else "Not found in uploaded documents"
    except Exception:
        for key, _label in SUMMARY_SECTIONS:
            parsed[key] = "Not found in uploaded documents"
        parsed["personal_information"] = raw or "Not found in uploaded documents"

    for key, _ in SUMMARY_SECTIONS:
        if not parsed.get(key):
            parsed[key] = "Not found in uploaded documents"

    sources = [s.to_dict() for s in deduplicate_sources(session_state.chunks)]
    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
    result = {
        "sections": [
            {"key": k, "label": label, "content": parsed[k]} for k, label in SUMMARY_SECTIONS
        ],
        "sources": sources,
        "latency_ms": elapsed_ms,
        "total_chunks": len(session_state.chunks),
    }
    session_state.last_summary = result
    return result


def answer_question(
    session_state: SessionState,
    question: str,
    gemini: GeminiClient,
    *,
    retrieval_mode: str = "hybrid",
    top_k_max: int = 20,
    history_window: int = 6,
    enable_reranker: bool = False,
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
    language_override: str | None = None,
    enable_multilingual: bool = True,
) -> RAGResponse:
    """Mode 2: Grounded Q&A with k=min(20,N), history=last 6 messages, and distinct sources."""
    t_start = time.perf_counter()
    lang = detect_language(question, language_override) if enable_multilingual else "en"
    category = categorize_query(question)

    if session_state.vector_index.count() == 0:
        return RAGResponse(
            answer=FIXED_NOT_FOUND_HI if lang == "hi" else FIXED_NOT_FOUND_EN,
            sources=[],
            is_not_found=True,
            category=category,
            language=lang,
            retrieval_mode=retrieval_mode,
        )

    t_ret0 = time.perf_counter()
    retrieved = session_state.vector_index.retrieve(
        question,
        top_k_max=top_k_max,
        mode=retrieval_mode,
        enable_reranker=enable_reranker,
        reranker_model=reranker_model,
    )
    ret_ms = round((time.perf_counter() - t_ret0) * 1000.0, 2)

    if not retrieved:
        return RAGResponse(
            answer=FIXED_NOT_FOUND_HI if lang == "hi" else FIXED_NOT_FOUND_EN,
            sources=[],
            is_not_found=True,
            category=category,
            language=lang,
            retrieval_mode=retrieval_mode,
            retrieval_latency_ms=ret_ms,
            total_latency_ms=round((time.perf_counter() - t_start) * 1000.0, 2),
        )

    is_scheme = _is_scheme_question(question)
    uploaded_names = [d.filename for d in session_state.documents]
    system_prompt = _build_qa_system_prompt(lang, is_scheme, uploaded_names)
    context_block = _format_context_blocks(retrieved)
    user_prompt = f"Context Chunks:\n\n{context_block}\n\nCitizen Question: {question}"
    history = session_state.get_history_window(history_window)

    t_llm0 = time.perf_counter()
    answer_text = gemini.generate(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        history=history,
        temperature=0.1,
    )
    llm_ms = round((time.perf_counter() - t_llm0) * 1000.0, 2)

    is_not_found = FIXED_NOT_FOUND_EN.lower() in answer_text.lower()
    if is_not_found and lang == "en":
        answer_text = FIXED_NOT_FOUND_EN

    sources = [] if is_not_found else deduplicate_sources(retrieved)
    session_state.append_chat_turn(question, answer_text, history_window=history_window)

    return RAGResponse(
        answer=answer_text,
        sources=sources,
        is_not_found=is_not_found,
        category=category,
        language=lang,
        retrieval_mode=retrieval_mode,
        retrieval_latency_ms=ret_ms,
        llm_latency_ms=llm_ms,
        total_latency_ms=round((time.perf_counter() - t_start) * 1000.0, 2),
        chunks_retrieved=len(retrieved),
    )


def stream_question(
    session_state: SessionState,
    question: str,
    gemini: GeminiClient,
    *,
    retrieval_mode: str = "hybrid",
    top_k_max: int = 20,
    history_window: int = 6,
    enable_reranker: bool = False,
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
    language_override: str | None = None,
    enable_multilingual: bool = True,
) -> Iterator[dict]:
    """Yield SSE events ('meta', 'token', 'done', or 'error') for streaming Q&A."""
    t_start = time.perf_counter()
    lang = detect_language(question, language_override) if enable_multilingual else "en"
    category = categorize_query(question)

    if session_state.vector_index.count() == 0:
        fallback = FIXED_NOT_FOUND_HI if lang == "hi" else FIXED_NOT_FOUND_EN
        yield {"event": "token", "data": {"text": fallback}}
        yield {
            "event": "done",
            "data": {
                "answer": fallback,
                "sources": [],
                "is_not_found": True,
                "category": category,
                "language": lang,
                "retrieval_mode": retrieval_mode,
                "retrieval_latency_ms": 0.0,
                "llm_latency_ms": 0.0,
                "total_latency_ms": 0.0,
                "chunks_retrieved": 0,
            },
        }
        return

    t_ret0 = time.perf_counter()
    retrieved = session_state.vector_index.retrieve(
        question,
        top_k_max=top_k_max,
        mode=retrieval_mode,
        enable_reranker=enable_reranker,
        reranker_model=reranker_model,
    )
    ret_ms = round((time.perf_counter() - t_ret0) * 1000.0, 2)
    sources = deduplicate_sources(retrieved)

    is_scheme = _is_scheme_question(question)
    uploaded_names = [d.filename for d in session_state.documents]
    system_prompt = _build_qa_system_prompt(lang, is_scheme, uploaded_names)
    context_block = _format_context_blocks(retrieved)
    user_prompt = f"Context Chunks:\n\n{context_block}\n\nCitizen Question: {question}"
    history = session_state.get_history_window(history_window)

    t_llm0 = time.perf_counter()
    full_chunks: list[str] = []
    try:
        for delta in gemini.generate_stream(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            history=history,
            temperature=0.1,
        ):
            full_chunks.append(delta)
            yield {"event": "token", "data": {"text": delta}}
    except GeminiUnavailableError as exc:
        yield {"event": "error", "data": {"message": str(exc)}}
        return

    llm_ms = round((time.perf_counter() - t_llm0) * 1000.0, 2)
    answer_text = "".join(full_chunks).strip()
    is_not_found = FIXED_NOT_FOUND_EN.lower() in answer_text.lower()
    if is_not_found and lang == "en":
        answer_text = FIXED_NOT_FOUND_EN
    final_sources = [] if is_not_found else [s.to_dict() for s in sources]

    session_state.append_chat_turn(question, answer_text, history_window=history_window)

    yield {
        "event": "done",
        "data": {
            "answer": answer_text,
            "sources": final_sources,
            "is_not_found": is_not_found,
            "category": category,
            "language": lang,
            "retrieval_mode": retrieval_mode,
            "retrieval_latency_ms": ret_ms,
            "llm_latency_ms": llm_ms,
            "total_latency_ms": round((time.perf_counter() - t_start) * 1000.0, 2),
            "chunks_retrieved": len(retrieved),
        },
    }
