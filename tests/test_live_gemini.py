"""Live Gemini API integration test (runs when GEMINI_API_KEY is set in env or .env)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from app.config import clean_model_name
from app.services.chunker import chunk_documents
from app.services.gemini_client import GeminiClient
from app.services.pdf_extractor import extract_pdf_document
from app.services.rag_service import answer_question
from app.services.session_manager import SessionManager
from tests.conftest import make_pdf_bytes

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


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
        model=clean_model_name(os.getenv("GEMINI_MODEL")),
    )
    res = answer_question(state, "What percentage did Aarav Sharma score?", gemini)
    assert "86" in res.answer
    assert not res.is_not_found

    # Test automatic 404 model fallback from a retired model id
    fallback_client = GeminiClient(
        api_key=os.environ["GEMINI_API_KEY"],
        model="gemini-1.0-nonexistent-flash",
    )
    res2 = answer_question(state, "What percentage did Aarav Sharma score?", fallback_client)
    assert "86" in res2.answer
    assert fallback_client.model != "gemini-1.0-nonexistent-flash"
    mgr.clear_session("live_test")
