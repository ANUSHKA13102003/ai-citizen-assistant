"""Language detection, query categorization, and bilingual prompt helpers."""

from __future__ import annotations

import re

from langdetect import LangDetectException, detect

FIXED_NOT_FOUND_EN = "The information could not be found in the uploaded documents."
FIXED_NOT_FOUND_HI = (
    "यह जानकारी अपलोड किए गए दस्तावेज़ों में नहीं मिल सकी। "
    "(The information could not be found in the uploaded documents.)"
)

_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")


def detect_language(text: str, override: str | None = None) -> str:
    """Return 'hi' or 'en' based on explicit toggle or query text."""
    if override and override.lower() in {"en", "hi"}:
        return override.lower()
    cleaned = (text or "").strip()
    if not cleaned:
        return "en"
    if _DEVANAGARI_RE.search(cleaned):
        return "hi"
    try:
        lang = detect(cleaned)
        if lang == "hi":
            return "hi"
    except LangDetectException:
        pass
    return "en"


def sanitize_input(text: str, max_length: int = 2000) -> str:
    """Strip control characters and bound user text length safely."""
    if not text:
        return ""
    cleaned = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", " ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:max_length]


def categorize_query(question: str) -> str:
    """Classify a query into a non-PII analytics category using keyword rules."""
    q = (question or "").lower()
    if any(
        w in q
        for w in [
            "scheme",
            "scholarship",
            "eligible",
            "eligibility",
            "missing",
            "available",
            "yojana",
            "pm-kisan",
            "nsp",
            "apply",
            "छात्रवृत्ति",
            "योजना",
            "पात्र",
        ]
    ):
        return "Scholarship / Scheme"
    if any(
        w in q
        for w in [
            "marks",
            "cgpa",
            "sgpa",
            "percentage",
            "grade",
            "degree",
            "college",
            "university",
            "school",
            "10th",
            "12th",
            "b.tech",
            "marksheet",
            "अंक",
            "शिक्षा",
        ]
    ):
        return "Education & Marksheets"
    if any(
        w in q
        for w in [
            "name",
            "dob",
            "birth",
            "address",
            "aadhaar",
            "pan",
            "email",
            "phone",
            "father",
            "mother",
            "income",
            "caste",
            "domicile",
            "नाम",
            "जन्म",
            "आय",
        ]
    ):
        return "Personal & Identity"
    if any(
        w in q
        for w in [
            "skill",
            "project",
            "intern",
            "experience",
            "certificate",
            "certification",
            "award",
            "achievement",
            "कौशल",
            "परियोजना",
        ]
    ):
        return "Skills & Projects"
    if any(w in q for w in ["date", "deadline", "last date", "year", "valid", "expiry", "तिथि"]):
        return "Dates & Deadlines"
    return "General"
