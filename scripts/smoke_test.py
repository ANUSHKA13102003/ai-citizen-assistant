"""Smoke test every page route, healthz, upload, eligibility, and analytics against live WSGI app."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402


def main() -> None:
    app = create_app("development")
    app.config["WTF_CSRF_ENABLED"] = False
    client = app.test_client()

    routes = [
        "/",
        "/workspace",
        "/eligibility",
        "/schemes",
        "/analytics",
        "/evaluation",
        "/about",
        "/privacy",
        "/healthz",
    ]
    for r in routes:
        resp = client.get(r)
        assert resp.status_code == 200, f"Route {r} failed with {resp.status_code}"
        print(f"GET {r} -> {resp.status_code}")

    # Load demo docs & run eligibility
    demo = client.post("/api/load-demo-docs", json={"scheme_id": "nsp_post_matric"})
    assert demo.status_code == 200, demo.data
    print("POST /api/load-demo-docs ->", demo.get_json()["total_chunks"], "chunks")

    elig = client.post(
        "/api/eligibility",
        data={"scheme_id": "nsp_post_matric", "language": "en"},
        content_type="multipart/form-data",
    )
    assert elig.status_code == 200, elig.data
    ej = elig.get_json()
    print("POST /api/eligibility verdict ->", ej["rule_based_verdict"])
    print("Available:", len(ej["available_documents"]), "Missing:", len(ej["missing_documents"]))

    an = client.get("/api/analytics")
    assert an.status_code == 200
    print("GET /api/analytics KPIs ->", json.dumps(an.get_json()["kpis"]))

    clr = client.post("/api/session/clear", json={})
    assert clr.status_code == 200
    print("POST /api/session/clear -> OK")


if __name__ == "__main__":
    main()
