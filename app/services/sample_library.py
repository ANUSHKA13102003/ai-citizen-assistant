"""Loader and search utilities for bundled sample Indian public scheme PDFs."""

from __future__ import annotations

import json
from pathlib import Path


def load_scheme_manifest(samples_dir: Path) -> list[dict]:
    """Load scheme metadata from data/samples/manifest.json."""
    manifest_path = samples_dir / "manifest.json"
    if not manifest_path.exists():
        return []
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        return data.get("schemes", []) if isinstance(data, dict) else []
    except Exception:
        return []


def search_schemes(
    samples_dir: Path,
    query: str = "",
    category: str = "",
) -> list[dict]:
    """Filter bundled scheme PDFs by search query and category."""
    schemes = load_scheme_manifest(samples_dir)
    q = (query or "").strip().lower()
    cat = (category or "").strip().lower()

    results: list[dict] = []
    for item in schemes:
        if cat and cat != "all" and item.get("category", "").lower() != cat:
            continue
        if q:
            haystack = " ".join(
                [
                    item.get("title", ""),
                    item.get("ministry", ""),
                    item.get("category", ""),
                    item.get("summary", ""),
                    " ".join(item.get("tags", [])),
                ]
            ).lower()
            if q not in haystack:
                continue
        pdf_path = samples_dir / item.get("filename", "")
        item_copy = dict(item)
        item_copy["available_on_disk"] = pdf_path.exists()
        results.append(item_copy)
    return results


def get_scheme_by_id(samples_dir: Path, scheme_id: str) -> dict | None:
    """Return a single scheme entry by id."""
    for item in load_scheme_manifest(samples_dir):
        if item.get("id") == scheme_id:
            return item
    return None
