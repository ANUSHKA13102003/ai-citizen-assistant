"""Tests for Mode 1 (7 sections), Mode 2 fixed fallback, history window, and sources."""

from __future__ import annotations

import json

from app.services.chunker import chunk_documents
from app.services.language_service import FIXED_NOT_FOUND_EN
from app.services.pdf_extractor import extract_pdf_document
from app.services.rag_service import SUMMARY_SECTIONS, analyze_documents, answer_question
from app.services.session_manager import SessionManager
from tests.conftest import make_pdf_bytes


class MockGemini:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []
        self.is_configured = True

    def generate(self, system_prompt: str, user_prompt: str, history=None, **_kwargs) -> str:
        self.calls.append(
            {"system": system_prompt, "user": user_prompt, "history": list(history or [])}
        )
        return self.responses.pop(0)


def test_mode1_seven_sections_and_missing_marker():
    doc = extract_pdf_document(
        make_pdf_bytes(["Name: Riya Verma. B.Tech CSE 2026. Skills: Python, SQL."]),
        "resume.pdf",
        enable_ocr_fallback=False,
    )
    mgr = SessionManager()
    state, _ = mgr.update_documents("m1", [doc], chunk_documents([doc]), ["h1"])

    mock_payload = json.dumps(
        {
            "personal_information": "Riya Verma (resume.pdf, Page 1)",
            "education": "B.Tech CSE 2026 (resume.pdf, Page 1)",
            "skills": "Python, SQL (resume.pdf, Page 1)",
            "certifications": "",
            "projects": None,
            "achievements": "Not found in uploaded documents",
            "important_dates": "Not found in uploaded documents",
        }
    )
    gemini = MockGemini([mock_payload])
    res = analyze_documents(state, gemini)

    assert len(res["sections"]) == len(SUMMARY_SECTIONS) == 7
    by_key = {s["key"]: s["content"] for s in res["sections"]}
    assert "Riya Verma" in by_key["personal_information"]
    assert by_key["certifications"] == "Not found in uploaded documents"
    assert by_key["projects"] == "Not found in uploaded documents"
    assert res["sources"] == [{"filename": "resume.pdf", "page": 1}]
    mgr.clear_session("m1")


def test_mode2_fixed_fallback_and_history_window():
    doc = extract_pdf_document(
        make_pdf_bytes(["Aarav scored 86.0% in B.Tech Semester VI."]),
        "marks.pdf",
        enable_ocr_fallback=False,
    )
    mgr = SessionManager()
    state, _ = mgr.update_documents("m2", [doc], chunk_documents([doc]), ["h2"])

    gemini = MockGemini(
        [
            "86.0% (marks.pdf, Page 1)",
            "B.Tech Semester VI",
            "Verified",
            "Yes",
            FIXED_NOT_FOUND_EN,
        ]
    )
    for i in range(4):
        r = answer_question(state, f"Question {i}?", gemini, history_window=6)
        assert r.is_not_found is False
        assert r.sources == [{"filename": "marks.pdf", "page": 1}] or [
            s.to_dict() for s in r.sources
        ] == [{"filename": "marks.pdf", "page": 1}]

    # History window must hold at most 6 messages (3 user + 3 model turns)
    assert len(state.chat_history) == 6

    nf = answer_question(state, "What is my passport number?", gemini, history_window=6)
    assert nf.is_not_found is True
    assert nf.answer == FIXED_NOT_FOUND_EN
    assert nf.sources == []
    assert len(gemini.calls[-1]["history"]) == 6
    mgr.clear_session("m2")
