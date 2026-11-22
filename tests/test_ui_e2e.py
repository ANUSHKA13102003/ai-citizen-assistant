"""Playwright E2E test at 1920x1080, 1440x900, and 390x844 across all user journeys."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

from app import create_app

SCREENSHOT_DIR = Path(
    r"C:\Users\Dell\.gemini\antigravity\brain\2cb26488-0e8d-4652-905c-e4c8ae329dd1\scratch\screenshots_final"
)


@pytest.fixture(scope="module")
def live_server_url():
    app = create_app("development")
    server = make_server("127.0.0.1", 7873, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.6)
    try:
        yield "http://127.0.0.1:7873"
    finally:
        server.shutdown()


def test_playwright_full_journeys_and_responsive(live_server_url):
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    console_errors: list[str] = []
    page_errors: list[str] = []
    bad_responses: list[str] = []

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="msedge", headless=True)
        except Exception:
            browser = p.chromium.launch(headless=True)

        context = browser.new_context(
            viewport={"width": 1440, "height": 900}, accept_downloads=True
        )
        page = context.new_page()

        page.on(
            "console",
            lambda msg: console_errors.append(msg.text) if msg.type == "error" else None,
        )
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))
        page.on(
            "response",
            lambda resp: bad_responses.append(f"{resp.status} {resp.url}")
            if resp.status >= 400 and "favicon" not in resp.url
            else None,
        )

        # 1. Visit all public pages at 1440x900
        for name, path in [
            ("home", "/"),
            ("find_schemes", "/find-schemes"),
            ("documents", "/documents"),
            ("ask", "/ask"),
            ("schemes", "/schemes"),
            ("scheme_detail", "/schemes/pm-kisan"),
            ("help", "/help"),
            ("privacy", "/privacy"),
        ]:
            resp = page.goto(f"{live_server_url}{path}", wait_until="domcontentloaded")
            assert resp is not None and resp.status == 200, f"{path} failed"
            overflow = page.evaluate(
                "() => document.documentElement.scrollWidth > document.documentElement.clientWidth"
            )
            assert not overflow, f"1440x900 horizontal overflow on {path}"
            if name in ("home", "find_schemes", "documents", "ask", "schemes", "scheme_detail"):
                page.screenshot(path=str(SCREENSHOT_DIR / f"1440_{name}.png"), full_page=True)

        # 2. 1920x1080 check on Home
        page.set_viewport_size({"width": 1920, "height": 1080})
        page.goto(f"{live_server_url}/", wait_until="domcontentloaded")
        page.screenshot(path=str(SCREENSHOT_DIR / "1920_home.png"), full_page=True)
        page.set_viewport_size({"width": 1440, "height": 900})

        # 3. Accessibility controls + Language toggle EN -> HI -> EN
        page.click(".scale-btn[data-scale='lg']")
        assert page.get_attribute("html", "data-scale") == "lg"
        page.click(".scale-btn[data-scale='md']")
        page.click("#contrastToggleBtn")
        assert page.get_attribute("html", "data-contrast") == "high"
        page.click("#contrastToggleBtn")
        page.click("#themeToggleBtn")
        assert page.get_attribute("html", "data-theme") == "dark"
        page.screenshot(path=str(SCREENSHOT_DIR / "1440_home_dark.png"), full_page=True)
        page.click("#themeToggleBtn")

        page.click("#langToggleBtn")
        page.wait_for_function("() => document.documentElement.lang === 'hi'", timeout=10000)
        assert page.get_attribute("html", "lang") == "hi"
        page.screenshot(path=str(SCREENSHOT_DIR / "1440_home_hi.png"), full_page=True)
        page.click("#langToggleBtn")
        page.wait_for_function("() => document.documentElement.lang === 'en'", timeout=10000)
        assert page.get_attribute("html", "lang") == "en"

        # 4. All Schemes instant filter + clear chip
        page.goto(f"{live_server_url}/schemes", wait_until="domcontentloaded")
        page.fill("#schemeSearchInput", "Kisan")
        assert "clear" in page.locator("#clearSchemeFiltersBtn").inner_text().lower()
        page.click("#clearSchemeFiltersBtn")
        assert page.input_value("#schemeSearchInput") == ""

        # 5. Find Schemes wizard: searchable state + live counter + results + My list + PDF
        page.goto(f"{live_server_url}/find-schemes", wait_until="domcontentloaded")
        page.fill("#stateSearchInput", "Maharashtra")
        assert page.locator(".option-pill").count() >= 1
        page.fill("#stateSearchInput", "")
        for _ in range(10):
            if page.is_visible("#wizardResults"):
                break
            if page.locator(".option-pill").count() > 0:
                page.locator(".option-pill").first.click()
            else:
                break
            page.wait_for_timeout(150)

        page.wait_for_selector("#wizardResults", state="visible", timeout=15000)
        page.locator(".save-list-btn").first.click()
        assert page.locator("#myListCount").inner_text() == "1"
        page.screenshot(path=str(SCREENSHOT_DIR / "1440_results.png"), full_page=True)

        with page.expect_download() as dl_info:
            page.locator(".pdf-checklist-btn").first.click()
        assert dl_info.value.suggested_filename.endswith(".pdf")

        # 6. My Documents: Load sample -> auto-filled Found cards + privacy chip + page viewer
        page.goto(f"{live_server_url}/documents", wait_until="domcontentloaded")
        page.click("#loadDemoDocsBtn")
        page.wait_for_selector("#foundCardsGrid .card-found", timeout=20000)
        assert page.is_visible("#privacyRedactionChip")
        assert page.input_value("#pfMarks") != ""
        assert page.input_value("#pfIncome") != ""
        page.screenshot(path=str(SCREENSHOT_DIR / "1440_documents_found.png"), full_page=True)

        page.locator(".view-doc-btn").first.click()
        page.wait_for_selector("#pageViewerModal.open", timeout=5000)
        page.click("#closePageViewerBtn")

        # 7. Ask Sahayak: send greeting
        page.goto(f"{live_server_url}/ask", wait_until="domcontentloaded")
        page.fill("#askInput", "Namaste")
        page.click("#sendChatBtn")
        page.wait_for_function(
            "() => document.querySelectorAll('#chatMessages .msg-bot').length >= 2",
            timeout=15000,
        )

        # 8. Privacy Clear my data
        page.goto(f"{live_server_url}/privacy", wait_until="domcontentloaded")
        page.click("#privacyClearBtn")
        page.wait_for_timeout(300)

        # 9. Mobile viewport 390x844
        page.set_viewport_size({"width": 390, "height": 844})
        for name, path in [
            ("home", "/"),
            ("find_schemes", "/find-schemes"),
            ("documents", "/documents"),
            ("ask", "/ask"),
        ]:
            page.goto(f"{live_server_url}{path}", wait_until="domcontentloaded")
            overflow_m = page.evaluate(
                "() => document.documentElement.scrollWidth > document.documentElement.clientWidth"
            )
            assert not overflow_m, f"390x844 horizontal overflow on {path}"
            page.screenshot(path=str(SCREENSHOT_DIR / f"390_{name}.png"), full_page=True)

        browser.close()

    assert not console_errors, f"Console errors: {console_errors}"
    assert not page_errors, f"Page errors: {page_errors}"
    assert not bad_responses, f"HTTP errors: {bad_responses}"
