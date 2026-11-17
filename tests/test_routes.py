"""Integration tests for Flask pages, healthz, consent, upload, eligibility, and export APIs."""

from __future__ import annotations

import io

from tests.conftest import make_pdf_bytes


def test_all_pages_and_healthz(client):
    for route in ["/", "/workspace", "/eligibility", "/schemes", "/analytics", "/evaluation", "/about", "/privacy"]:
        resp = client.get(route)
        assert resp.status_code == 200, f"Route {route} returned {resp.status_code}"

    hz = client.get("/healthz")
    assert hz.status_code == 200
    assert hz.get_json()["status"] == "ok"


def test_consent_upload_eligibility_export_and_clear(client):
    pdf_bytes = make_pdf_bytes(
        [
            "Student Name: Kabir Nair. Age: 21 years. Aggregate Percentage: 78.5%. Marksheet. "
            "Annual Family Income: Rs. 1,90,000 issued by Tehsildar. Income Certificate."
        ]
    )

    # Upload blocked without consent
    blocked = client.post(
        "/api/upload",
        data={"files": (io.BytesIO(pdf_bytes), "citizen_bundle.pdf")},
        content_type="multipart/form-data",
    )
    assert blocked.status_code == 400

    # Accept consent
    c_resp = client.post("/api/consent", json={"accepted": True})
    assert c_resp.status_code == 200

    # Upload succeeds
    up_resp = client.post(
        "/api/upload",
        data={"files": (io.BytesIO(pdf_bytes), "citizen_bundle.pdf")},
        content_type="multipart/form-data",
    )
    assert up_resp.status_code == 200
    up_json = up_resp.get_json()
    assert up_json["total_chunks"] >= 1
    assert up_json["documents"][0]["filename"] == "citizen_bundle.pdf"

    # Eligibility check against bundled scheme
    elig_resp = client.post(
        "/api/eligibility",
        data={"scheme_id": "nsp_post_matric", "language": "en"},
        content_type="multipart/form-data",
    )
    assert elig_resp.status_code == 200
    elig_json = elig_resp.get_json()
    assert "rule_based_verdict" in elig_json
    assert len(elig_json["available_documents"]) >= 1

    # Export checklist as Markdown and PDF
    md_resp = client.post("/api/export/checklist", json={**elig_json, "format": "md"})
    assert md_resp.status_code == 200
    assert b"Eligibility Checklist" in md_resp.data

    pdf_resp = client.post("/api/export/checklist", json={**elig_json, "format": "pdf"})
    assert pdf_resp.status_code == 200
    assert pdf_resp.data.startswith(b"%PDF-")

    # Analytics reflects session & query
    an_resp = client.get("/api/analytics")
    assert an_resp.status_code == 200
    assert an_resp.get_json()["kpis"]["total_sessions"] >= 1

    # Delete my data now
    clr = client.post("/api/session/clear", json={})
    assert clr.status_code == 200
    assert clr.get_json()["status"] == "cleared"
