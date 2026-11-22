"""Integration tests for routes, deduplication, separate scheme vs citizen stores, and exports."""

from __future__ import annotations

import io

from app.config import clean_model_name
from app.services.gemini_client import pick_best_flash
from tests.conftest import make_pdf_bytes


def test_model_name_cleaner_and_flash_picker():
    assert clean_model_name("GEMINI_MODEL=gemini-3.8-flash") == "gemini-3.8-flash"
    assert clean_model_name("models/gemini-3.8-flash") == "gemini-3.8-flash"
    best = pick_best_flash(
        [
            "models/gemini-2.5-flash-tts",
            "models/gemini-3.8-flash-tts",
            "models/gemini-3.8-flash",
            "models/gemini-3.5-flash-lite",
        ]
    )
    assert best == "gemini-3.8-flash"


def test_all_pages_and_healthz(client):
    forbidden_terms = [
        "iilm",
        "capstone",
        "bt-90",
        "ieee",
        "table iv",
        "section iii-i",
        "hilal",
        "zero hallucination",
        "passport number",
        "chromadb",
        "embeddings",
        "live scheme match preview",
    ]
    for route in [
        "/",
        "/find-schemes",
        "/documents",
        "/ask",
        "/schemes",
        "/schemes/pm-kisan",
        "/privacy",
        "/help",
    ]:
        resp = client.get(route)
        assert resp.status_code == 200, f"Route {route} returned {resp.status_code}"
        body_low = resp.get_data(as_text=True).lower()
        for term in forbidden_terms:
            assert term not in body_low, f"Forbidden term '{term}' found on {route}"

    # Legacy/research pages removed or redirected
    assert client.get("/about").status_code == 404
    assert client.get("/accuracy").status_code == 404
    assert client.get("/evaluation").status_code == 404
    assert client.get("/admin/insights").status_code == 404
    assert client.get("/workspace").status_code == 302
    assert client.get("/eligibility").status_code == 302

    assert client.get("/robots.txt").status_code == 200
    assert client.get("/sitemap.xml").status_code == 200

    hz = client.get("/healthz")
    assert hz.status_code == 200
    assert hz.get_json()["status"] == "ok"


def test_pii_redaction_and_bilingual_toggle(client):
    from app.services.pii_redactor import redact_text

    sample = "Aadhaar 1234 5678 9012, PAN ABCDE1234F, Account No 98765432101234, Phone +91 9876543210, Email a@b.in"
    out = redact_text(sample)
    assert "1234 5678 9012" not in out
    assert "ABCDE1234F" not in out
    assert "98765432101234" not in out
    assert "9876543210" not in out
    assert "a@b.in" not in out

    res_hi = client.post("/api/language", json={"lang": "hi"})
    assert res_hi.status_code == 200
    home_hi = client.get("/")
    assert 'lang="hi"' in home_hi.get_data(as_text=True)
    client.post("/api/language", json={"lang": "en"})


def test_consent_dedup_separate_scheme_store_and_clear(client):
    pdf_bytes = make_pdf_bytes(
        [
            "Student Name: Kabir Nair. Age: 21 years. Aggregate Percentage: 78.5%. Statement of Marks. "
            "Annual Family Income: Rs. 1,90,000 issued by Tehsildar. Income Certificate."
        ]
    )

    # Upload succeeds directly
    up_resp = client.post(
        "/api/upload",
        data={"files": (io.BytesIO(pdf_bytes), "citizen_bundle.pdf")},
        content_type="multipart/form-data",
    )
    assert up_resp.status_code == 200
    up_json = up_resp.get_json()
    assert up_json["total_chunks"] >= 1
    assert up_json["documents"][0]["filename"] == "citizen_bundle.pdf"
    assert up_json["duplicates"] == []

    # Uploading the exact same content under a "_1" copy is deduplicated
    dup_resp = client.post(
        "/api/upload",
        data={"files": (io.BytesIO(pdf_bytes), "citizen_bundle_1.pdf")},
        content_type="multipart/form-data",
    )
    assert dup_resp.status_code == 200
    dup_json = dup_resp.get_json()
    assert "citizen_bundle_1.pdf" in dup_json["duplicates"]
    assert len(dup_json["documents"]) == 1

    # Uploaded scheme PDF overrides dropdown and is stored separately from citizen_documents
    custom_scheme_pdf = make_pdf_bytes(
        [
            "Custom State Merit Scholarship Guideline. Minimum 70% marks required. "
            "Annual family income must not exceed Rs. 3,00,000. Required Documents: Aadhaar Card, Marksheet."
        ]
    )
    elig_resp = client.post(
        "/api/eligibility",
        data={
            "scheme_id": "nsp_post_matric",
            "language": "en",
            "scheme_file": (io.BytesIO(custom_scheme_pdf), "custom_scheme.pdf"),
        },
        content_type="multipart/form-data",
    )
    assert elig_resp.status_code == 200
    elig_json = elig_resp.get_json()
    assert elig_json["checked_scheme_source"] == "uploaded_pdf"
    assert elig_json["scheme_name"] == "custom_scheme.pdf"
    citizen_names = [d["filename"] for d in elig_json["citizen_documents"]]
    scheme_names = [s["filename"] for s in elig_json["scheme_documents"]]
    assert "custom_scheme.pdf" not in citizen_names
    assert "custom_scheme.pdf" in scheme_names

    # Export checklist as Markdown and PDF
    md_resp = client.post("/api/export/checklist", json={**elig_json, "format": "md"})
    assert md_resp.status_code == 200
    assert b"Eligibility Checklist" in md_resp.data

    pdf_resp = client.post("/api/export/checklist", json={**elig_json, "format": "pdf"})
    assert pdf_resp.status_code == 200
    assert pdf_resp.data.startswith(b"%PDF-")

    # Document page viewer endpoint works
    pg_resp = client.get("/api/document-page?filename=citizen_bundle.pdf&page=1")
    assert pg_resp.status_code == 200
    assert "Kabir Nair" in pg_resp.get_json()["text"]

    # Delete my data now
    clr = client.post("/api/session/clear", json={})
    assert clr.status_code == 200
    assert clr.get_json()["status"] == "cleared"
