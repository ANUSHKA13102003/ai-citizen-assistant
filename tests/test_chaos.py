"""Chaos tests: verify zero errors reach visitors when Gemini key is unset, invalid, 429, 503, or timed out."""

from __future__ import annotations

import threading
import time

import pytest
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

from app import create_app
from app.services.gemini_client import GeminiClient, GeminiUnavailableError

FORBIDDEN = [
    "429",
    "503",
    "401",
    "403",
    "quota",
    "api key",
    "generativelanguage.googleapis",
    "traceback",
]


def _assert_clean_text(blob: str, context: str) -> None:
    low = (blob or "").lower()
    for term in FORBIDDEN:
        assert term not in low, f"Forbidden term '{term}' leaked in {context}: {blob[:200]}"
    assert "NOT_FOUND" not in (blob or ""), f"Forbidden 'NOT_FOUND' leaked in {context}"
    assert '"model"' not in low and " model " not in low, f"Forbidden 'model' in {context}"


def test_chaos_unset_key_and_admin_status(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    app = create_app("testing")
    app.config["GEMINI_API_KEY"] = ""
    app.config["ADMIN_KEY"] = "test-admin-secret"
    client = app.test_client()

    for route in ["/", "/find-schemes", "/documents", "/ask", "/schemes", "/schemes/pm-kisan", "/help", "/privacy"]:
        r = client.get(route)
        assert r.status_code == 200
        _assert_clean_text(r.get_data(as_text=True), route)

    # Chat in English & Hindi works from verified data
    r_en = client.post("/api/chat", json={"question": "What documents do I need for PM-KISAN?"})
    assert r_en.status_code == 200
    d_en = r_en.get_json()
    assert d_en["ok"] is True
    assert d_en["mode"] == "verified_data"
    _assert_clean_text(r_en.get_data(as_text=True), "/api/chat EN")

    r_hi = client.post("/api/chat", json={"question": "पीएम किसान योजना के लिए कौन-से दस्तावेज़ चाहिए?"})
    assert r_hi.status_code == 200
    _assert_clean_text(r_hi.get_data(as_text=True), "/api/chat HI")

    # SSE stream works cleanly
    r_sse = client.post("/api/chat/stream", json={"question": "Tell me about Ayushman Bharat"})
    assert r_sse.status_code == 200
    _assert_clean_text(r_sse.get_data(as_text=True), "/api/chat/stream")

    # Load demo docs + analyze + scheme match work without Gemini
    assert client.post("/api/load-demo-docs", json={}).status_code == 200
    r_an = client.post("/api/analyze", json={"language": "en"})
    assert r_an.status_code == 200
    _assert_clean_text(r_an.get_data(as_text=True), "/api/analyze")

    r_match = client.post("/api/scheme-match", json={"answers": {"state": "Uttar Pradesh", "age": 20}})
    assert r_match.status_code == 200
    _assert_clean_text(r_match.get_data(as_text=True), "/api/scheme-match")

    # /admin/status gated by ADMIN_KEY
    assert client.get("/admin/status").status_code == 404
    st = client.get("/admin/status?key=test-admin-secret")
    assert st.status_code == 200
    st_json = st.get_json()
    assert st_json["key_health"] == "missing"
    assert st_json["mode"] == "verified_data"


@pytest.mark.parametrize("sim_err", ["401 invalid", "403 forbidden", "429 quota", "503 unavailable", "timeout"])
def test_chaos_simulated_provider_failures(monkeypatch, sim_err):
    app = create_app("testing")
    app.config["GEMINI_API_KEY"] = "fake-key-for-chaos"
    client = app.test_client()

    def _boom(*_args, **_kwargs):
        raise GeminiUnavailableError(f"Simulated {sim_err}")

    monkeypatch.setattr(GeminiClient, "generate", _boom)
    monkeypatch.setattr(GeminiClient, "generate_stream", _boom)

    r_chat = client.post("/api/chat", json={"question": f"PM-KISAN documents ({sim_err})"})
    assert r_chat.status_code == 200
    assert r_chat.get_json()["mode"] == "verified_data"
    _assert_clean_text(r_chat.get_data(as_text=True), f"chat {sim_err}")

    r_stream = client.post("/api/chat/stream", json={"question": "Ayushman Bharat benefit"})
    assert r_stream.status_code == 200
    _assert_clean_text(r_stream.get_data(as_text=True), f"stream {sim_err}")


def test_chaos_playwright_no_key_journey(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    app = create_app("testing")
    app.config["GEMINI_API_KEY"] = ""
    server = make_server("127.0.0.1", 7875, app, threaded=True)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    time.sleep(0.5)

    console_errors: list[str] = []
    bad_responses: list[str] = []
    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(channel="msedge", headless=True)
            except Exception:
                browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
            page.on(
                "response",
                lambda r: bad_responses.append(f"{r.status} {r.url}")
                if r.status >= 400 and "favicon" not in r.url
                else None,
            )

            page.goto("http://127.0.0.1:7875/ask", wait_until="domcontentloaded")
            page.fill("#askInput", "What documents do I need for PM-KISAN?")
            page.click("#sendChatBtn")
            page.wait_for_function(
                "() => document.querySelectorAll('#chatMessages .msg-bot').length >= 2",
                timeout=10000,
            )
            bot_txt = page.locator("#chatMessages .msg-bot").last.inner_text()
            _assert_clean_text(bot_txt, "Playwright Ask Sahayak no-key")
            assert "verified scheme data" in bot_txt.lower()
            browser.close()
    finally:
        server.shutdown()

    assert not console_errors
    assert not bad_responses
