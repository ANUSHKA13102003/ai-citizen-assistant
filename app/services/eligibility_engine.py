"""Deterministic Python eligibility rules engine separated from AI explanation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.gemini_client import GeminiClient, GeminiUnavailableError

DOCUMENT_ALIASES: dict[str, list[str]] = {
    "Aadhaar Card": ["aadhaar", "aadhar", "uidai", "unique identification"],
    "Income Certificate": ["income certificate", "annual family income", "tehsildar", "income proof"],
    "Caste / Category Certificate": [
        "caste / category certificate",
        "caste certificate",
        "category certificate",
        "sc certificate",
        "st certificate",
        "obc certificate",
        "ews certificate",
        "community certificate",
    ],
    "Domicile / Residence Certificate": ["domicile", "residence certificate", "nativity certificate"],
    "Academic Marksheet / Transcript": ["marksheet", "mark sheet", "marks statement", "grade card", "transcript", "cgpa", "percentage", "10th", "12th", "semester"],
    "Bank Passbook / Account Details": ["bank passbook", "ifsc", "bank account", "cancelled cheque", "aadhaar seeded"],
    "Bonafide / Admission Proof": ["bonafide", "enrollment", "admission letter", "student id", "institutional verification"],
    "Fee Receipt": ["fee receipt", "tuition fee", "payment receipt"],
    "Land Ownership / Khatauni Record": ["land ownership", "khatauni", "khasra", "jamabandi", "ror", "agricultural land", "cultivable land"],
    "PAN Card": ["pan card", "permanent account number"],
    "Passport Size Photograph": ["photograph", "passport size photo", "passport photo"],
    "Disability Certificate (UDID)": ["disability certificate", "udid", "pwbd", "divyang"],
}


@dataclass
class CitizenFacts:
    marks_percentage: float | None = None
    cgpa: float | None = None
    annual_income_inr: float | None = None
    age_years: int | None = None
    category: str | None = None
    documents_detected: dict[str, str] = field(default_factory=dict)  # doc_type -> supporting filename


@dataclass
class SchemeRequirements:
    scheme_name: str
    min_marks_percentage: float | None = None
    max_income_inr: float | None = None
    min_age: int | None = None
    max_age: int | None = None
    allowed_categories: list[str] = field(default_factory=list)
    required_documents: list[str] = field(default_factory=list)


@dataclass
class CriterionCheck:
    criterion: str
    required: str
    citizen_value: str
    status: str  # PASS | FAIL | UNKNOWN


def _parse_indian_currency_to_inr(num_str: str, unit: str | None) -> float | None:
    cleaned = num_str.replace(",", "").strip()
    try:
        val = float(cleaned)
    except ValueError:
        return None
    u = (unit or "").lower().strip()
    if u in {"lakh", "lakhs", "lac", "lacs"}:
        return val * 100_000.0
    if u in {"crore", "crores", "cr"}:
        return val * 10_000_000.0
    return val


def extract_citizen_facts(texts_by_file: dict[str, str]) -> CitizenFacts:
    """Extract numeric marks, income, age, category, and available documents with regex."""
    facts = CitizenFacts()
    combined_text = "\n".join(texts_by_file.values())

    # Marks percentage (prefer explicit percentage/aggregate/total marks%)
    pct_patterns = [
        r"(?:aggregate|overall|total|percentage|marks\s*obtained|scored)\s*[:\-]?\s*(\d{2,3}(?:\.\d{1,2})?)\s*%",
        r"(\d{2}(?:\.\d{1,2})?)\s*%\s*(?:marks|aggregate|in\s+(?:12th|10th|class|b\.?tech|graduation))",
    ]
    for pat in pct_patterns:
        m = re.search(pat, combined_text, re.IGNORECASE)
        if m:
            val = float(m.group(1))
            if 0 <= val <= 100:
                facts.marks_percentage = val
                break

    # CGPA fallback -> convert to equivalent percentage if percentage absent
    cgpa_m = re.search(r"\b(?:cgpa|sgpa)\s*[:\-]?\s*(\d{1,2}(?:\.\d{1,2})?)(?:\s*/\s*10)?", combined_text, re.IGNORECASE)
    if cgpa_m:
        cgpa_val = float(cgpa_m.group(1))
        if 0 < cgpa_val <= 10:
            facts.cgpa = cgpa_val
            if facts.marks_percentage is None:
                facts.marks_percentage = round(cgpa_val * 9.5, 2)

    # Annual income in INR (handles both compact labels and formal certificate phrasing)
    inc_patterns = [
        r"(?:annual\s+(?:family\s+)?income|family\s+income|total\s+income).{0,180}?(?:rs\.?|inr|₹)\s*([\d,]+(?:\.\d+)?)\s*(lakhs?|lacs?|crores?)?",
        r"(?:rs\.?|inr|₹)\s*([\d,]+(?:\.\d+)?)\s*(lakhs?|lacs?)?\s*(?:\([^)]*\)\s*)?(?:per\s+annum|p\.a\.|annually)",
    ]
    for pat in inc_patterns:
        m = re.search(pat, combined_text, re.IGNORECASE)
        if m:
            parsed = _parse_indian_currency_to_inr(m.group(1), m.group(2) if m.lastindex and m.lastindex >= 2 else None)
            if parsed and parsed >= 1000:
                facts.annual_income_inr = parsed
                break

    # Age
    age_m = re.search(r"\bage\s*[:\-]?\s*(\d{2})\s*(?:years|yrs)?\b", combined_text, re.IGNORECASE)
    if age_m:
        age_val = int(age_m.group(1))
        if 10 <= age_val <= 100:
            facts.age_years = age_val

    # Category
    cat_m = re.search(r"\bcategory\s*[:\-]?\s*(SC|ST|OBC(?:-NCL)?|EWS|General|Minority)\b", combined_text, re.IGNORECASE)
    if cat_m:
        facts.category = cat_m.group(1).upper()

    # Document presence detection per uploaded file (check filename + content)
    for filename, text in texts_by_file.items():
        haystack = f"{filename}\n{text}".lower()
        for doc_type, keywords in DOCUMENT_ALIASES.items():
            if doc_type in facts.documents_detected:
                continue
            # Require filename match OR strong keyword match inside document text
            fn_low = filename.lower()
            if any(kw in fn_low for kw in keywords) or any(
                re.search(rf"\b{re.escape(kw)}\b", haystack) for kw in keywords
            ):
                # Avoid false-positive detection from a scheme guideline PDF itself
                if "scheme" in fn_low or "guideline" in fn_low or "eligibility" in fn_low:
                    continue
                facts.documents_detected[doc_type] = filename

    return facts


def extract_scheme_requirements(scheme_name: str, scheme_text: str) -> SchemeRequirements:
    """Extract numeric thresholds and required documents from a scheme guideline PDF."""
    reqs = SchemeRequirements(scheme_name=scheme_name)
    text = scheme_text or ""

    # Minimum marks %
    marks_m = re.search(
        r"(?:minimum|at\s+least|not\s+less\s+than|>=)\s*(\d{2}(?:\.\d{1,2})?)\s*%\s*(?:marks|aggregate|score)?",
        text,
        re.IGNORECASE,
    )
    if marks_m:
        reqs.min_marks_percentage = float(marks_m.group(1))

    # Maximum annual income
    inc_m = re.search(
        r"(?:annual\s+(?:family\s+)?income|family\s+income|income\s+(?:ceiling|limit|cap)).{0,40}?(?:not\s+exceed|below|less\s+than|up\s+to|<=|within)?\s*(?:rs\.?|inr|₹)\s*([\d,]+(?:\.\d+)?)\s*(lakhs?|lacs?|crores?)?",
        text,
        re.IGNORECASE,
    )
    if inc_m:
        reqs.max_income_inr = _parse_indian_currency_to_inr(
            inc_m.group(1), inc_m.group(2) if inc_m.lastindex and inc_m.lastindex >= 2 else None
        )

    # Age bounds
    age_range_m = re.search(
        r"age\s*(?:between|limit)?\s*(\d{2})\s*(?:to|-|and)\s*(\d{2})\s*years",
        text,
        re.IGNORECASE,
    )
    if age_range_m:
        reqs.min_age = int(age_range_m.group(1))
        reqs.max_age = int(age_range_m.group(2))
    else:
        min_age_m = re.search(r"(?:minimum\s+age|at\s+least)\s*(\d{2})\s*years", text, re.IGNORECASE)
        if min_age_m:
            reqs.min_age = int(min_age_m.group(1))

    # Allowed categories if explicitly restricted
    if re.search(r"\b(?:SC/ST|Scheduled\s+Caste|Scheduled\s+Tribe)\s+only\b", text, re.IGNORECASE):
        reqs.allowed_categories = ["SC", "ST"]

    # Required documents mentioned in scheme text
    lower_text = text.lower()
    for doc_type, keywords in DOCUMENT_ALIASES.items():
        if any(kw in lower_text for kw in keywords):
            reqs.required_documents.append(doc_type)

    return reqs


def evaluate_eligibility(
    scheme_name: str,
    scheme_text: str,
    citizen_texts_by_file: dict[str, str],
    gemini: GeminiClient | None = None,
    language: str = "en",
) -> dict:
    """Run deterministic Python rule checks first, then ask LLM only to explain the result."""
    reqs = extract_scheme_requirements(scheme_name, scheme_text)
    facts = extract_citizen_facts(citizen_texts_by_file)

    criteria_checks: list[CriterionCheck] = []
    has_fail = False
    has_unknown = False

    # 1. Marks threshold
    if reqs.min_marks_percentage is not None:
        if facts.marks_percentage is None:
            status = "UNKNOWN"
            has_unknown = True
            c_val = "Not found in uploaded documents"
        elif facts.marks_percentage >= reqs.min_marks_percentage:
            status = "PASS"
            c_val = f"{facts.marks_percentage}%"
        else:
            status = "FAIL"
            has_fail = True
            c_val = f"{facts.marks_percentage}%"
        criteria_checks.append(
            CriterionCheck(
                criterion="Minimum Marks / Percentage",
                required=f">= {reqs.min_marks_percentage}%",
                citizen_value=c_val,
                status=status,
            )
        )

    # 2. Income threshold
    if reqs.max_income_inr is not None:
        req_str = f"<= INR {int(reqs.max_income_inr):,}"
        if facts.annual_income_inr is None:
            status = "UNKNOWN"
            has_unknown = True
            c_val = "Not found in uploaded documents"
        elif facts.annual_income_inr <= reqs.max_income_inr:
            status = "PASS"
            c_val = f"INR {int(facts.annual_income_inr):,}"
        else:
            status = "FAIL"
            has_fail = True
            c_val = f"INR {int(facts.annual_income_inr):,}"
        criteria_checks.append(
            CriterionCheck(
                criterion="Annual Family Income Ceiling",
                required=req_str,
                citizen_value=c_val,
                status=status,
            )
        )

    # 3. Age bounds
    if reqs.min_age is not None or reqs.max_age is not None:
        req_age = (
            f"{reqs.min_age or 0} - {reqs.max_age or 'Any'} years"
            if reqs.max_age
            else f">= {reqs.min_age} years"
        )
        if facts.age_years is None:
            status = "UNKNOWN"
            has_unknown = True
            c_val = "Not found in uploaded documents"
        else:
            ok_min = reqs.min_age is None or facts.age_years >= reqs.min_age
            ok_max = reqs.max_age is None or facts.age_years <= reqs.max_age
            if ok_min and ok_max:
                status = "PASS"
            else:
                status = "FAIL"
                has_fail = True
            c_val = f"{facts.age_years} years"
        criteria_checks.append(
            CriterionCheck(
                criterion="Age Requirement",
                required=req_age,
                citizen_value=c_val,
                status=status,
            )
        )

    # 4. Document Checklist (Available vs Missing with supporting filename)
    available_docs: list[dict] = []
    missing_docs: list[str] = []
    for doc_type in reqs.required_documents:
        if doc_type in facts.documents_detected:
            available_docs.append(
                {
                    "document": doc_type,
                    "supporting_filename": facts.documents_detected[doc_type],
                    "status": "Available",
                }
            )
        else:
            missing_docs.append(doc_type)

    # Deterministic verdict
    if has_fail:
        verdict = "NOT ELIGIBLE"
    elif missing_docs:
        verdict = "CONDITIONALLY ELIGIBLE (DOCUMENTS MISSING)"
    elif has_unknown and not criteria_checks:
        verdict = "INSUFFICIENT DATA"
    elif has_unknown:
        verdict = "PARTIALLY VERIFIED (NEEDS NUMERIC PROOF)"
    else:
        verdict = "ELIGIBLE"

    # AI Explanation (LLM only explains the deterministic verdict; never changes verdict)
    ai_explanation = _generate_ai_explanation(
        scheme_name=scheme_name,
        verdict=verdict,
        criteria_checks=criteria_checks,
        available_docs=available_docs,
        missing_docs=missing_docs,
        gemini=gemini,
        language=language,
    )

    return {
        "scheme_name": scheme_name,
        "rule_based_verdict": verdict,
        "ai_explanation": ai_explanation,
        "criteria_checks": [
            {
                "criterion": c.criterion,
                "required": c.required,
                "citizen_value": c.citizen_value,
                "status": c.status,
            }
            for c in criteria_checks
        ],
        "available_documents": available_docs,
        "missing_documents": missing_docs,
        "supporting_files": [
            {"document": d["document"], "filename": d["supporting_filename"]}
            for d in available_docs
        ],
        "extracted_citizen_facts": {
            "marks_percentage": facts.marks_percentage,
            "cgpa": facts.cgpa,
            "annual_income_inr": facts.annual_income_inr,
            "age_years": facts.age_years,
            "category": facts.category,
        },
    }


def _generate_ai_explanation(
    *,
    scheme_name: str,
    verdict: str,
    criteria_checks: list[CriterionCheck],
    available_docs: list[dict],
    missing_docs: list[str],
    gemini: GeminiClient | None,
    language: str,
) -> str:
    deterministic_summary = (
        f"Deterministic Rule-Based Verdict for '{scheme_name}': {verdict}. "
        f"Available documents: {len(available_docs)}; Missing documents: {len(missing_docs)}."
    )
    if gemini is None or not gemini.is_configured:
        missing_txt = ", ".join(missing_docs) if missing_docs else "None"
        return (
            f"{deterministic_summary} "
            f"Missing documents to obtain before applying: {missing_txt}. "
            "(Live Gemini AI explanation unavailable because GEMINI_API_KEY is not set.)"
        )

    lang_note = "Respond in Hindi." if language == "hi" else "Respond in clear English."
    prompt = (
        f"Scheme: {scheme_name}\n"
        f"Rule-Based Verdict (DO NOT contradict or alter): {verdict}\n"
        f"Numeric Criteria Checks: {[(c.criterion, c.required, c.citizen_value, c.status) for c in criteria_checks]}\n"
        f"Available Documents: {available_docs}\n"
        f"Missing Documents: {missing_docs}\n\n"
        "Explain this deterministic verdict to the Indian citizen in 3-5 helpful sentences, "
        "noting next steps for any missing documents. Do not invent any document not listed above."
    )
    try:
        return gemini.generate(
            system_prompt=f"You are a helpful Indian civic eligibility explainer. {lang_note}",
            user_prompt=prompt,
            temperature=0.1,
        )
    except GeminiUnavailableError:
        return deterministic_summary
