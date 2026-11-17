"""Start app in-process and capture Playwright screenshots under docs/."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402

DOCS_DIR = ROOT / "docs"


def main() -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    app = create_app("development")
    server = make_server("127.0.0.1", 7865, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.8)

    base_url = "http://127.0.0.1:7865"

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True)
            context = browser.new_context(viewport={"width": 1360, "height": 900})
            page = context.new_page()

            # 1. Landing page
            page.goto(f"{base_url}/", wait_until="networkidle")
            page.wait_for_timeout(500)
            page.screenshot(path=str(DOCS_DIR / "screenshot_landing.png"), full_page=False)
            print("Saved docs/screenshot_landing.png")

            # 2. Workspace page (load sample docs)
            page.goto(f"{base_url}/workspace", wait_until="networkidle")
            page.click("#load-demo-btn")
            page.wait_for_function(
                "() => document.querySelector('#chunk-count-badge')?.textContent !== '0 chunks'",
                timeout=20000,
            )
            page.wait_for_timeout(400)
            page.screenshot(path=str(DOCS_DIR / "screenshot_workspace.png"), full_page=False)
            print("Saved docs/screenshot_workspace.png")

            # 3. Eligibility page (run NSP check)
            page.goto(f"{base_url}/eligibility?scheme=nsp_post_matric", wait_until="networkidle")
            page.click("button[type='submit']")
            page.wait_for_selector("#eligibility-results:not(.hidden)", timeout=10000)
            page.wait_for_timeout(3800)  # Let success toast auto-dismiss for a clean screenshot
            page.screenshot(path=str(DOCS_DIR / "screenshot_eligibility.png"), full_page=True)
            print("Saved docs/screenshot_eligibility.png")

            # 4. Analytics page
            page.goto(f"{base_url}/analytics", wait_until="networkidle")
            page.wait_for_timeout(1200)
            page.screenshot(path=str(DOCS_DIR / "screenshot_analytics.png"), full_page=True)
            print("Saved docs/screenshot_analytics.png")

            # 5. Evaluation page
            page.goto(f"{base_url}/evaluation", wait_until="networkidle")
            page.wait_for_timeout(1200)
            page.screenshot(path=str(DOCS_DIR / "screenshot_evaluation.png"), full_page=True)
            print("Saved docs/screenshot_evaluation.png")

            browser.close()
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
