"""Tests for strict per-session isolation, collection rebuild, and chat clearing."""

from __future__ import annotations

from app.services.chunker import chunk_documents
from app.services.pdf_extractor import extract_pdf_document
from app.services.session_manager import SessionManager
from tests.conftest import make_pdf_bytes


def test_session_isolation_and_rebuild_clears_history():
    mgr = SessionManager()

    doc_a = extract_pdf_document(
        make_pdf_bytes(["Citizen Alpha has Aadhaar 1111 and CGPA 9.1."]),
        "alpha.pdf",
        enable_ocr_fallback=False,
    )
    doc_b = extract_pdf_document(
        make_pdf_bytes(["Citizen Beta has income Rs 120000 and works in Pune."]),
        "beta.pdf",
        enable_ocr_fallback=False,
    )

    state_a, rebuilt_a = mgr.update_documents("sess_a", [doc_a], chunk_documents([doc_a]), ["h_a"])
    state_b, rebuilt_b = mgr.update_documents("sess_b", [doc_b], chunk_documents([doc_b]), ["h_b"])
    assert rebuilt_a is True
    assert rebuilt_b is True

    hits_a = state_a.vector_index.retrieve("Pune income", mode="baseline")
    assert all(h.filename == "alpha.pdf" for h in hits_a)

    hits_b = state_b.vector_index.retrieve("Aadhaar 1111", mode="baseline")
    assert all(h.filename == "beta.pdf" for h in hits_b)

    # Append chat history, then rebuild with changed file set -> chat history cleared
    state_a.append_chat_turn("What is my CGPA?", "Your CGPA is 9.1.", history_window=6)
    assert len(state_a.chat_history) == 2

    state_a2, rebuilt_changed = mgr.update_documents(
        "sess_a", [doc_b], chunk_documents([doc_b]), ["h_b_new"]
    )
    assert rebuilt_changed is True
    assert state_a2.chat_history == []

    # Delete my data now
    assert mgr.clear_session("sess_a") is True
    assert mgr.clear_session("sess_a") is False
