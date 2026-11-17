"""Download official public Indian scheme PDFs or build clearly-labelled synthetic fallback PDFs."""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

ROOT = Path(__file__).resolve().parent.parent
SAMPLES_DIR = ROOT / "data" / "samples"

SCHEMES_SPEC = [
    {
        "id": "nsp_post_matric",
        "title": "NSP Central Sector / Post-Matric Scholarship Scheme",
        "ministry": "Ministry of Education & Ministry of Social Justice, Govt. of India",
        "category": "Scholarship",
        "filename": "scheme_nsp_post_matric.pdf",
        "source_url": "https://scholarships.gov.in/public/schemeGuidelines/CSSS_Guidelines.pdf",
        "tags": ["nsp", "scholarship", "post-matric", "students", "education"],
        "summary": "Merit-cum-means scholarship for Indian students pursuing post-matric or higher education with family income ceiling and minimum marks criteria.",
        "fallback_paragraphs": [
            "SYNTHETIC REFERENCE GUIDELINE (Modeled on National Scholarship Portal CSSS / Post-Matric Guidelines). Not an official government circular.",
            "1. Objective: To provide financial assistance to meritorious students from low-income families to meet day-to-day expenses while pursuing higher studies.",
            "2. Eligibility Criteria: (a) Applicants must have secured minimum 60% marks in the qualifying Class XII or previous semester examination. (b) Annual family income from all sources must not exceed Rs. 4,50,000 (INR 4.5 lakhs) per annum. (c) Age between 17 to 30 years as on 1st July of the academic year.",
            "3. Required Documents Checklist: 1) Aadhaar Card for e-KYC authentication. 2) Income Certificate issued by Tehsildar or competent revenue authority. 3) Academic Marksheet / Transcript of the previous qualifying examination. 4) Bank Passbook / Account Details seeded with Aadhaar. 5) Bonafide / Admission Proof verified by the institution. 6) Caste / Category Certificate (where applicable for reserved quotas).",
            "4. Disbursement & Renewal: Scholarship amount is transferred via Direct Benefit Transfer (DBT) to the Aadhaar-seeded bank account. Renewal requires maintaining at least 50% marks and 75% attendance. Last date for fresh applications is 31st October.",
        ],
    },
    {
        "id": "pm_kisan",
        "title": "PM-KISAN (Pradhan Mantri Kisan Samman Nidhi)",
        "ministry": "Ministry of Agriculture & Farmers Welfare, Govt. of India",
        "category": "Agriculture",
        "filename": "scheme_pm_kisan.pdf",
        "source_url": "https://pmkisan.gov.in/Documents/PMKisanSamanNidhi.pdf",
        "tags": ["pm-kisan", "farmer", "agriculture", "dbt", "land"],
        "summary": "Income support of Rs. 6,000 per year in three equal installments to eligible landholding farmer families across India.",
        "fallback_paragraphs": [
            "SYNTHETIC REFERENCE GUIDELINE (Modeled on PM-KISAN Operational Guidelines). Not an official government circular.",
            "1. Scheme Overview: Under PM-KISAN, financial benefit of Rs. 6,000 per annum is released in three four-monthly installments of Rs. 2,000 directly into bank accounts of eligible landholding farmer families.",
            "2. Eligibility Criteria: (a) Cultivable landholding farmer families subject to state land records. (b) Minimum age 18 years. (c) Institutional landholders, constitutional post holders, and income tax payees in the last assessment year are excluded.",
            "3. Required Documents Checklist: 1) Aadhaar Card (mandatory e-KYC). 2) Land Ownership / Khatauni Record (RoR / Khasra / Jamabandi). 3) Bank Passbook / Account Details with IFSC code. 4) Domicile / Residence Certificate or citizenship proof.",
            "4. Grievance & Verification: Farmers can verify beneficiary status on pmkisan.gov.in or at local Common Service Centres (CSC).",
        ],
    },
    {
        "id": "aicte_pragati",
        "title": "AICTE Pragati Scholarship Scheme for Technical Education",
        "ministry": "All India Council for Technical Education (AICTE)",
        "category": "Scholarship",
        "filename": "scheme_aicte_pragati.pdf",
        "source_url": "https://www.aicte-india.org/sites/default/files/Pragati_Guidelines.pdf",
        "tags": ["aicte", "pragati", "engineering", "diploma", "degree"],
        "summary": "Scholarship supporting students admitted to AICTE-approved technical degree/diploma institutions with family income below Rs. 8,00,000.",
        "fallback_paragraphs": [
            "SYNTHETIC REFERENCE GUIDELINE (Modeled on AICTE Pragati Scheme Guidelines). Not an official government circular.",
            "1. Scope: Up to 5,000 scholarships per annum for students admitted to the First Year of Degree/Diploma level courses in AICTE-approved institutions.",
            "2. Eligibility Criteria: (a) Annual family income should not exceed Rs. 8,00,000 (INR 8 lakhs) per annum. (b) Minimum 55% marks in qualifying 10th/12th examination. (c) Maximum two students per family.",
            "3. Required Documents Checklist: 1) Academic Marksheet / Transcript (10th and 12th). 2) Income Certificate issued by competent authority. 3) Bonafide / Admission Proof from AICTE-approved college. 4) Fee Receipt for current academic year. 5) Aadhaar Card. 6) Bank Passbook / Account Details.",
            "4. Benefit: Rs. 50,000 per annum for every year of study towards tuition fee, books, and equipment.",
        ],
    },
    {
        "id": "pm_yasasvi",
        "title": "PM-YASASVI Top Class College Education Scholarship",
        "ministry": "Ministry of Social Justice & Empowerment, Govt. of India",
        "category": "Scholarship",
        "filename": "scheme_pm_yasasvi.pdf",
        "source_url": "https://socialjustice.gov.in/writereaddata/UploadFile/PMYASASVI_Guidelines.pdf",
        "tags": ["yasasvi", "obc", "ebc", "dnt", "college"],
        "summary": "Financial assistance covering tuition and living allowance for OBC, EBC, and DNT students in notified top-class institutions.",
        "fallback_paragraphs": [
            "SYNTHETIC REFERENCE GUIDELINE (Modeled on PM-YASASVI Scheme Guidelines). Not an official government circular.",
            "1. Target Group: Students belonging to OBC, EBC, and DNT categories pursuing full-time graduate or postgraduate courses.",
            "2. Eligibility Criteria: (a) Total annual family income from all sources must not exceed Rs. 2,50,000 per annum. (b) Minimum 65% marks in the previous qualifying examination. (c) Age between 18 to 28 years.",
            "3. Required Documents Checklist: 1) Caste / Category Certificate (OBC/EBC/DNT). 2) Income Certificate. 3) Academic Marksheet / Transcript. 4) Bonafide / Admission Proof. 5) Fee Receipt. 6) Aadhaar Card. 7) Bank Passbook / Account Details.",
        ],
    },
    {
        "id": "ayushman_pmjay",
        "title": "Ayushman Bharat PM-JAY Citizen Health Assurance",
        "ministry": "National Health Authority (NHA), Govt. of India",
        "category": "Healthcare",
        "filename": "scheme_ayushman_pmjay.pdf",
        "source_url": "https://nha.gov.in/img/resources/PM-JAY-Guidelines.pdf",
        "tags": ["health", "ayushman", "pmjay", "hospital", "insurance"],
        "summary": "Cashless secondary and tertiary hospitalization cover up to Rs. 5,00,000 per eligible family per year across empanelled hospitals.",
        "fallback_paragraphs": [
            "SYNTHETIC REFERENCE GUIDELINE (Modeled on Ayushman Bharat PM-JAY Guidelines). Not an official government circular.",
            "1. Benefit Cover: Health coverage of Rs. 5,00,000 per family per year for secondary and tertiary care hospitalization across public and private empanelled hospitals.",
            "2. Eligibility Criteria: Families listed under SECC 2011 deprivation criteria or holding valid state health assurance ration cards, with annual family income below Rs. 2,00,000 where income cap applies.",
            "3. Required Documents Checklist: 1) Aadhaar Card for beneficiary verification. 2) Domicile / Residence Certificate or Ration Card. 3) Income Certificate (where applicable).",
        ],
    },
]


def _try_download_pdf(url: str, dest: Path) -> bool:
    """Attempt downloading a real official PDF with strict magic-byte check."""
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (AI-Citizen-Assistant-Builder)"},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = resp.read()
        if len(data) > 1024 and data.lstrip()[:8].startswith(b"%PDF-"):
            dest.write_bytes(data)
            return True
    except Exception:
        pass
    return False


def _write_synthetic_scheme_pdf(spec: dict, dest: Path) -> None:
    doc = SimpleDocTemplate(str(dest), pagesize=A4)
    styles = getSampleStyleSheet()
    story = [
        Paragraph(spec["title"], styles["Title"]),
        Paragraph(f"<b>Issuing Authority:</b> {spec['ministry']}", styles["BodyText"]),
        Paragraph(f"<b>Reference Source URL:</b> {spec['source_url']}", styles["BodyText"]),
        Spacer(1, 12),
    ]
    for para in spec["fallback_paragraphs"]:
        story.append(Paragraph(para, styles["BodyText"]))
        story.append(Spacer(1, 8))
    doc.build(story)


def main() -> None:
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    skip_network = "--offline" in sys.argv
    manifest_schemes = []

    for spec in SCHEMES_SPEC:
        dest = SAMPLES_DIR / spec["filename"]
        downloaded = False if skip_network else _try_download_pdf(spec["source_url"], dest)
        if not downloaded:
            _write_synthetic_scheme_pdf(spec, dest)
            source_type = "synthetic_reference"
        else:
            source_type = "official_download"

        manifest_schemes.append(
            {
                "id": spec["id"],
                "title": spec["title"],
                "ministry": spec["ministry"],
                "category": spec["category"],
                "filename": spec["filename"],
                "source_url": spec["source_url"],
                "source_type": source_type,
                "summary": spec["summary"],
                "tags": spec["tags"],
            }
        )
        print(f"[{source_type}] {spec['filename']}")

    manifest_path = SAMPLES_DIR / "manifest.json"
    manifest_path.write_text(
        json.dumps({"schemes": manifest_schemes}, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {manifest_path}")


if __name__ == "__main__":
    main()
