"""Document type detection and key-field extraction (with source page) for citizen documents."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from app.services.pdf_extractor import ExtractedDocument

CANONICAL_DOCUMENTS = [
    "Aadhaar Card",
    "Income Certificate",
    "Caste / Category Certificate",
    "Domicile / Residence Certificate",
    "Academic Marksheet / Transcript",
    "Bank Passbook / Account Details",
    "Bonafide / Admission Proof",
    "Fee Receipt",
    "Land Ownership / Khatauni Record",
    "PAN Card",
    "Passport Size Photograph",
    "Disability Certificate (UDID)",
    "Ration Card",
    "Birth Certificate / Age Proof",
]

# doc_type -> (label, keyword patterns, canonical documents it proves)
DOC_TYPES: dict[str, tuple[str, list[str], list[str]]] = {
    "marksheet": ("Marksheet", [r"statement of marks", r"mark\s*sheet", r"marks obtained",
                                r"grade card", r"transcript", r"\bsgpa\b", r"result\s*:\s*pass"],
                  ["Academic Marksheet / Transcript"]),
    "income_certificate": ("Income Certificate", [r"income certificate", r"annual family income",
                                                  r"\bआय प्रमाण"], ["Income Certificate"]),
    "caste_certificate": ("Caste Certificate", [r"caste certificate", r"category certificate",
                                                r"other backward class", r"scheduled caste",
                                                r"scheduled tribe", r"jati praman"],
                          ["Caste / Category Certificate"]),
    "aadhaar": ("Aadhaar", [r"aadhaar", r"\buidai\b", r"unique identification"],
                ["Aadhaar Card"]),
    "domicile_certificate": ("Domicile Certificate", [r"domicile", r"residence certificate",
                                                      r"niwas praman", r"permanent resident of"],
                             ["Domicile / Residence Certificate"]),
    "bank_passbook": ("Bank Passbook", [r"passbook", r"account statement", r"savings account",
                                        r"\bifsc\b.*account|account.*\bifsc\b"],
                      ["Bank Passbook / Account Details"]),
    "fee_receipt": ("Fee Receipt", [r"fee receipt", r"tuition fee", r"fees? paid"],
                    ["Fee Receipt"]),
    "bonafide": ("Bonafide / Admission Letter", [r"bonafide", r"admission letter",
                                                 r"provisional admission", r"is a student of"],
                 ["Bonafide / Admission Proof"]),
    "land_record": ("Land Record", [r"khatauni", r"khasra", r"jamabandi", r"land record",
                                    r"record of rights"], ["Land Ownership / Khatauni Record"]),
    "ration_card": ("Ration Card", [r"ration card", r"\bnfsa\b", r"antyodaya"], ["Ration Card"]),
    "birth_certificate": ("Birth Certificate", [r"birth certificate", r"certificate of birth"],
                          ["Birth Certificate / Age Proof"]),
    "disability_certificate": ("Disability Certificate", [r"disability certificate", r"\budid\b"],
                               ["Disability Certificate (UDID)"]),
    "pan_card": ("PAN Card", [r"permanent account number", r"\bpan card\b"], ["PAN Card"]),
    "resume": ("Resume / CV", [r"curriculum vitae", r"\bresume\b", r"technical skills",
                               r"\bprojects\b.*\bskills\b|\bskills\b.*\bprojects\b"], []),
    "scheme_guideline": ("Scheme Guideline", [r"scheme guideline", r"eligibility criteria",
                                              r"required documents", r"how to apply"], []),
}

UP_DISTRICT_HINTS = ["uttar pradesh", "lucknow", "noida", "kanpur", "varanasi", "prayagraj",
                     "agra", "meerut", "ghaziabad", "gorakhpur", "bareilly", "aligarh",
                     "gautam buddha nagar", "jhansi", "ayodhya", "मेरठ", "उत्तर प्रदेश"]
STATES = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh",
    "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka",
    "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya", "Mizoram",
    "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu",
    "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal",
    "Andaman and Nicobar Islands", "Chandigarh",
    "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Jammu and Kashmir",
    "Ladakh", "Lakshadweep", "Puducherry",
]


@dataclass
class FieldValue:
    key: str
    label: str
    value: str | float | int | None
    display: str
    filename: str = ""
    page: int = 0
    edited: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DocumentInsight:
    filename: str
    doc_type: str
    doc_type_label: str
    proves: list[str] = field(default_factory=list)
    fields: list[FieldValue] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "filename": self.filename,
            "doc_type": self.doc_type,
            "doc_type_label": self.doc_type_label,
            "proves": self.proves,
            "fields": [f.to_dict() for f in self.fields],
        }


FIELD_LABELS = {
    "name": "Name",
    "dob": "Date of birth",
    "age": "Age",
    "gender": "Gender",
    "marks_percent": "Percentage",
    "cgpa": "CGPA",
    "annual_income_inr": "Annual family income",
    "category": "Category",
    "state": "State",
    "course": "Course",
    "education_level": "Education level",
    "occupation": "Occupation",
}


def _num(s: str) -> float | None:
    try:
        return float(s.replace(",", "").strip())
    except ValueError:
        return None


def _inr(num: str, unit: str | None) -> float | None:
    val = _num(num)
    if val is None:
        return None
    u = (unit or "").lower()
    if u.startswith("lakh") or u.startswith("lac"):
        val *= 100_000
    elif u.startswith("crore") or u == "cr":
        val *= 10_000_000
    return val


def format_inr(value: float) -> str:
    v = int(round(value))
    s = str(v)
    if len(s) <= 3:
        return f"₹{s}"
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return "₹" + ",".join(parts) + "," + tail


def classify(doc: ExtractedDocument) -> tuple[str, list[str]]:
    """Return (doc_type, proven canonical documents) using filename + content keyword scores."""
    text = "\n".join(p.text for p in doc.pages).lower()
    fname = doc.filename.lower()
    best, best_score = "other", 0
    for dtype, (_label, patterns, _proves) in DOC_TYPES.items():
        score = sum(len(re.findall(p, text)) for p in patterns)
        if dtype.split("_")[0] in fname:
            score += 3
        if score > best_score:
            best, best_score = dtype, score
    proves = list(DOC_TYPES.get(best, ("", [], []))[2])
    # Secondary proof: a marksheet that embeds a bonafide certificate also proves admission.
    if best == "marksheet" and re.search(r"bonafide", text):
        proves.append("Bonafide / Admission Proof")
    if best == "aadhaar" and re.search(r"bank account linked\s*:\s*yes|\bifsc\b", text):
        proves.append("Bank Passbook / Account Details")
    return best, proves


def _first(pattern: str, doc: ExtractedDocument, flags=re.IGNORECASE):
    for page in doc.pages:
        m = re.search(pattern, page.text, flags)
        if m:
            return m, page.page
    return None, 0


def extract_fields(doc: ExtractedDocument, doc_type: str) -> list[FieldValue]:
    out: list[FieldValue] = []
    fn = doc.filename

    def add(key: str, value, display: str, page: int) -> None:
        if value is None or any(f.key == key for f in out):
            return
        out.append(FieldValue(key, FIELD_LABELS[key], value, display, fn, page))

    m, pg = _first(r"(?:student\s+name|candidate(?:'s)?\s+name|name of (?:the )?(?:student|"
                   r"applicant|candidate)|^name)\s*[:\-]\s*([A-Z][A-Za-z.]+(?:\s+[A-Z][A-Za-z.]+){0,3})",
                   doc, re.IGNORECASE | re.MULTILINE)
    if not m and doc_type == "resume":
        first_line = doc.pages[0].text.strip().splitlines()[0] if doc.pages else ""
        nm = re.match(r"([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){1,3})", first_line.title())
        if nm:
            add("name", nm.group(1), nm.group(1), doc.pages[0].page)
    if m:
        add("name", m.group(1).strip(), m.group(1).strip(), pg)

    m, pg = _first(
        r"(?:date of birth|\bdob\b)\s*[:\-]?\s*(\d{1,2}[-/.]\d{1,2}[-/.]\d{4}|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})",
        doc,
    )
    if m:
        add("dob", m.group(1), m.group(1), pg)

    m, pg = _first(r"\bage\s*[:\-]?\s*(\d{1,2})\s*(?:years|yrs)", doc)
    if m and 5 <= int(m.group(1)) <= 100:
        add("age", int(m.group(1)), f"{m.group(1)} years", pg)

    m, pg = _first(r"\bgender\s*[:\-]\s*(male|female|transgender)", doc)
    if m:
        add("gender", m.group(1).lower(), m.group(1).title(), pg)

    if doc_type in {"marksheet", "resume", "other", "bonafide"}:
        m, pg = _first(
            r"(?:aggregate|overall|total|marks|score)?\s*(?:percentage|marks)\s*[:\-]?\s*(\d{2,3}(?:\.\d{1,2})?)\s*%",
            doc,
        )
        if not m:
            m, pg = _first(r"(\d{2,3}(?:\.\d{1,2})?)\s*%\s*(?:marks|aggregate|score)", doc)
        if not m:
            m, pg = _first(r"(?:aggregate|overall|scored|obtained|marks)\D{0,20}(\d{2}(?:\.\d{1,2})?)\s*%", doc)
        if m and 0 < float(m.group(1)) <= 100:
            add("marks_percent", float(m.group(1)), f"{float(m.group(1)):g}%", pg)
        m, pg = _first(r"\bcgpa\s*[:\-]?\s*(\d{1,2}(?:\.\d{1,2})?)", doc)
        if m and 0 < float(m.group(1)) <= 10:
            add("cgpa", float(m.group(1)), f"{float(m.group(1)):g} / 10", pg)

    if doc_type in {"income_certificate", "other", "ration_card"}:
        m, pg = _first(r"(?:annual\s+(?:family\s+)?income|family\s+income|total\s+income)"
                       r".{0,160}?(?:rs\.?|inr|₹)\s*([\d,]+(?:\.\d+)?)\s*(lakhs?|lacs?|crores?)?",
                       doc, re.IGNORECASE | re.DOTALL)
        if m:
            val = _inr(m.group(1), m.group(2))
            if val and val >= 1000:
                add("annual_income_inr", val, format_inr(val), pg)

    m, pg = _first(r"\bcategory\s*[:\-]\s*(SC|ST|OBC(?:-NCL)?|EWS|General|Minority)\b", doc)
    if not m and doc_type == "caste_certificate":
        m, pg = _first(r"\b(scheduled caste|scheduled tribe|other backward class|OBC|SC|ST)\b", doc)
    if m:
        raw = m.group(1).upper()
        cat = {"SCHEDULED CASTE": "SC", "SCHEDULED TRIBE": "ST",
               "OTHER BACKWARD CLASS": "OBC"}.get(raw, raw.replace("-NCL", ""))
        cat = "General" if cat == "GENERAL" else ("Minority" if cat == "MINORITY" else cat)
        add("category", cat, cat, pg)

    full = "\n".join(p.text for p in doc.pages)
    low = full.lower()
    for st in STATES:
        if st.lower() in low:
            add("state", st, st, _first(re.escape(st), doc)[1])
            break
    else:
        for hint in UP_DISTRICT_HINTS:
            if hint in low:
                add("state", "Uttar Pradesh", "Uttar Pradesh", _first(re.escape(hint), doc)[1])
                break

    m, pg = _first(r"\b(B\.?\s?Tech|B\.?E\.|M\.?\s?Tech|B\.?Sc|M\.?Sc|B\.?Com|M\.?Com|B\.?A\.|"
                   r"M\.?A\.|BCA|MCA|MBA|MBBS|Diploma|Polytechnic|ITI|Class\s*(?:XII|XI|X|IX|12|11|10|9)"
                   r"|Intermediate|High School)\b", doc)
    if m and doc_type in {"marksheet", "bonafide", "resume", "fee_receipt", "other"}:
        course = re.sub(r"\s+", " ", m.group(1)).strip()
        add("course", course, course, pg)
        level = education_level_for(course)
        if level:
            add("education_level", level, level.replace("_", " ").title(), pg)
    return out


def education_level_for(course: str) -> str | None:
    c = course.lower().replace(".", "").replace(" ", "")
    if c in {"btech", "be", "mtech"}:
        return "technical_degree"
    if c in {"bsc", "bcom", "ba", "bca", "mbbs"}:
        return "undergraduate"
    if c in {"msc", "mcom", "ma", "mca", "mba"}:
        return "postgraduate"
    if c in {"diploma", "polytechnic", "iti"}:
        return "diploma"
    if c in {"classxii", "classxi", "class12", "class11", "intermediate"}:
        return "class_11_12"
    if c in {"classx", "classix", "class10", "class9", "highschool"}:
        return "class_9_10"
    return None


def analyze_document(doc: ExtractedDocument) -> DocumentInsight:
    dtype, proves = classify(doc)
    label = DOC_TYPES.get(dtype, ("Other document", [], []))[0]
    return DocumentInsight(doc.filename, dtype, label, proves, extract_fields(doc, dtype))


# Field priority: which document type is the authoritative source for each field.
_FIELD_SOURCE_PRIORITY = {
    "annual_income_inr": ["income_certificate"],
    "category": ["caste_certificate", "marksheet"],
    "marks_percent": ["marksheet", "resume"],
    "cgpa": ["marksheet", "resume"],
    "state": ["domicile_certificate", "aadhaar", "income_certificate"],
    "dob": ["birth_certificate", "aadhaar", "marksheet"],
}


def build_profile(insights: list[DocumentInsight], overrides: dict | None = None) -> dict:
    """Merge per-document fields into one citizen profile; user overrides always win."""
    by_type = {i.filename: i.doc_type for i in insights}
    merged: dict[str, FieldValue] = {}
    for ins in insights:
        for f in ins.fields:
            cur = merged.get(f.key)
            if cur is None:
                merged[f.key] = f
                continue
            prio = _FIELD_SOURCE_PRIORITY.get(f.key, [])
            new_rank = prio.index(ins.doc_type) if ins.doc_type in prio else 99
            cur_type = by_type.get(cur.filename, "")
            cur_rank = prio.index(cur_type) if cur_type in prio else 99
            if new_rank < cur_rank:
                merged[f.key] = f

    if "age" not in merged and "dob" in merged:
        m = re.search(r"(\d{4})$", str(merged["dob"].value))
        if m:
            from datetime import date

            age = date.today().year - int(m.group(1))
            src = merged["dob"]
            merged["age"] = FieldValue("age", "Age", age, f"{age} years (from DOB)",
                                       src.filename, src.page)

    if "marks_percent" not in merged and "cgpa" in merged:
        src = merged["cgpa"]
        pct = round(float(src.value) * 9.5, 1)
        merged["marks_percent"] = FieldValue("marks_percent", "Percentage", pct,
                                             f"{pct:g}% (CGPA × 9.5)", src.filename, src.page)

    types_present = {i.doc_type for i in insights}
    if "occupation" not in merged:
        if types_present & {"marksheet", "bonafide", "fee_receipt"}:
            merged["occupation"] = FieldValue("occupation", "Occupation", "student", "Student")
        elif "land_record" in types_present:
            merged["occupation"] = FieldValue("occupation", "Occupation", "farmer", "Farmer")

    for key, val in (overrides or {}).items():
        if key not in FIELD_LABELS:
            continue
        if val in (None, ""):
            merged.pop(key, None)
            continue
        disp = str(val)
        if key == "annual_income_inr":
            val = float(val)
            disp = format_inr(val)
        elif key in {"marks_percent", "cgpa"}:
            val = float(val)
            disp = f"{val:g}%" if key == "marks_percent" else f"{val:g} / 10"
        elif key == "age":
            val = int(float(val))
            disp = f"{val} years"
        merged[key] = FieldValue(key, FIELD_LABELS[key], val, disp, edited=True)

    documents: dict[str, str] = {}
    for ins in insights:
        for d in ins.proves:
            documents.setdefault(d, ins.filename)

    return {
        "fields": {k: v.to_dict() for k, v in merged.items()},
        "documents": documents,
        "doc_types": sorted(types_present),
    }


def profile_value(profile: dict, key: str):
    f = profile.get("fields", {}).get(key)
    return None if f is None else f.get("value")
