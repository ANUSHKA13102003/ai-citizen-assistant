"""Loader and search utilities for curated Indian public schemes and fallback manifest."""

from __future__ import annotations

import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_SCHEMES_PATH = BASE_DIR / "data" / "schemes" / "schemes.json"


def _normalize_scheme(item: dict, samples_dir: Path | None = None) -> dict:
    s = dict(item)
    s.setdefault("name", s.get("title", ""))
    s.setdefault("title", s.get("name", ""))
    s.setdefault("name_hi", s.get("name", ""))
    s.setdefault("slug", s.get("id", ""))
    s.setdefault("official_url", s.get("source_url", ""))
    s.setdefault("source_url", s.get("official_url", ""))
    s.setdefault("benefit", s.get("summary", ""))
    s.setdefault("benefit_hi", s.get("benefit", ""))
    s.setdefault("who", "")
    s.setdefault("who_hi", s.get("who", ""))
    s.setdefault("level", "central")
    s.setdefault("required_documents", [])
    s.setdefault("apply", {})
    s.setdefault("how_to_apply", "Apply online through the official government portal.")
    s.setdefault("last_verified", "2026-11-19")
    if samples_dir and s.get("filename"):
        s["available_on_disk"] = (samples_dir / s["filename"]).exists()
    else:
        s["available_on_disk"] = False
    return s


def build_apply_steps(scheme: dict, lang: str = "en") -> list[str]:
    """Generate 3-5 numbered plain-language steps from apply.mode and portal."""
    apply_info = scheme.get("apply") or {}
    mode = (apply_info.get("mode") or "online").lower()
    portal = apply_info.get("portal") or scheme.get("official_url", "")
    note = apply_info.get("note_hi" if lang == "hi" else "note") or ""
    if lang == "hi":
        if mode == "bank":
            steps = [
                "ऊपर दिए गए सभी ज़रूरी दस्तावेज़ इकट्ठा करें।",
                f"नज़दीकी बैंक शाखा या जन सेवा केंद्र (CSC) जाएँ, या {portal} पर ऑनलाइन आवेदन करें।",
                "आवेदन फ़ॉर्म भरें और दस्तावेज़ों की कॉपी जमा करें (बैंक/CSC से रसीद ज़रूर लें)।",
                "स्वीकृति के बाद लाभ या ऋण सीधे आपके बैंक खाते में आएगा।",
            ]
        elif mode == "csc":
            steps = [
                "ऊपर दिए गए दस्तावेज़ मूल और फ़ोटोकॉपी के साथ तैयार रखें।",
                f"नज़दीकी जन सेवा केंद्र (CSC) जाएँ या {portal} पोर्टल खोलें।",
                "फ़ॉर्म भरकर दस्तावेज़ अपलोड करें और आवेदन रसीद संभाल कर रखें।",
                "आवेदन संख्या से समय-समय पर स्थिति जाँचते रहें।",
            ]
        elif mode == "school":
            steps = [
                "अपने स्कूल या कॉलेज की छात्रवृत्ति डेस्क से बात करें और दस्तावेज़ तैयार रखें।",
                f"{portal} पोर्टल पर छात्र पंजीकरण कर ऑनलाइन फ़ॉर्म भरें।",
                "दस्तावेज़ अपलोड करके प्रिंट-आउट अपने संस्थान में सत्यापन के लिए जमा करें।",
                "सत्यापन के बाद छात्रवृत्ति सीधे आधार-लिंक्ड बैंक खाते में आएगी।",
            ]
        elif mode == "hospital":
            steps = [
                "सरकारी या सूचीबद्ध (empanelled) निजी अस्पताल के आयुष्मान/योजना मित्र डेस्क पर जाएँ।",
                "अपना पहचान पत्र और राशन कार्ड/पात्रता कार्ड दिखाकर सत्यापन कराएँ।",
                "पात्र पाए जाने पर बिना नकद (कैशलेस) इलाज शुरू किया जाएगा।",
            ]
        elif mode in {"office", "ration_office"}:
            steps = [
                "आवश्यक दस्तावेज़ों की फ़ोटोकॉपी और पासपोर्ट फ़ोटो तैयार रखें।",
                f"नज़दीकी सरकारी/तहसील/ब्लॉक कार्यालय या जन सेवा केंद्र जाएँ ({portal} पर जानकारी देखें)।",
                "आवेदन जमा करें और रसीद नंबर प्राप्त करें।",
            ]
        else:
            steps = [
                "ऊपर दिए गए सभी दस्तावेज़ स्कैन या साफ़ फ़ोटो के रूप में तैयार रखें।",
                f"आधिकारिक वेबसाइट ({portal}) खोलें और नया पंजीकरण (Register) करें।",
                "अपनी जानकारी और दस्तावेज़ अपलोड कर फ़ॉर्म सबमिट करें।",
                "आवेदन रसीद डाउनलोड करें और उसी पोर्टल पर स्टेटस ट्रैक करें।",
            ]
        if note:
            steps.append(f"विशेष ध्यान: {note}")
        return steps

    if mode == "bank":
        steps = [
            "Keep the required documents listed above ready.",
            f"Visit your nearest bank branch or Common Service Centre (CSC), or apply online via {portal}.",
            "Submit the application form with copies of your documents and collect the acknowledgement receipt.",
            "Once approved, the loan or subsidy is credited to your bank account.",
        ]
    elif mode == "csc":
        steps = [
            "Keep originals and copies of all required documents ready.",
            f"Visit your nearest Common Service Centre (CSC / Jan Seva Kendra) or open {portal}.",
            "Fill in the application, upload your documents, and save the acknowledgement receipt.",
            "Track your application status online using your application number.",
        ]
    elif mode == "school":
        steps = [
            "Check with your school or college scholarship desk and gather the required documents.",
            f"Register on {portal} and complete the online scholarship form.",
            "Upload documents and submit a printed copy to your institution for verification.",
            "After verification, the scholarship is sent directly to your bank account.",
        ]
    elif mode == "hospital":
        steps = [
            "Visit the help desk at any government or empanelled private hospital.",
            "Show your ID and ration card / family card for quick eligibility verification.",
            "Once verified, cashless treatment is covered up to the scheme limit.",
        ]
    elif mode in {"office", "ration_office"}:
        steps = [
            "Collect photocopies of the required documents and passport-size photos.",
            f"Visit your local block, tehsil, or district office or CSC (check details on {portal}).",
            "Submit the form and keep your receipt number to track approval.",
        ]
    else:
        steps = [
            "Keep clear scans or PDFs of the required documents ready.",
            f"Open the official website ({portal}) and register with your mobile number.",
            "Fill in the form, upload the documents, and submit.",
            "Save the application receipt and track your status on the official portal.",
        ]
    if note:
        steps.append(f"Note: {note}")
    return steps


def load_scheme_manifest(
    samples_dir: Path | None = None,
    schemes_path: Path | None = None,
) -> list[dict]:
    """Load curated schemes from data/schemes/schemes.json, falling back to data/samples/manifest.json."""
    curated = schemes_path or DEFAULT_SCHEMES_PATH
    if curated.exists():
        try:
            data = json.loads(curated.read_text(encoding="utf-8"))
            items = data.get("schemes", []) if isinstance(data, dict) else []
            if items:
                return [_normalize_scheme(x, samples_dir) for x in items]
        except Exception:
            pass

    if samples_dir:
        manifest_path = Path(samples_dir) / "manifest.json"
        if manifest_path.exists():
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                items = data.get("schemes", []) if isinstance(data, dict) else []
                return [_normalize_scheme(x, Path(samples_dir)) for x in items]
            except Exception:
                return []
    return []


def search_schemes(
    samples_dir: Path | None = None,
    query: str = "",
    category: str = "",
    level: str = "",
    schemes_path: Path | None = None,
) -> list[dict]:
    """Filter schemes by search query, category, and level (central / uttar_pradesh)."""
    schemes = load_scheme_manifest(samples_dir, schemes_path=schemes_path)
    q = (query or "").strip().lower()
    cat = (category or "").strip().lower()
    lvl = (level or "").strip().lower()

    results: list[dict] = []
    for item in schemes:
        if cat and cat != "all" and item.get("category", "").lower() != cat:
            continue
        if lvl and lvl != "all" and item.get("level", "").lower() != lvl:
            continue
        if q:
            haystack = " ".join(
                [
                    item.get("name", ""),
                    item.get("name_hi", ""),
                    item.get("title", ""),
                    item.get("ministry", ""),
                    item.get("category", ""),
                    item.get("who", ""),
                    item.get("who_hi", ""),
                    item.get("benefit", ""),
                    item.get("benefit_hi", ""),
                    item.get("summary", ""),
                    " ".join(item.get("tags", [])),
                ]
            ).lower()
            if q not in haystack:
                continue
        results.append(item)
    return results


def get_scheme_by_id(
    samples_dir: Path | None,
    scheme_id: str,
    schemes_path: Path | None = None,
) -> dict | None:
    for item in load_scheme_manifest(samples_dir, schemes_path=schemes_path):
        if item.get("id") == scheme_id or item.get("slug") == scheme_id:
            return item
    return None


def get_scheme_by_slug(
    slug: str,
    samples_dir: Path | None = None,
    schemes_path: Path | None = None,
) -> dict | None:
    for item in load_scheme_manifest(samples_dir, schemes_path=schemes_path):
        if item.get("slug") == slug or item.get("id") == slug:
            return item
    return None
