"""Zero-API verified-data chat fallback + 24h non-personal LRU answer cache."""

from __future__ import annotations

import json
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from rank_bm25 import BM25Okapi

from app.services.i18n import load_locale
from app.services.language_service import FIXED_NOT_FOUND_EN, FIXED_NOT_FOUND_HI, detect_language

EXPLAINERS_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "explainers.json"

_CACHE_LOCK = threading.Lock()
_ANSWER_CACHE: OrderedDict[tuple[str, str], tuple[float, dict]] = OrderedDict()
_CACHE_MAX = 256
_CACHE_TTL_SEC = 24 * 3600


def _norm_q(question: str) -> str:
    return re.sub(r"\s+", " ", (question or "").strip().lower())


def get_cached_answer(question: str, lang: str) -> dict | None:
    key = (_norm_q(question), lang)
    now = time.time()
    with _CACHE_LOCK:
        entry = _ANSWER_CACHE.get(key)
        if not entry:
            return None
        ts, payload = entry
        if now - ts > _CACHE_TTL_SEC:
            _ANSWER_CACHE.pop(key, None)
            return None
        _ANSWER_CACHE.move_to_end(key)
        return dict(payload)


def put_cached_answer(question: str, lang: str, payload: dict) -> None:
    key = (_norm_q(question), lang)
    with _CACHE_LOCK:
        _ANSWER_CACHE[key] = (time.time(), dict(payload))
        _ANSWER_CACHE.move_to_end(key)
        while len(_ANSWER_CACHE) > _CACHE_MAX:
            _ANSWER_CACHE.popitem(last=False)


@lru_cache(maxsize=2)
def load_explainers(path: Path | None = None) -> dict[str, dict]:
    p = path or EXPLAINERS_PATH
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data.get("explainers", {}) if isinstance(data, dict) else {}
    except Exception:
        return {}


def _tokens(text: str) -> list[str]:
    return re.sub(r"[?.,!।\-/()\"']", " ", (text or "").lower()).split()


@dataclass
class VerifiedChatResult:
    answer: str
    scheme_cards: list[dict] = field(default_factory=list)
    followups: list[str] = field(default_factory=list)
    intent: str = "scheme_question"
    is_not_found: bool = False


def answer_from_verified_data(
    question: str,
    schemes: list[dict],
    session_state=None,
    language_override: str | None = None,
) -> VerifiedChatResult:
    """Answer citizen queries from schemes.json, explainers.json, FAQs, and extracted doc facts."""
    lang = detect_language(question, language_override)
    q_low = (question or "").lower()
    explainers = load_explainers()

    # 1. Privacy / fraud safety quick answer
    if any(w in q_low for w in ("aadhaar", "otp", "agent", "middleman", "dalal", "दलाल", "आधार", "फ़ोन", "privacy")):
        msg = (
            "यह जानकारी हमारे सत्यापित योजना डेटा से दिखाई जा रही है।\n\n"
            "• हम कभी भी आपका आधार, पैन या बैंक खाता नंबर नहीं माँगते।\n"
            "• मुफ़्त सरकारी फ़ॉर्म के लिए किसी एजेंट को पैसे न दें और कभी भी OTP साझा न करें।\n"
            "• हमेशा आधिकारिक .gov.in वेबसाइट या अधिकृत जन सेवा केंद्र (CSC) से ही आवेदन करें।"
            if lang == "hi"
            else "Showing answers from our verified scheme data.\n\n"
            "• We never ask for your Aadhaar, PAN, or bank account number, and personal IDs are hidden automatically.\n"
            "• Never pay an agent for a free government form and never share your OTP.\n"
            "• Always apply on the official .gov.in website or at an authorised Jan Seva Kendra (CSC)."
        )
        return VerifiedChatResult(answer=msg, intent="scheme_question")

    # 2. Personal document summary / profile check from extracted facts (no AI needed)
    if session_state is not None and any(
        w in q_low for w in ("marks", "percentage", "income", "my document", "summarize", "अंक", "आय", "दस्तावेज़ों का सारांश")
    ):
        fields = (session_state.get_profile() or {}).get("fields", {})
        if fields:
            lines = [
                "यह जानकारी हमारे सत्यापित डेटा और आपके पढ़े गए दस्तावेज़ों से दिखाई जा रही है:\n"
                if lang == "hi"
                else "Showing answers from our verified data and your scanned documents:\n"
            ]
            for f in fields.values():
                lines.append(f"• **{f.get('label', '')}:** {f.get('display', f.get('value', ''))} ({f.get('filename', '')})")
            return VerifiedChatResult(answer="\n".join(lines), intent="document_qa")

    # 3. Search schemes + explainers via BM25
    corpus_docs: list[tuple[dict, str]] = []
    for s in schemes:
        exp = explainers.get(s.get("id", ""), {})
        blob = " ".join(
            [
                s.get("id", ""),
                s.get("slug", ""),
                s.get("name", ""),
                s.get("name_hi", ""),
                s.get("category", ""),
                s.get("who", ""),
                s.get("who_hi", ""),
                s.get("benefit", ""),
                s.get("benefit_hi", ""),
                exp.get("summary", ""),
                exp.get("summary_hi", ""),
                " ".join(s.get("tags", [])),
            ]
        )
        corpus_docs.append((s, blob))

    q_toks = _tokens(question)
    matched: list[dict] = []
    if corpus_docs and q_toks:
        bm25 = BM25Okapi([_tokens(b) for _, b in corpus_docs])
        scores = bm25.get_scores(q_toks)
        ranked = sorted(zip(scores, [s for s, _ in corpus_docs], strict=True), key=lambda x: x[0], reverse=True)
        matched = [s for sc, s in ranked[:3] if sc > 0.2]

    if matched:
        top = matched[0]
        exp = explainers.get(top.get("id", ""), {})
        name = top.get("name_hi") if lang == "hi" else top.get("name")
        benefit = top.get("benefit_hi") if lang == "hi" else top.get("benefit")
        who = (exp.get("who_hi") if lang == "hi" else exp.get("who")) or (top.get("who_hi") if lang == "hi" else top.get("who"))
        docs = ", ".join(top.get("required_documents") or [])
        url = top.get("official_url", "")

        cards = [
            {
                "id": s.get("id"),
                "slug": s.get("slug") or s.get("id"),
                "name": s.get("name_hi") if lang == "hi" else s.get("name"),
                "benefit": s.get("benefit_hi") if lang == "hi" else s.get("benefit"),
                "category": s.get("category", ""),
                "official_url": s.get("official_url", ""),
                "last_verified": s.get("last_verified", ""),
            }
            for s in matched
        ]

        if lang == "hi":
            answer = (
                "यह जानकारी हमारे सत्यापित योजना डेटा से दिखाई जा रही है।\n\n"
                f"**{name}**\n"
                f"• **लाभ:** {benefit}\n"
                f"• **कौन आवेदन कर सकता है:** {who}\n"
                f"• **ज़रूरी दस्तावेज़:** {docs}\n"
                f"• **आधिकारिक वेबसाइट:** {url}"
            )
        else:
            answer = (
                "Showing answers from our verified scheme data.\n\n"
                f"**{name}**\n"
                f"• **Benefit:** {benefit}\n"
                f"• **Who can apply:** {who}\n"
                f"• **Documents needed:** {docs}\n"
                f"• **Official portal:** {url}"
            )
        return VerifiedChatResult(answer=answer, scheme_cards=cards, intent="scheme_question")

    # 4. Check FAQs
    locale = load_locale(lang)
    for faq in locale.get("home", {}).get("faq", []):
        if any(tok in faq.get("q", "").lower() for tok in q_toks if len(tok) > 3):
            prefix = "यह जानकारी हमारे सत्यापित योजना डेटा से दिखाई जा रही है।\n\n" if lang == "hi" else "Showing answers from our verified scheme data.\n\n"
            return VerifiedChatResult(answer=f"{prefix}**{faq['q']}**\n{faq['a']}", intent="scheme_question")

    # 5. Personal doc question with no match
    if session_state is not None and not getattr(session_state, "documents", None):
        guide = (
            "यह जानकारी हमारे सत्यापित योजना डेटा से दिखाई जा रही है। आप 'योजना खोजें' में कुछ आसान सवालों के जवाब देकर अपनी पात्र योजनाएँ देख सकते हैं, या 'सभी योजनाएँ' देख सकते हैं।"
            if lang == "hi"
            else "Showing answers from our verified scheme data. Try Find Schemes to answer a few quick questions and see schemes matched to you, or browse All Schemes."
        )
        return VerifiedChatResult(answer=guide, intent="scheme_question")

    return VerifiedChatResult(
        answer=FIXED_NOT_FOUND_HI if lang == "hi" else FIXED_NOT_FOUND_EN,
        intent="document_qa",
        is_not_found=True,
    )
