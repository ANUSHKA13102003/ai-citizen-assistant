"""Tests for My Documents auto-fill extraction (marks %, income, DOB month names, state, education)."""

from __future__ import annotations

import io
from datetime import date

from app.services.doc_intel import analyze_document, build_profile, profile_value
from app.services.pdf_extractor import extract_pdf_document
from tests.conftest import make_pdf_bytes


def test_fictional_marksheet_and_income_autofill(client):
    marksheet = make_pdf_bytes(
        [
            "Dr. A.P.J. University, Lucknow, Uttar Pradesh\n"
            "Statement of Marks - B.Sc Computer Science\n"
            "Student Name: Priya Verma\n"
            "DOB: 14 March 2005\n"
            "Category: OBC-NCL\n"
            "Marks: 78.2% | Result: PASS\n"
        ]
    )
    income_cert = make_pdf_bytes(
        [
            "Government of Uttar Pradesh\n"
            "Income Certificate issued by Tehsildar\n"
            "Annual Family Income: Rs. 2,40,000\n"
        ]
    )

    # Unit check on doc_intel
    doc1 = extract_pdf_document(marksheet, "priya_marksheet.pdf", enable_ocr_fallback=False)
    doc2 = extract_pdf_document(income_cert, "priya_income.pdf", enable_ocr_fallback=False)
    ins1 = analyze_document(doc1)
    ins2 = analyze_document(doc2)
    profile = build_profile([ins1, ins2])

    assert profile_value(profile, "marks_percent") == 78.2
    assert profile_value(profile, "annual_income_inr") == 240000.0
    assert profile_value(profile, "state") == "Uttar Pradesh"
    assert profile_value(profile, "education_level") == "undergraduate"
    assert profile_value(profile, "occupation") == "student"
    assert profile_value(profile, "age") == date.today().year - 2005
    assert "marksheet" in profile["doc_types"]
    assert "income_certificate" in profile["doc_types"]

    # Integration check via /api/upload
    resp = client.post(
        "/api/upload",
        data={
            "files": [
                (io.BytesIO(marksheet), "priya_marksheet.pdf"),
                (io.BytesIO(income_cert), "priya_income.pdf"),
            ]
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    data = resp.get_json()
    fields = data["profile"]["fields"]
    assert fields["marks_percent"]["value"] == 78.2
    assert fields["annual_income_inr"]["value"] == 240000.0
    assert fields["state"]["value"] == "Uttar Pradesh"
