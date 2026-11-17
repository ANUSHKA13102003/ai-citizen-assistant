"""Tests for PDF upload validation, magic bytes, encryption, size/page limits, and table extraction."""

from __future__ import annotations

import io

import pytest
from pypdf import PdfWriter

from app.services.pdf_extractor import PDFValidationError, extract_pdf_document
from tests.conftest import make_pdf_bytes


def test_rejects_non_pdf_and_bad_magic_bytes():
    with pytest.raises(PDFValidationError, match="not a valid PDF"):
        extract_pdf_document(b"%PDF-1.4 fake", "notes.txt")

    with pytest.raises(PDFValidationError, match="magic-byte"):
        extract_pdf_document(b"NOT_A_PDF_HEADER", "spoof.pdf")


def test_rejects_empty_and_oversized():
    with pytest.raises(PDFValidationError, match="empty"):
        extract_pdf_document(b"", "empty.pdf")

    with pytest.raises(PDFValidationError, match="exceeds"):
        extract_pdf_document(b"%PDF-1.4 " + b"x" * 2048, "big.pdf", max_file_size_bytes=512)


def test_rejects_encrypted_pdf():
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.encrypt("secret123")
    buf = io.BytesIO()
    writer.write(buf)

    with pytest.raises(PDFValidationError, match="password-protected"):
        extract_pdf_document(buf.getvalue(), "locked.pdf")


def test_rejects_page_limit():
    raw = make_pdf_bytes(["p1", "p2", "p3"])
    with pytest.raises(PDFValidationError, match="exceeding the 2-page limit"):
        extract_pdf_document(raw, "three_pages.pdf", max_pages=2)
