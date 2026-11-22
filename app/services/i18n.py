"""Lightweight bilingual (English / Hindi) i18n loader for templates and JS."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

I18N_DIR = Path(__file__).resolve().parent.parent / "i18n"
SUPPORTED_LANGUAGES = ("en", "hi")


@lru_cache(maxsize=4)
def load_locale(lang: str) -> dict:
    code = lang if lang in SUPPORTED_LANGUAGES else "en"
    path = I18N_DIR / f"{code}.json"
    if not path.exists():
        path = I18N_DIR / "en.json"
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_lang(raw: str | None) -> str:
    val = (raw or "").strip().lower()
    if val in {"hi", "hindi", "हिन्दी", "हिंदी"}:
        return "hi"
    return "en"


def translate(lang: str, key: str, default: str = "") -> str:
    data = load_locale(lang)
    cur: object = data
    for part in key.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return default or key
    return cur if isinstance(cur, str) else (default or key)
