"""Verify official URLs over HTTP and write data/schemes/schemes.json (schemes without a 200 URL are dropped)."""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from schemes_data import SCHEMES  # noqa: E402

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}
OUT = ROOT / "data" / "schemes" / "schemes.json"


def first_ok(client: httpx.Client, urls: list[str]) -> str | None:
    for url in urls:
        try:
            r = client.get(url, follow_redirects=True, timeout=12.0)
            if r.status_code == 200:
                return url
        except Exception:
            continue
    return None


def main() -> None:
    today = date.today().isoformat()
    kept, dropped = [], []
    with httpx.Client(headers=HEADERS, verify=True) as client:
        for s in SCHEMES:
            ok = first_ok(client, s["candidate_urls"])
            if not ok:
                dropped.append(s["slug"])
                print("[DROPPED: no 200 URL]", s["slug"])
                continue
            entry = {k: v for k, v in s.items() if k != "candidate_urls"}
            entry["official_url"] = ok
            entry["last_verified"] = today
            kept.append(entry)
            print("[OK]", s["slug"], "->", ok)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"schemes": kept}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(kept)} schemes; dropped {len(dropped)}: {dropped}")


if __name__ == "__main__":
    main()
