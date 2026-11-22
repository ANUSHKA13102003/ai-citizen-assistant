"""Deterministic Python eligibility rules engine separated from AI explanation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.gemini_client import GeminiClient, GeminiUnavailableError

DOCUMENT_ALIASES: dict[str, list[str]] = {
    "Aadhaar Card": ["aadhaar", "aadhar", "uidai", "unique identification"],
    "Income Certificate": [
        "income certificate",
        "annual family income",
        "tehsildar",
        "income proof",
    ],
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
    "Domicile / Residence Certificate": [
        "domicile",
        "residence certificate",
        "nativity certificate",
    ],
    "Academic Marksheet / Transcript": [
        "marksheet",
        "mark sheet",
        "marks statement",
        "statement of marks",
        "grade card",
        "transcript",
        "cgpa",
        "percentage",
        "10th",
        "12th",
        "semester",
    ],
    "Bank Passbook / Account Details": [
        "bank passbook",
        "ifsc",
        "bank account",
        "cancelled cheque",
        "aadhaar seeded",
    ],
    "Bonafide / Admission Proof": [
        "bonafide",
        "enrollment",
        "admission letter",
        "student id",
        "institutional verification",
    ],
    "Fee Receipt": ["fee receipt", "tuition fee", "payment receipt"],
    "Land Ownership / Khatauni Record": [
        "land ownership",
        "khatauni",
        "khasra",
        "jamabandi",
        "ror",
        "agricultural land",
        "cultivable land",
    ],
    "PAN Card": ["pan card", "permanent account number"],
    "Passport Size Photograph": ["photograph", "passport size photo", "passport photo"],
    "Disability Certificate (UDID)": ["disability certificate", "udid", "pwbd", "divyang"],
    "Ration Card": ["ration card", "nfsa", "antyodaya"],
    "Birth Certificate / Age Proof": ["birth certificate", "certificate of birth", "age proof"],
}


def format_inr(amount: float | int | None) -> str:
    """Format an integer/float amount using Indian comma grouping (e.g., ₹2,50,000)."""
    if amount is None:
        return ""
    n = int(round(float(amount)))
    neg = n < 0
    s = str(abs(n))
    if len(s) <= 3:
        grouped = s
    else:
        last3 = s[-3:]
        rest = s[:-3]
        parts = []
        while len(rest) > 2:
            parts.append(rest[-2:])
            rest = rest[:-2]
        if rest:
            parts.append(rest)
        grouped = ",".join(reversed(parts)) + "," + last3
    return f"{'-' if neg else ''}₹{grouped}"


@dataclass
class CitizenFacts:
    marks_percentage: float | None = None
    cgpa: float | None = None
    annual_income_inr: float | None = None
    age_years: int | None = None
    category: str | None = None
    state: str | None = None
    gender: str | None = None
    education_level: str | None = None
    occupation: str | None = None
    has_disability: bool | None = None
    documents_detected: dict[str, str] = field(default_factory=dict)


@dataclass
class SchemeRequirements:
    scheme_name: str
    min_marks_percentage: float | None = None
    max_income_inr: float | None = None
    min_age: int | None = None
    max_age: int | None = None
    allowed_categories: list[str] = field(default_factory=list)
    categories_maybe: list[str] = field(default_factory=list)
    allowed_states: list[str] = field(default_factory=list)
    gender: str | None = None
    education_levels: list[str] = field(default_factory=list)
    occupations: list[str] = field(default_factory=list)
    requires_disability: bool = False
    verify_only: bool = False
    any_of: list[dict] = field(default_factory=list)
    required_documents: list[str] = field(default_factory=list)


@dataclass
class CriterionCheck:
    criterion: str
    required: str
    citizen_value: str
    status: str  # PASS | FAIL | UNKNOWN
    missing_doc_hint: str = ""
    missing_doc_type: str = ""

    def to_dict(self) -> dict:
        return {
            "criterion": self.criterion,
            "required": self.required,
            "citizen_value": self.citizen_value,
            "status": self.status,
            "missing_doc_hint": self.missing_doc_hint,
            "missing_doc_type": self.missing_doc_type,
        }


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


def extract_citizen_facts(
    texts_by_file: dict[str, str],
    overrides: dict | None = None,
) -> CitizenFacts:
    """Extract numeric marks, income, age, category, state, and available documents with regex."""
    facts = CitizenFacts()
    combined_text = "\n".join(texts_by_file.values())

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

    cgpa_m = re.search(
        r"\b(?:cgpa|sgpa)\s*[:\-]?\s*(\d{1,2}(?:\.\d{1,2})?)(?:\s*/\s*10)?",
        combined_text,
        re.IGNORECASE,
    )
    if cgpa_m:
        cgpa_val = float(cgpa_m.group(1))
        if 0 < cgpa_val <= 10:
            facts.cgpa = cgpa_val
            if facts.marks_percentage is None:
                facts.marks_percentage = round(cgpa_val * 9.5, 2)

    inc_patterns = [
        r"(?:annual\s+(?:family\s+)?income|family\s+income|total\s+income).{0,180}?(?:rs\.?|inr|₹)\s*([\d,]+(?:\.\d+)?)\s*(lakhs?|lacs?|crores?)?",
        r"(?:rs\.?|inr|₹)\s*([\d,]+(?:\.\d+)?)\s*(lakhs?|lacs?)?\s*(?:\([^)]*\)\s*)?(?:per\s+annum|p\.a\.|annually)",
    ]
    for pat in inc_patterns:
        m = re.search(pat, combined_text, re.IGNORECASE | re.DOTALL)
        if m:
            parsed = _parse_indian_currency_to_inr(
                m.group(1), m.group(2) if m.lastindex and m.lastindex >= 2 else None
            )
            if parsed and parsed >= 1000:
                facts.annual_income_inr = parsed
                break

    age_m = re.search(r"\bage\s*[:\-]?\s*(\d{2})\s*(?:years|yrs)?\b", combined_text, re.IGNORECASE)
    if age_m:
        age_val = int(age_m.group(1))
        if 5 <= age_val <= 100:
            facts.age_years = age_val

    cat_m = re.search(
        r"\bcategory\s*[:\-]?\s*(SC|ST|OBC(?:-NCL)?|EWS|General|Minority)\b",
        combined_text,
        re.IGNORECASE,
    )
    if cat_m:
        facts.category = cat_m.group(1).upper().replace("-NCL", "")

    gen_m = re.search(r"\bgender\s*[:\-]?\s*(male|female|transgender)\b", combined_text, re.IGNORECASE)
    if gen_m:
        facts.gender = gen_m.group(1).lower()

    if "uttar pradesh" in combined_text.lower() or "lucknow" in combined_text.lower() or "noida" in combined_text.lower():
        facts.state = "Uttar Pradesh"

    for filename, text in texts_by_file.items():
        haystack = f"{filename}\n{text}".lower()
        fn_low = filename.lower()
        if "scheme" in fn_low or "guideline" in fn_low or "eligibility" in fn_low:
            continue
        for doc_type, keywords in DOCUMENT_ALIASES.items():
            if doc_type in facts.documents_detected:
                continue
            if any(kw in fn_low for kw in keywords) or any(
                re.search(rf"\b{re.escape(kw)}\b", haystack) for kw in keywords
            ):
                facts.documents_detected[doc_type] = filename

    # Apply manual overrides from the Detected Details / Wizard panel
    if overrides:
        marks_v = overrides.get("marks_percent")
        if marks_v in (None, ""):
            marks_v = overrides.get("marks_percentage")
        if marks_v not in (None, ""):
            facts.marks_percentage = float(marks_v)
        if overrides.get("cgpa") not in (None, ""):
            facts.cgpa = float(overrides["cgpa"])
        if overrides.get("annual_income_inr") not in (None, ""):
            facts.annual_income_inr = float(overrides["annual_income_inr"])
        age_v = overrides.get("age")
        if age_v in (None, ""):
            age_v = overrides.get("age_years")
        if age_v not in (None, ""):
            facts.age_years = int(float(age_v))
        if overrides.get("category") not in (None, ""):
            facts.category = str(overrides["category"]).upper().replace("-NCL", "").strip()
        if overrides.get("state") not in (None, ""):
            facts.state = str(overrides["state"]).strip()
        if overrides.get("gender") not in (None, ""):
            facts.gender = str(overrides["gender"]).lower().strip()
        if overrides.get("education_level") not in (None, ""):
            facts.education_level = str(overrides["education_level"]).lower().strip()
        if overrides.get("occupation") not in (None, ""):
            occ = overrides["occupation"]
            if isinstance(occ, list):
                facts.occupation = ",".join(str(x).lower().strip() for x in occ if x)
            else:
                facts.occupation = str(occ).lower().strip()
        if overrides.get("has_disability") is not None:
            val = overrides["has_disability"]
            if isinstance(val, bool):
                facts.has_disability = val
            elif str(val).lower() in {"true", "yes", "1"}:
                facts.has_disability = True
            elif str(val).lower() in {"false", "no", "0"}:
                facts.has_disability = False

    return facts


def extract_scheme_requirements(
    scheme_name: str,
    scheme_text: str = "",
    structured_scheme: dict | None = None,
) -> SchemeRequirements:
    """Build SchemeRequirements from structured library rules or extracted scheme PDF text."""
    reqs = SchemeRequirements(scheme_name=scheme_name)
    if structured_scheme and isinstance(structured_scheme.get("rules"), dict):
        rules = structured_scheme["rules"]
        reqs.min_marks_percentage = (
            float(rules["min_marks_percent"])
            if rules.get("min_marks_percent") is not None
            else None
        )
        reqs.max_income_inr = (
            float(rules["max_family_income_inr"])
            if rules.get("max_family_income_inr") is not None
            else None
        )
        reqs.min_age = int(rules["min_age"]) if rules.get("min_age") is not None else None
        reqs.max_age = int(rules["max_age"]) if rules.get("max_age") is not None else None
        reqs.allowed_categories = [c.upper() for c in (rules.get("categories") or [])]
        reqs.categories_maybe = [c.upper() for c in (rules.get("categories_maybe") or [])]
        reqs.allowed_states = list(rules.get("states") or [])
        reqs.gender = rules.get("gender")
        reqs.education_levels = [str(e).lower() for e in (rules.get("education_levels") or [])]
        reqs.occupations = [str(o).lower() for o in (rules.get("occupations") or [])]
        reqs.requires_disability = bool(rules.get("requires_disability"))
        reqs.verify_only = bool(rules.get("verify_only"))
        reqs.any_of = list(rules.get("any_of") or [])
        reqs.required_documents = list(structured_scheme.get("required_documents") or [])
        return reqs

    text = scheme_text or ""
    marks_m = re.search(
        r"(?:minimum|at\s+least|not\s+less\s+than|>=)\s*(\d{2}(?:\.\d{1,2})?)\s*%\s*(?:marks|aggregate|score)?",
        text,
        re.IGNORECASE,
    )
    if marks_m:
        reqs.min_marks_percentage = float(marks_m.group(1))

    inc_m = re.search(
        r"(?:annual\s+(?:family\s+)?income|family\s+income|income\s+(?:ceiling|limit|cap)).{0,40}?(?:not\s+exceed|below|less\s+than|up\s+to|<=|within)?\s*(?:rs\.?|inr|₹)\s*([\d,]+(?:\.\d+)?)\s*(lakhs?|lacs?|crores?)?",
        text,
        re.IGNORECASE,
    )
    if inc_m:
        reqs.max_income_inr = _parse_indian_currency_to_inr(
            inc_m.group(1), inc_m.group(2) if inc_m.lastindex and inc_m.lastindex >= 2 else None
        )

    age_range_m = re.search(
        r"age\s*(?:between|limit)?\s*(\d{2})\s*(?:to|-|and)\s*(\d{2})\s*years",
        text,
        re.IGNORECASE,
    )
    if age_range_m:
        reqs.min_age = int(age_range_m.group(1))
        reqs.max_age = int(age_range_m.group(2))
    else:
        min_age_m = re.search(
            r"(?:minimum\s+age|at\s+least)\s*(\d{2})\s*years", text, re.IGNORECASE
        )
        if min_age_m:
            reqs.min_age = int(min_age_m.group(1))

    if re.search(r"\b(?:SC/ST|Scheduled\s+Caste|Scheduled\s+Tribe)\s+only\b", text, re.IGNORECASE):
        reqs.allowed_categories = ["SC", "ST"]

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
    structured_scheme: dict | None = None,
    profile_overrides: dict | None = None,
) -> dict:
    """Run deterministic Python rule checks first, then ask LLM only to explain the result."""
    reqs = extract_scheme_requirements(scheme_name, scheme_text, structured_scheme)
    facts = extract_citizen_facts(citizen_texts_by_file, overrides=profile_overrides)

    criteria_checks: list[CriterionCheck] = []
    has_fail = False
    has_unknown = False

    # 1. Marks threshold
    if reqs.min_marks_percentage is not None:
        if facts.marks_percentage is None:
            status = "UNKNOWN"
            has_unknown = True
            c_val = "Upload your marksheet to check this"
            hint = "Upload your marksheet to check this"
            dtype = "marksheet"
        elif facts.marks_percentage >= reqs.min_marks_percentage:
            status = "PASS"
            c_val = f"{facts.marks_percentage:g}%"
            hint, dtype = "", ""
        else:
            status = "FAIL"
            has_fail = True
            c_val = f"{facts.marks_percentage:g}%"
            hint, dtype = "", ""
        criteria_checks.append(
            CriterionCheck(
                criterion="Minimum Marks / Percentage",
                required=f">= {reqs.min_marks_percentage:g}%",
                citizen_value=c_val,
                status=status,
                missing_doc_hint=hint,
                missing_doc_type=dtype,
            )
        )

    # 2. Income threshold
    if reqs.max_income_inr is not None:
        req_str = f"<= INR {int(reqs.max_income_inr):,}"
        if facts.annual_income_inr is None:
            status = "UNKNOWN"
            has_unknown = True
            c_val = "Upload your income certificate to check this"
            hint = "Upload your income certificate to check this"
            dtype = "income_certificate"
        elif facts.annual_income_inr <= reqs.max_income_inr:
            status = "PASS"
            c_val = f"INR {int(facts.annual_income_inr):,}"
            hint, dtype = "", ""
        else:
            status = "FAIL"
            has_fail = True
            c_val = f"INR {int(facts.annual_income_inr):,}"
            hint, dtype = "", ""
        criteria_checks.append(
            CriterionCheck(
                criterion="Annual Family Income Ceiling",
                required=req_str,
                citizen_value=c_val,
                status=status,
                missing_doc_hint=hint,
                missing_doc_type=dtype,
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
            c_val = "Upload your Aadhaar or age proof to check this"
            hint = "Upload your Aadhaar or age proof to check this"
            dtype = "aadhaar"
        else:
            ok_min = reqs.min_age is None or facts.age_years >= reqs.min_age
            ok_max = reqs.max_age is None or facts.age_years <= reqs.max_age
            if ok_min and ok_max:
                status = "PASS"
            else:
                status = "FAIL"
                has_fail = True
            c_val = f"{facts.age_years} years"
            hint, dtype = "", ""
        criteria_checks.append(
            CriterionCheck(
                criterion="Age Requirement",
                required=req_age,
                citizen_value=c_val,
                status=status,
                missing_doc_hint=hint,
                missing_doc_type=dtype,
            )
        )

    # 4. Category check if scheme restricts categories
    if reqs.allowed_categories:
        req_cats = ", ".join(reqs.allowed_categories)
        if not facts.category:
            status = "UNKNOWN"
            has_unknown = True
            c_val = "Upload your caste/category certificate to check this"
            hint = "Tell us your social category or upload your category certificate"
            dtype = "caste_certificate"
        elif facts.category.upper() in [c.upper() for c in reqs.allowed_categories]:
            status = "PASS"
            c_val = facts.category
            hint, dtype = "", ""
        elif facts.category.upper() in [c.upper() for c in reqs.categories_maybe]:
            status = "UNKNOWN"
            has_unknown = True
            c_val = facts.category
            hint = f"Special rules may apply for {facts.category} applicants; confirm on the portal"
            dtype = ""
        else:
            status = "FAIL"
            has_fail = True
            c_val = facts.category
            hint, dtype = "", ""
        criteria_checks.append(
            CriterionCheck(
                criterion="Eligible Category",
                required=req_cats,
                citizen_value=c_val,
                status=status,
                missing_doc_hint=hint,
                missing_doc_type=dtype,
            )
        )

    # 5. State / Domicile check if scheme restricts states
    if reqs.allowed_states:
        req_states = ", ".join(reqs.allowed_states)
        if not facts.state:
            status = "UNKNOWN"
            has_unknown = True
            c_val = "Upload your domicile certificate or Aadhaar to check this"
            hint = "Tell us your state or upload your residence proof"
            dtype = "domicile_certificate"
        elif any(s.lower() == facts.state.lower() for s in reqs.allowed_states):
            status = "PASS"
            c_val = facts.state
            hint, dtype = "", ""
        else:
            status = "FAIL"
            has_fail = True
            c_val = facts.state
            hint, dtype = "", ""
        criteria_checks.append(
            CriterionCheck(
                criterion="State / Domicile",
                required=req_states,
                citizen_value=c_val,
                status=status,
                missing_doc_hint=hint,
                missing_doc_type=dtype,
            )
        )

    # 6. Gender check if scheme restricts gender
    if reqs.gender:
        if not facts.gender:
            status = "UNKNOWN"
            has_unknown = True
            c_val = "Not specified"
            hint = f"This scheme is for {reqs.gender.title()} applicants"
            dtype = "aadhaar"
        elif facts.gender.lower() == reqs.gender.lower():
            status = "PASS"
            c_val = facts.gender.title()
            hint, dtype = "", ""
        else:
            status = "FAIL"
            has_fail = True
            c_val = facts.gender.title()
            hint, dtype = "", ""
        criteria_checks.append(
            CriterionCheck(
                criterion="Gender Requirement",
                required=reqs.gender.title(),
                citizen_value=c_val,
                status=status,
                missing_doc_hint=hint,
                missing_doc_type=dtype,
            )
        )

    # 7. Education level check
    if reqs.education_levels:
        req_edu = ", ".join(reqs.education_levels)
        if not facts.education_level:
            status = "UNKNOWN"
            has_unknown = True
            c_val = "Not specified"
            hint = "Tell us your education level or upload a marksheet"
            dtype = "marksheet"
        elif facts.education_level.lower() in reqs.education_levels:
            status = "PASS"
            c_val = facts.education_level.replace("_", " ").title()
            hint, dtype = "", ""
        else:
            status = "FAIL"
            has_fail = True
            c_val = facts.education_level.replace("_", " ").title()
            hint, dtype = "", ""
        criteria_checks.append(
            CriterionCheck(
                criterion="Education Level",
                required=req_edu.replace("_", " ").title(),
                citizen_value=c_val,
                status=status,
                missing_doc_hint=hint,
                missing_doc_type=dtype,
            )
        )

    # 8. Occupation / role check
    if reqs.occupations:
        req_occ = ", ".join(reqs.occupations)
        citizen_occs = (
            {x.strip().lower() for x in facts.occupation.split(",") if x.strip()}
            if facts.occupation
            else set()
        )
        if not citizen_occs:
            status = "UNKNOWN"
            has_unknown = True
            c_val = "Not specified"
            hint = f"Applies to: {req_occ.replace('_', ' ')}"
            dtype = ""
        elif citizen_occs & set(reqs.occupations):
            status = "PASS"
            c_val = ", ".join(sorted(citizen_occs)).replace("_", " ").title()
            hint, dtype = "", ""
        else:
            status = "FAIL"
            has_fail = True
            c_val = ", ".join(sorted(citizen_occs)).replace("_", " ").title()
            hint, dtype = "", ""
        criteria_checks.append(
            CriterionCheck(
                criterion="Who Can Apply",
                required=req_occ.replace("_", " ").title(),
                citizen_value=c_val,
                status=status,
                missing_doc_hint=hint,
                missing_doc_type=dtype,
            )
        )

    # 9. Disability requirement
    if reqs.requires_disability:
        if facts.has_disability is None:
            status = "UNKNOWN"
            has_unknown = True
            c_val = "Not specified"
            hint = "For persons with benchmark disability (UDID certificate needed)"
            dtype = ""
        elif facts.has_disability:
            status = "PASS"
            c_val = "Yes"
            hint, dtype = "", ""
        else:
            status = "FAIL"
            has_fail = True
            c_val = "No"
            hint, dtype = "", ""
        criteria_checks.append(
            CriterionCheck(
                criterion="Disability Requirement",
                required="Benchmark Disability (UDID)",
                citizen_value=c_val,
                status=status,
                missing_doc_hint=hint,
                missing_doc_type=dtype,
            )
        )

    # 10. Any-of branch check (e.g., Stand Up India: SC/ST OR Woman)
    if reqs.any_of:
        branch_statuses: list[str] = []
        for branch in reqs.any_of:
            if "categories" in branch:
                allowed = [c.upper() for c in branch["categories"]]
                if not facts.category:
                    branch_statuses.append("UNKNOWN")
                elif facts.category.upper() in allowed:
                    branch_statuses.append("PASS")
                else:
                    branch_statuses.append("FAIL")
            elif "gender" in branch:
                g = str(branch["gender"]).lower()
                if not facts.gender:
                    branch_statuses.append("UNKNOWN")
                elif facts.gender.lower() == g:
                    branch_statuses.append("PASS")
                else:
                    branch_statuses.append("FAIL")
        if "PASS" in branch_statuses:
            status = "PASS"
            c_val = "Meets criteria"
            hint, dtype = "", ""
        elif "UNKNOWN" in branch_statuses:
            status = "UNKNOWN"
            has_unknown = True
            c_val = "Not specified"
            hint = "Tell us your category or gender to confirm"
            dtype = ""
        else:
            status = "FAIL"
            has_fail = True
            c_val = f"{facts.category or ''} / {facts.gender or ''}".strip(" /")
            hint, dtype = "", ""
        criteria_checks.append(
            CriterionCheck(
                criterion="Special Group Requirement",
                required="SC/ST or Woman applicant",
                citizen_value=c_val,
                status=status,
                missing_doc_hint=hint,
                missing_doc_type=dtype,
            )
        )

    # 11. Verify-only schemes (e.g., SECC / ration-card based schemes)
    if reqs.verify_only and not has_fail:
        has_unknown = True
        criteria_checks.append(
            CriterionCheck(
                criterion="Portal Verification Needed",
                required="Verify family ration card / eligibility list on official portal",
                citizen_value="Check on portal",
                status="UNKNOWN",
                missing_doc_hint="Confirm your name/ration card on the official portal",
                missing_doc_type="",
            )
        )

    # 7. Document Checklist
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

    if has_fail:
        verdict = "NOT ELIGIBLE"
        finder_tier = "Not eligible"
    elif has_unknown:
        verdict = (
            "PARTIALLY VERIFIED (NEEDS NUMERIC PROOF)"
            if criteria_checks
            else "INSUFFICIENT DATA"
        )
        finder_tier = "Needs more info"
    elif missing_docs:
        verdict = "CONDITIONALLY ELIGIBLE (DOCUMENTS MISSING)"
        finder_tier = "Likely eligible"
    else:
        verdict = "ELIGIBLE"
        finder_tier = "Eligible"

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
        "finder_tier": finder_tier,
        "ai_explanation": ai_explanation,
        "criteria_checks": [c.to_dict() for c in criteria_checks],
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
            "state": facts.state,
            "gender": facts.gender,
        },
    }


def match_all_schemes(
    schemes: list[dict],
    citizen_texts_by_file: dict[str, str],
    profile_overrides: dict | None = None,
    lang: str = "en",
) -> list[dict]:
    """Run deterministic rules against every scheme in the library and rank results."""
    from app.services.sample_library import build_apply_steps

    tier_order = {"Eligible": 0, "Likely eligible": 1, "Needs more info": 2, "Not eligible": 3}
    ranked: list[dict] = []

    for scheme in schemes:
        res = evaluate_eligibility(
            scheme_name=scheme.get("name") or scheme.get("title", ""),
            scheme_text="",
            citizen_texts_by_file=citizen_texts_by_file,
            gemini=None,
            language=lang,
            structured_scheme=scheme,
            profile_overrides=profile_overrides,
        )
        reasons_pass = [
            f"{c['criterion']}: {c['citizen_value']} ({c['required']})"
            for c in res["criteria_checks"]
            if c["status"] == "PASS"
        ]
        reasons_fail = [
            f"{c['criterion']}: {c['citizen_value']} (requires {c['required']})"
            for c in res["criteria_checks"]
            if c["status"] == "FAIL"
        ]
        reasons_unknown = [
            c["missing_doc_hint"] or f"{c['criterion']} unknown"
            for c in res["criteria_checks"]
            if c["status"] == "UNKNOWN"
        ]
        tier = res["finder_tier"]
        if tier in {"Eligible", "Likely eligible"}:
            group = "qualify"
        elif tier == "Needs more info":
            group = "check"
        else:
            group = "not_eligible"

        ranked.append(
            {
                "id": scheme.get("id"),
                "slug": scheme.get("slug") or scheme.get("id"),
                "name": scheme.get("name") or scheme.get("title"),
                "name_hi": scheme.get("name_hi") or scheme.get("name") or scheme.get("title"),
                "ministry": scheme.get("ministry", ""),
                "category": scheme.get("category", ""),
                "level": scheme.get("level", "central"),
                "who": scheme.get("who", ""),
                "who_hi": scheme.get("who_hi") or scheme.get("who", ""),
                "benefit": scheme.get("benefit") or scheme.get("summary", ""),
                "benefit_hi": scheme.get("benefit_hi") or scheme.get("benefit") or scheme.get("summary", ""),
                "official_url": scheme.get("official_url") or scheme.get("source_url", ""),
                "apply": scheme.get("apply") or {},
                "how_to_apply": scheme.get("how_to_apply", ""),
                "how_to_apply_steps": build_apply_steps(scheme, lang=lang),
                "last_verified": scheme.get("last_verified", "2026-11-19"),
                "required_documents": scheme.get("required_documents", []),
                "tier": tier,
                "group": group,
                "rule_based_verdict": res["rule_based_verdict"],
                "reasons_pass": reasons_pass,
                "reasons_fail": reasons_fail,
                "reasons_unknown": reasons_unknown,
                "available_documents": res["available_documents"],
                "missing_documents": res["missing_documents"],
                "criteria_checks": res["criteria_checks"],
            }
        )

    ranked.sort(
        key=lambda item: (
            tier_order.get(item["tier"], 9),
            len(item["reasons_fail"]),
            len(item["missing_documents"]),
            item["name"],
        )
    )
    return ranked


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
    missing_txt = ", ".join(missing_docs) if missing_docs else "None"
    unknowns = [c.missing_doc_hint for c in criteria_checks if c.status == "UNKNOWN" and c.missing_doc_hint]
    deterministic_summary = (
        f"Rule-Based Verdict for {scheme_name}: {verdict}. "
        f"Available documents: {len(available_docs)}; Missing documents: {len(missing_docs)} ({missing_txt})."
        + (f" Next step: {' '.join(unknowns)}." if unknowns else "")
    )
    if gemini is None or not gemini.is_configured:
        return deterministic_summary

    lang_note = "Respond in Hindi." if language == "hi" else "Respond in clear English."
    prompt = (
        f"Scheme: {scheme_name}\n"
        f"Rule-Based Verdict (DO NOT contradict or alter): {verdict}\n"
        f"Numeric Criteria Checks: {[(c.criterion, c.required, c.citizen_value, c.status) for c in criteria_checks]}\n"
        f"Available Documents: {available_docs}\n"
        f"Missing Documents: {missing_docs}\n\n"
        "Explain this result to the citizen in 3-4 clear sentences, noting which documents or proofs "
        "to upload or obtain next. Do not invent any document not listed above."
    )
    try:
        return gemini.generate(
            system_prompt=f"You are a helpful Indian civic eligibility explainer. {lang_note}",
            user_prompt=prompt,
            temperature=0.1,
        )
    except GeminiUnavailableError:
        return deterministic_summary
