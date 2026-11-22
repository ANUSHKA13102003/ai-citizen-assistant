"""In-memory PDF validation and page-by-page extraction with table & OCR support."""

from __future__ import annotations

import io
import logging
import os
from dataclasses import dataclass, field

import pdfplumber
import pymupdf
import pytesseract
from PIL import Image
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from werkzeug.utils import secure_filename

logger = logging.getLogger(__name__)


class PDFValidationError(ValueError):
    """Raised when an uploaded file fails security or readability checks."""


@dataclass
class PageContent:
    filename: str
    page: int  # 1-indexed
    text: str
    ocr: bool = False
    has_table: bool = False


@dataclass
class ExtractedDocument:
    filename: str
    total_pages: int
    pages: list[PageContent] = field(default_factory=list)
    skipped_image_pages: int = 0
    ocr_pages: int = 0
    table_pages: int = 0
    warnings: list[str] = field(default_factory=list)


def _configure_tesseract(tesseract_cmd: str = "") -> bool:
    """Configure pytesseract binary path if available; return True if usable."""
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def validate_pdf_bytes(
    raw_bytes: bytes,
    original_filename: str,
    max_file_size_bytes: int = 15 * 1024 * 1024,
    max_pages: int = 100,
) -> tuple[str, PdfReader]:
    """Validate extension, size, magic bytes, encryption, and page limits."""
    safe_name = secure_filename(original_filename or "")
    if not safe_name or not safe_name.lower().endswith(".pdf"):
        raise PDFValidationError(
            f"'{original_filename or 'file'}' is not a valid PDF file (.pdf required)."
        )
    if not raw_bytes:
        raise PDFValidationError(f"'{safe_name}' is empty.")
    if len(raw_bytes) > max_file_size_bytes:
        limit_mb = round(max_file_size_bytes / (1024 * 1024), 1)
        raise PDFValidationError(f"'{safe_name}' exceeds the {limit_mb} MB per-file limit.")
    if not raw_bytes.lstrip()[:8].startswith(b"%PDF-"):
        raise PDFValidationError(f"'{safe_name}' failed PDF magic-byte verification.")

    try:
        reader = PdfReader(io.BytesIO(raw_bytes))
    except PdfReadError as exc:
        raise PDFValidationError(f"'{safe_name}' appears corrupted or unreadable.") from exc
    except Exception as exc:
        raise PDFValidationError(f"Could not parse '{safe_name}': {exc}") from exc

    if reader.is_encrypted:
        raise PDFValidationError(
            f"'{safe_name}' is password-protected. Please unlock the PDF before uploading."
        )

    page_count = len(reader.pages)
    if page_count == 0:
        raise PDFValidationError(f"'{safe_name}' contains 0 pages.")
    if page_count > max_pages:
        raise PDFValidationError(
            f"'{safe_name}' has {page_count} pages, exceeding the {max_pages}-page limit."
        )

    return safe_name, reader


def _extract_tables_for_pages(raw_bytes: bytes) -> dict[int, str]:
    """Extract markdown-like table text per 1-indexed page using pdfplumber."""
    tables_by_page: dict[int, str] = {}
    try:
        with pdfplumber.open(io.BytesIO(raw_bytes)) as pdf:
            for idx, page in enumerate(pdf.pages, start=1):
                tables = page.extract_tables() or []
                formatted_tables: list[str] = []
                for table in tables:
                    rows = []
                    for row in table:
                        if not row:
                            continue
                        cleaned_cells = [
                            (cell or "").replace("\n", " ").strip() for cell in row
                        ]
                        if any(cleaned_cells):
                            rows.append(" | ".join(cleaned_cells))
                    if rows:
                        formatted_tables.append("\n".join(rows))
                if formatted_tables:
                    tables_by_page[idx] = "[Extracted Table]\n" + "\n\n".join(formatted_tables)
    except Exception as exc:
        logger.debug("pdfplumber table extraction skipped: %s", exc)
    return tables_by_page


def _ocr_single_page(raw_bytes: bytes, page_index_zero: int) -> str:
    """Render a PDF page to an image with PyMuPDF and run Tesseract OCR."""
    doc = pymupdf.open(stream=raw_bytes, filetype="pdf")
    try:
        page = doc.load_page(page_index_zero)
        pix = page.get_pixmap(dpi=200)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        return (pytesseract.image_to_string(img, lang="eng+hin") or "").strip()
    except pytesseract.TesseractError:
        # Fallback to English-only traineddata if Hindi language pack is absent
        page = doc.load_page(page_index_zero)
        pix = page.get_pixmap(dpi=200)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        return (pytesseract.image_to_string(img, lang="eng") or "").strip()
    finally:
        doc.close()


def extract_pdf_document(
    raw_bytes: bytes,
    original_filename: str,
    *,
    enable_table_extraction: bool = True,
    enable_ocr_fallback: bool = True,
    tesseract_cmd: str = "",
    max_file_size_bytes: int = 15 * 1024 * 1024,
    max_pages: int = 100,
) -> ExtractedDocument:
    """Extract text page by page with pypdf (paper baseline) + optional tables & OCR."""
    safe_name, reader = validate_pdf_bytes(
        raw_bytes,
        original_filename,
        max_file_size_bytes=max_file_size_bytes,
        max_pages=max_pages,
    )

    total_pages = len(reader.pages)
    doc_result = ExtractedDocument(filename=safe_name, total_pages=total_pages)

    tables_by_page = _extract_tables_for_pages(raw_bytes) if enable_table_extraction else {}
    tesseract_ready = (
        _configure_tesseract(tesseract_cmd or os.getenv("TESSERACT_CMD", ""))
        if enable_ocr_fallback
        else False
    )
    ocr_unavailable_warned = False

    for page_num, page in enumerate(reader.pages, start=1):
        try:
            text = (page.extract_text() or "").strip()
        except Exception as exc:
            logger.warning("pypdf extraction failed for %s page %d: %s", safe_name, page_num, exc)
            text = ""

        is_ocr = False
        has_table = False

        if page_num in tables_by_page:
            table_text = tables_by_page[page_num]
            if table_text and table_text not in text:
                text = f"{text}\n\n{table_text}".strip() if text else table_text
                has_table = True
                doc_result.table_pages += 1

        if not text:
            if enable_ocr_fallback:
                if tesseract_ready:
                    try:
                        ocr_text = _ocr_single_page(raw_bytes, page_num - 1)
                    except Exception as exc:
                        logger.warning("OCR failed for %s page %d: %s", safe_name, page_num, exc)
                        ocr_text = ""
                    if ocr_text:
                        text = ocr_text
                        is_ocr = True
                        doc_result.ocr_pages += 1
                    else:
                        doc_result.skipped_image_pages += 1
                else:
                    doc_result.skipped_image_pages += 1
                    if not ocr_unavailable_warned:
                        doc_result.warnings.append(
                            f"'{safe_name}' contains scanned/image-only pages, and Tesseract OCR "
                            "is not installed locally. Image-only pages were skipped."
                        )
                        ocr_unavailable_warned = True
            else:
                doc_result.skipped_image_pages += 1

        if text:
            doc_result.pages.append(
                PageContent(
                    filename=safe_name,
                    page=page_num,
                    text=text,
                    ocr=is_ocr,
                    has_table=has_table,
                )
            )

    if not doc_result.pages:
        raise PDFValidationError(
            f"'{safe_name}' has no extractable text layer"
            + (
                " (and Tesseract OCR is unavailable or found no text)."
                if enable_ocr_fallback
                else "."
            )
        )

    return doc_result


_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png")


def extract_image_bytes(
    raw_bytes: bytes,
    original_filename: str,
    max_file_size_bytes: int = 15 * 1024 * 1024,
    tesseract_cmd: str = "",
) -> ExtractedDocument:
    """Validate and OCR a JPG/PNG document photo into a 1-page ExtractedDocument."""
    safe_name = secure_filename(original_filename or "")
    lower = safe_name.lower()
    if not safe_name or not lower.endswith(_IMAGE_EXTENSIONS):
        raise PDFValidationError(
            f"'{original_filename or 'file'}' is not a supported PDF or image (.pdf, .jpg, .png)."
        )
    if not raw_bytes:
        raise PDFValidationError(f"'{safe_name}' is empty.")
    if len(raw_bytes) > max_file_size_bytes:
        limit_mb = round(max_file_size_bytes / (1024 * 1024), 1)
        raise PDFValidationError(f"'{safe_name}' exceeds the {limit_mb} MB per-file limit.")

    try:
        with Image.open(io.BytesIO(raw_bytes)) as img:
            rgb = img.convert("RGB")
    except Exception as exc:
        raise PDFValidationError(f"'{safe_name}' could not be opened as an image.") from exc

    tesseract_ready = _configure_tesseract(
        tesseract_cmd or os.environ.get("TESSERACT_CMD", "")
    )
    if not tesseract_ready:
        raise PDFValidationError(
            f"'{safe_name}' is a photo, and text reading (OCR) is not available on this server. "
            "Please upload a digital PDF instead."
        )

    text = ""
    for lang in ("eng+hin", "eng"):
        try:
            text = pytesseract.image_to_string(rgb, lang=lang).strip()
            if text:
                break
        except Exception:
            continue

    if not text:
        raise PDFValidationError(
            f"Could not read clear text from '{safe_name}'. Please upload a clearer photo or a PDF."
        )

    return ExtractedDocument(
        filename=safe_name,
        total_pages=1,
        pages=[PageContent(filename=safe_name, page=1, text=text, ocr=True, has_table=False)],
        ocr_pages=1,
    )


def extract_document_bytes(
    raw_bytes: bytes,
    original_filename: str,
    max_file_size_bytes: int = 15 * 1024 * 1024,
    max_pages: int = 100,
    enable_ocr_fallback: bool = True,
    tesseract_cmd: str = "",
) -> ExtractedDocument:
    """Extract text from either a PDF or a JPG/PNG image upload."""
    lower = (original_filename or "").strip().lower()
    if lower.endswith(_IMAGE_EXTENSIONS):
        return extract_image_bytes(
            raw_bytes=raw_bytes,
            original_filename=original_filename,
            max_file_size_bytes=max_file_size_bytes,
            tesseract_cmd=tesseract_cmd,
        )
    return extract_pdf_document(
        raw_bytes=raw_bytes,
        original_filename=original_filename,
        max_file_size_bytes=max_file_size_bytes,
        max_pages=max_pages,
        enable_ocr_fallback=enable_ocr_fallback,
        tesseract_cmd=tesseract_cmd,
    )
