"""Optional live Gemini API integration test (runs only when GEMINI_API_KEY is set)."""

from __future__ import annotations

import os

import pytest

from app.services.chunker import chunk_documents
from app.services.gemini_client import GeminiClient
from app.services.pdf_extractor import extract_pdf_document
from app.services.rag_service import answer_question
from app.services.session_manager import SessionManager
from tests.conftest import make_pdf_bytes


@pytest.mark.skipif(
    not os.getenv("GEMINI_API_KEY", "").strip(),
    reason="GEMINI_API_KEY not configured",
)
def test_live_gemini_grounded_qa_and_fallback():
    doc = extract_pdf_document(
        make_pdf_bytes(["Aarav Sharma scored 86.0% in B.Tech Semester VI."]),
        "live_marksheet.pdf",
        enable_ocr_fallback=False,
    )
    mgr = SessionManager()
    state, _ = mgr.update_documents("live_test", [doc], chunk_documents([doc]), ["h_live"])
    gemini = GeminiClient(
        api_key=os.environ["GEMINI_API_KEY"],
        model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
    )
    res = answer_question(state, "What percentage did Aarav Sharma score?", gemini)
    assert "86" in res.answer
    assert not res.is_not_found

    nf = answer_question(state, "What is Aarav Sharma's passport number?", gemini)
    assert nf.is_not_found is True
    mgr.clear_session("live_test")
