"""Tests for LangChain RecursiveCharacterTextSplitter (500/50) and metadata preservation."""

from __future__ import annotations

from app.services.chunker import chunk_documents
from app.services.pdf_extractor import extract_pdf_document
from tests.conftest import make_pdf_bytes


def test_chunking_size_overlap_and_metadata():
    long_p1 = " ".join(f"Token{i}" for i in range(180))  # > 1000 chars
    long_p2 = "Second page academic marksheet CGPA 8.9 percentage 84.5%."
    raw = make_pdf_bytes([long_p1, long_p2])

    doc = extract_pdf_document(raw, "marksheet_test.pdf", enable_ocr_fallback=False)
    chunks = chunk_documents([doc], chunk_size=500, chunk_overlap=50)

    assert len(chunks) >= 3
    for ch in chunks:
        assert len(ch.text) <= 500
        assert ch.filename == "marksheet_test.pdf"
        assert ch.page in (1, 2)
        meta = ch.to_metadata()
        assert set(["filename", "page", "ocr", "has_table", "chunk_index"]).issubset(meta.keys())

    pages_seen = {ch.page for ch in chunks}
    assert pages_seen == {1, 2}
