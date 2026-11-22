"""Generate validated bilingual scheme explainers (data/explainers.json) once using Gemini + rules."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
load_dotenv(BASE_DIR / ".env")

from app.config import clean_model_name  # noqa: E402
from app.services.gemini_client import GeminiClient  # noqa: E402
from app.services.sample_library import build_apply_steps, load_scheme_manifest  # noqa: E402


def _deterministic_explainer(scheme: dict) -> dict:
    name = scheme.get("name", "")
    name_hi = scheme.get("name_hi") or name
    benefit = scheme.get("benefit", "")
    benefit_hi = scheme.get("benefit_hi") or benefit
    who = scheme.get("who", "")
    who_hi = scheme.get("who_hi") or who
    url = scheme.get("official_url", "")
    docs = scheme.get("required_documents") or []
    docs_str = ", ".join(docs) if docs else "Aadhaar Card, Bank Passbook"
    steps_en = build_apply_steps(scheme, lang="en")
    steps_hi = build_apply_steps(scheme, lang="hi")

    return {
        "id": scheme["id"],
        "slug": scheme.get("slug") or scheme["id"],
        "official_url": url,
        "summary": f"{name} offers {benefit}",
        "summary_hi": f"{name_hi}: {benefit_hi}",
        "who": who,
        "who_hi": who_hi,
        "steps": steps_en,
        "steps_hi": steps_hi,
        "qas": [
            {
                "q": f"What benefit does {name} provide?",
                "a": benefit,
                "q_hi": f"{name_hi} से क्या लाभ मिलता है?",
                "a_hi": benefit_hi,
            },
            {
                "q": f"Who can apply for {name}?",
                "a": who,
                "q_hi": f"{name_hi} के लिए कौन आवेदन कर सकता है?",
                "a_hi": who_hi,
            },
            {
                "q": f"Which documents are needed for {name}?",
                "a": f"Keep these ready: {docs_str}.",
                "q_hi": f"{name_hi} के लिए कौन-से दस्तावेज़ चाहिए?",
                "a_hi": f"ये दस्तावेज़ तैयार रखें: {docs_str}।",
            },
            {
                "q": f"Where do I apply for {name}?",
                "a": f"Apply only on the official portal ({url}) or an authorised Jan Seva Kendra (CSC).",
                "q_hi": f"{name_hi} के लिए आवेदन कहाँ करें?",
                "a_hi": f"केवल आधिकारिक पोर्टल ({url}) या नज़दीकी जन सेवा केंद्र (CSC) पर आवेदन करें।",
            },
            {
                "q": f"What is the last date to apply for {name}?",
                "a": f"Check the official site ({url}) for current dates and deadlines.",
                "q_hi": f"{name_hi} की अंतिम तारीख क्या है?",
                "a_hi": f"नए आवेदन और अंतिम तारीखें हमेशा आधिकारिक वेबसाइट ({url}) पर देखें।",
            },
        ],
    }


def _validate_urls(obj: dict, official_url: str) -> bool:
    """Reject any AI-generated explainer that introduces an external URL other than official_url."""
    blob = json.dumps(obj, ensure_ascii=False)
    urls = re.findall(r"https?://[^\s\"'<>]+", blob)
    allowed_host = official_url.split("//", 1)[-1].split("/", 1)[0].lower()
    for u in urls:
        host = u.split("//", 1)[-1].split("/", 1)[0].lower()
        if allowed_host not in host and host not in allowed_host:
            return False
    return True


def main() -> None:
    schemes = load_scheme_manifest(
        BASE_DIR / "data" / "samples",
        BASE_DIR / "data" / "schemes" / "schemes.json",
    )
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    gemini = GeminiClient(api_key=api_key, model=clean_model_name(os.getenv("GEMINI_MODEL"))) if api_key else None

    explainers: dict[str, dict] = {}
    enriched = 0
    for idx, s in enumerate(schemes, 1):
        base = _deterministic_explainer(s)
        if gemini and gemini.is_configured:
            prompt = (
                f"Scheme: {s['name']} ({s['name_hi']})\n"
                f"Benefit: {s['benefit']}\n"
                f"Who can apply: {s['who']}\n"
                f"Required docs: {s.get('required_documents', [])}\n"
                f"Official URL: {s['official_url']}\n\n"
                "Return JSON with keys summary, summary_hi (max 25 words each, plain Class 8 language, "
                "using ONLY the numbers and official URL above, never inventing dates or deadlines)."
            )
            try:
                raw = gemini.generate(
                    system_prompt="You write clear, accurate citizen scheme summaries in English and Hindi JSON.",
                    user_prompt=prompt,
                    temperature=0.1,
                    response_mime_type="application/json",
                )
                cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.DOTALL)
                parsed = json.loads(cleaned)
                if (
                    isinstance(parsed, dict)
                    and parsed.get("summary")
                    and parsed.get("summary_hi")
                    and _validate_urls(parsed, s["official_url"])
                ):
                    base["summary"] = str(parsed["summary"]).strip()
                    base["summary_hi"] = str(parsed["summary_hi"]).strip()
                    enriched += 1
            except Exception as exc:
                print(f"[{idx}/{len(schemes)}] {s['id']} -> deterministic fallback ({type(exc).__name__})")
            time.sleep(0.8)
        explainers[s["id"]] = base
        print(f"[{idx}/{len(schemes)}] {s['id']} OK")

    out_path = BASE_DIR / "data" / "explainers.json"
    out_path.write_text(
        json.dumps({"explainers": explainers, "count": len(explainers)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {len(explainers)} explainers ({enriched} AI-enriched) -> {out_path}")


if __name__ == "__main__":
    main()
