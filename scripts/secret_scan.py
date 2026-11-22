"""Scan tracked or staged repository files for accidental API key patterns."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

PATTERNS = [
    ("Google API key", re.compile(r"AIza[0-9A-Za-z_-]{20,}")),
    ("OpenAI/Stripe-style key", re.compile(r"\bsk-[0-9A-Za-z_-]{20,}\b")),
    ("Hugging Face token", re.compile(r"\bhf_[0-9A-Za-z]{20,}\b")),
]

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    files_raw = subprocess.check_output(
        ["git", "ls-files"], cwd=str(ROOT), text=True
    ).splitlines()
    hits: list[str] = []
    for rel in files_raw:
        p = ROOT / rel
        if not p.is_file() or p.suffix.lower() in {".png", ".gif", ".jpg", ".jpeg", ".pdf", ".ico"}:
            continue
        try:
            content = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for label, rx in PATTERNS:
            if rx.search(content):
                hits.append(f"{rel}: matched {label}")
    if hits:
        print("SECRET SCAN FAILED:")
        for h in hits:
            print(" -", h)
        return 1
    print(f"Secret scan clean across {len(files_raw)} tracked files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
