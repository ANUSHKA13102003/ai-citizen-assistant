"""Redact sensitive personal identifiers before sending text to external LLMs."""

from __future__ import annotations

import re
from dataclasses import dataclass

# 12-digit Aadhaar-like numbers (4-4-4 or 12 consecutive digits), not part of a longer number
_AADHAAR_RE = re.compile(r"(?<!\d)(?:\d{4}[\s-]\d{4}[\s-]\d{4}|\d{12})(?!\d)")

# Indian PAN: 5 letters + 4 digits + 1 letter
_PAN_RE = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b", re.IGNORECASE)

# Email addresses
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

# Indian mobile / phone numbers (+91 / 0 prefix optional, 10 digits starting 6-9)
_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+91[\s-]?|91[\s-]?|0)?[6-9]\d{4}[\s-]?\d{5}(?!\d)"
)

# Bank account numbers near bank/account cues (9 to 18 digits) or standalone 11, 13-18 digit sequences
_BANK_CONTEXT_RE = re.compile(
    r"(?i)(\b(?:account|acct|a/c|bank\s*(?:no|number)?|ifsc\s*code?|passbook)\b[^0-9\n]{0,20})(\d{9,18})\b"
)
_LONG_ACCT_RE = re.compile(r"(?<!\d)(?:\d{11}|\d{13,18})(?!\d)")


@dataclass(frozen=True)
class RedactionResult:
    text: str
    redacted_counts: dict[str, int]

    @property
    def total_redacted(self) -> int:
        return sum(self.redacted_counts.values())


def redact_pii(text: str) -> RedactionResult:
    """Replace Aadhaar-like numbers, PAN, bank account numbers, phones, and emails."""
    if not text:
        return RedactionResult(text="", redacted_counts={})

    counts: dict[str, int] = {}

    def _sub(pattern: re.Pattern[str], label: str, repl: str, value: str) -> str:
        n = 0

        def _cb(match: re.Match[str]) -> str:
            nonlocal n
            n += 1
            return repl

        out = pattern.sub(_cb, value)
        if n:
            counts[label] = counts.get(label, 0) + n
        return out

    cleaned = _sub(_EMAIL_RE, "email", "[REDACTED_EMAIL]", text)
    cleaned = _sub(_PAN_RE, "pan", "[REDACTED_PAN]", cleaned)

    # Context-aware bank account redaction preserves the label prefix
    bank_hits = 0

    def _bank_cb(match: re.Match[str]) -> str:
        nonlocal bank_hits
        bank_hits += 1
        return f"{match.group(1)}[REDACTED_ACCOUNT]"

    cleaned = _BANK_CONTEXT_RE.sub(_bank_cb, cleaned)
    if bank_hits:
        counts["bank_account"] = counts.get("bank_account", 0) + bank_hits

    cleaned = _sub(_AADHAAR_RE, "aadhaar", "[REDACTED_ID]", cleaned)
    cleaned = _sub(_LONG_ACCT_RE, "bank_account", "[REDACTED_ACCOUNT]", cleaned)
    cleaned = _sub(_PHONE_RE, "phone", "[REDACTED_PHONE]", cleaned)

    return RedactionResult(text=cleaned, redacted_counts=counts)


def redact_text(text: str) -> str:
    """Convenience helper returning only the redacted string."""
    return redact_pii(text).text
