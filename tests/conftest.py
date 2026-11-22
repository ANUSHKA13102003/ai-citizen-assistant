"""Shared pytest fixtures and synthetic PDF byte helpers."""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402


def make_pdf_bytes(pages_text: list[str]) -> bytes:
    """Create a valid multi-page PDF in memory for unit tests."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    styles = getSampleStyleSheet()
    story = []
    for idx, text in enumerate(pages_text):
        if idx > 0:
            story.append(PageBreak())
        story.append(Paragraph(text, styles["BodyText"]))
    doc.build(story)
    return buf.getvalue()


@pytest.fixture()
def app():
    application = create_app("testing")
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()
