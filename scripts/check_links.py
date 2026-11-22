"""Verify that all external URLs in schemes.json and rendered pages return HTTP 200."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


_PRECONNECT_HOSTS = {"https://fonts.googleapis.com", "https://fonts.gstatic.com"}


def collect_external_urls() -> set[str]:
    urls: set[str] = set()
    schemes_path = ROOT / "data" / "schemes" / "schemes.json"
    if schemes_path.exists():
        data = json.loads(schemes_path.read_text(encoding="utf-8"))
        for s in data.get("schemes", []):
            if s.get("official_url"):
                urls.add(s["official_url"])

    app = create_app("testing")
    client = app.test_client()
    for route in ["/", "/find-schemes", "/documents", "/ask", "/schemes", "/privacy", "/help"]:
        html = client.get(route).get_data(as_text=True)
        for m in re.findall(r'href=["\'](https?://[^"\']+)["\']', html):
            if m not in _PRECONNECT_HOSTS:
                urls.add(m)
    return urls


def verify_urls(urls: set[str]) -> list[tuple[str, int | str]]:
    failures: list[tuple[str, int | str]] = []
    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=15.0) as client:
        for url in sorted(urls):
            last_err: int | str = "unknown"
            ok = False
            for _attempt in range(2):
                try:
                    resp = client.get(url)
                    if resp.status_code == 200:
                        print(f"[200 OK] {url}")
                        ok = True
                        break
                    last_err = resp.status_code
                except Exception as exc:
                    last_err = str(exc)
            if not ok:
                failures.append((url, last_err))
    return failures


def main() -> None:
    urls = collect_external_urls()
    print(f"Checking {len(urls)} unique external URLs...")
    failures = verify_urls(urls)
    if failures:
        for u, err in failures:
            print(f"[FAIL] {u} -> {err}")
        sys.exit(1)
    print(f"All {len(urls)} external URLs returned HTTP 200.")


if __name__ == "__main__":
    main()
