"""Tests for paper baseline vector retrieval (k=min(20,N)) and hybrid BM25+RRF."""

from __future__ import annotations

from app.services.chunker import chunk_documents
from app.services.pdf_extractor import extract_pdf_document
from app.services.vector_store import SessionVectorIndex
from tests.conftest import make_pdf_bytes


def test_baseline_and_hybrid_retrieval():
    pages = [
        "Resume summary: Python developer skilled in Flask, SQL, and Docker.",
        "Certificate ID UP-INC-2026-999111 states Annual Family Income Rs. 1,50,000.",
        "Scheme guideline: NSP Post-Matric requires 60% marks and income certificate.",
    ]
    doc = extract_pdf_document(make_pdf_bytes(pages), "bundle.pdf", enable_ocr_fallback=False)
    chunks = chunk_documents([doc])

    index = SessionVectorIndex(session_id="test_retrieval_idx")
    count = index.rebuild(chunks)
    assert count == len(chunks)

    # Baseline k = min(20, N)
    base_hits = index.retrieve("UP-INC-2026-999111", top_k_max=20, mode="baseline")
    assert len(base_hits) == min(20, count)

    # Hybrid BM25 + Vector RRF boosts exact alphanumeric certificate ID to top
    hyb_hits = index.retrieve("UP-INC-2026-999111", top_k_max=20, mode="hybrid")
    assert len(hyb_hits) >= 1
    assert hyb_hits[0].page == 2
    assert "UP-INC-2026-999111" in hyb_hits[0].text
    index.clear()
