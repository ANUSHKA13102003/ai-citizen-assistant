"""Generate 32 fictional PDFs with distractors and 105 labelled benchmark questions."""

from __future__ import annotations

import json
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

ROOT = Path(__file__).resolve().parent.parent
EVAL_DIR = ROOT / "data" / "eval"
DOCS_DIR = EVAL_DIR / "docs"
LEGACY_EVAL_DIR = ROOT / "eval"

STUDENTS = [
    ("aarav_sharma", "Aarav Sharma", "VIT2026CS042", "Vindhya Institute of Technology", "B.Tech CSE", 86.0, 8.84, "OBC", "14-05-2004", 22, "CS601", 89),
    ("priya_verma", "Priya Verma", "LU2026EC108", "Lucknow University Faculty of Engg", "B.Tech ECE", 81.5, 8.40, "SC", "22-08-2004", 22, "EC502", 85),
    ("rohan_gupta", "Rohan Gupta", "HBTU2025ME019", "HBTU Kanpur", "B.Tech Mechanical", 74.2, 7.80, "General", "03-11-2003", 23, "ME404", 77),
    ("ananya_singh", "Ananya Singh", "BHU2026BS311", "Banaras Hindu University", "B.Sc Physics", 88.4, 9.10, "EWS", "19-01-2005", 21, "PH301", 93),
    ("mohd_zaid", "Mohd Zaid", "AMU2025CE077", "Aligarh Muslim University", "Diploma Civil", 79.0, 8.15, "OBC", "09-04-2005", 21, "CE209", 82),
    ("kavya_mishra", "Kavya Mishra", "MMMUT2026IT054", "MMMUT Gorakhpur", "B.Tech IT", 84.6, 8.70, "General", "27-07-2004", 22, "IT603", 90),
    ("dev_paswan", "Dev Paswan", "BBAU2026BA142", "BBAU Lucknow", "B.A. Economics", 68.5, 7.20, "SC", "11-12-2004", 21, "EC201", 71),
    ("neha_yadav", "Neha Yadav", "IET2026EE088", "IET Lucknow", "B.Tech Electrical", 77.8, 8.05, "OBC", "05-03-2004", 22, "EE509", 81),
]

RESUMES = [
    ("aarav_sharma", "Aarav Sharma", "CivicDoc Search", "NPTEL Cloud Computing Silver Medal", "Smart Campus Civic Hackathon 2025", "30-06-2026", "Python, Flask, ChromaDB, Docker"),
    ("priya_verma", "Priya Verma", "IoT Smart Meter Grid", "Cisco CCNA Routing Certificate", "State Electronics Expo Winner 2025", "15-07-2026", "Embedded C, Verilog, MQTT, PCB Design"),
    ("rohan_gupta", "Rohan Gupta", "Solar Thermal Desalination", "Autodesk Fusion CAD Certified", "National Robotics Trial Finalist 2024", "20-05-2025", "SolidWorks, ANSYS, MATLAB, CNC"),
    ("ananya_singh", "Ananya Singh", "Quantum Optics Simulator", "IIT Kanpur Summer Research Fellow", "INSPIRE Science Camp Gold Medalist", "10-06-2026", "Python, NumPy, SciPy, LaTeX"),
    ("mohd_zaid", "Mohd Zaid", "Rural Road GIS Mapper", "NSDC Surveyor Level-4 Certified", "District Polytechnic Best Project 2025", "31-05-2025", "AutoCAD, QGIS, Total Station, Revit"),
    ("kavya_mishra", "Kavya Mishra", "FinGuard Fraud Detector", "AWS Certified Cloud Practitioner", "Women in Tech CodeSprint Winner 2025", "25-06-2026", "Java, Spring Boot, PostgreSQL, React"),
]

INCOMES = [
    ("aarav_sharma", "Aarav Sharma", "Rajesh Sharma", "UP-INC-2026-884120", "Gautam Buddha Nagar", 180000, "12-07-2026", "11-07-2029"),
    ("priya_verma", "Priya Verma", "Mahesh Verma", "UP-INC-2026-331045", "Lucknow Sadar", 145000, "04-06-2026", "03-06-2029"),
    ("rohan_gupta", "Rohan Gupta", "Dinesh Gupta", "UP-INC-2026-559210", "Kanpur Nagar", 520000, "18-05-2026", "17-05-2029"),
    ("ananya_singh", "Ananya Singh", "Vikram Singh", "UP-INC-2026-774009", "Varanasi", 290000, "21-04-2026", "20-04-2029"),
    ("mohd_zaid", "Mohd Zaid", "Abdul Hamid", "UP-INC-2026-612398", "Aligarh", 195000, "09-03-2026", "08-03-2029"),
    ("kavya_mishra", "Kavya Mishra", "Santosh Mishra", "UP-INC-2026-908112", "Gorakhpur", 740000, "14-08-2026", "13-08-2029"),
]

CASTES = [
    ("aarav_sharma", "Aarav Sharma", "UP-CST-2025-110234", "OBC", "Other Backward Class (Non-Creamy Layer)", "Gautam Buddha Nagar"),
    ("priya_verma", "Priya Verma", "UP-CST-2025-220981", "SC", "Scheduled Caste", "Lucknow"),
    ("dev_paswan", "Dev Paswan", "UP-CST-2025-330412", "SC", "Scheduled Caste", "Lucknow"),
    ("neha_yadav", "Neha Yadav", "UP-CST-2025-440876", "OBC", "Other Backward Class", "Etawah"),
]

AADHAARS = [
    ("aarav_sharma", "Aarav Sharma", "XXXX-XXXX-4912", "201308", "SBIN0001234", "Greater Noida, Uttar Pradesh", "Male"),
    ("priya_verma", "Priya Verma", "XXXX-XXXX-7823", "226010", "BARB0LUCKNW", "Gomti Nagar, Lucknow, Uttar Pradesh", "Female"),
    ("ananya_singh", "Ananya Singh", "XXXX-XXXX-6154", "221005", "PUNB0044100", "Lanka, Varanasi, Uttar Pradesh", "Female"),
    ("kavya_mishra", "Kavya Mishra", "XXXX-XXXX-9301", "273001", "CNRB0002890", "Civil Lines, Gorakhpur, Uttar Pradesh", "Female"),
]

EXTRA_DOCS = [
    (
        "khatauni_ramesh_kisan.pdf",
        "UTTAR PRADESH BHULEKH — KHATAUNI LAND RECORD (FICTIONAL)",
        [
            "<b>Farmer Name:</b> Ramesh Kumar | <b>Father's Name:</b> Hariprasad | <b>Age:</b> 46 years",
            "<b>Village:</b> Rampur | <b>Tehsil:</b> Mohanlalganj | <b>District:</b> Lucknow, Uttar Pradesh",
            "<b>Khatauni Account No:</b> 00412 | <b>Khasra No:</b> 218M | <b>Cultivable Land Area:</b> 1.4200 Hectares",
            "<b>Land Ownership / Khatauni Record Status:</b> Verified Agricultural Landholder.",
        ],
        "Ramesh Kumar",
        "00412",
        "1.4200 Hectares",
    ),
    (
        "udid_disability_arjun.pdf",
        "UNIQUE DISABILITY ID (UDID) CERTIFICATE (FICTIONAL)",
        [
            "<b>Applicant Name:</b> Arjun Rathore | <b>Age:</b> 19 years | <b>State:</b> Uttar Pradesh",
            "<b>UDID Card Number:</b> UP1420620050098214 | <b>Disability Type:</b> Locomotor Disability",
            "<b>Disability Percentage:</b> 48% Permanent | <b>Issuing Hospital:</b> CMO Office Agra",
            "<b>Disability Certificate (UDID):</b> Verified for AICTE Saksham & Divyangjan scholarships.",
        ],
        "Arjun Rathore",
        "UP1420620050098214",
        "48%",
    ),
    (
        "fee_receipt_aarav.pdf",
        "VINDHYA INSTITUTE OF TECHNOLOGY — TUITION FEE RECEIPT (FICTIONAL)",
        [
            "<b>Receipt Number:</b> VIT-FEE-2026-7731 | <b>Date:</b> 05-07-2026",
            "<b>Student Name:</b> Aarav Sharma | <b>Roll Number:</b> VIT2026CS042 | <b>Course:</b> B.Tech CSE",
            "<b>Academic Year:</b> 2025-2026 | <b>Tuition Fee Paid:</b> Rs. 68,500",
            "<b>Payment Mode:</b> NEFT Ref UTR99201823 | <b>Status:</b> Paid in Full.",
        ],
        "Aarav Sharma",
        "VIT-FEE-2026-7731",
        "68,500",
    ),
    (
        "domicile_priya_verma.pdf",
        "GOVERNMENT OF UTTAR PRADESH — DOMICILE / RESIDENCE CERTIFICATE (FICTIONAL)",
        [
            "<b>Certificate Number:</b> UP-DOM-2025-665432 | <b>Issue Date:</b> 10-09-2025",
            "<b>Applicant Name:</b> Priya Verma | <b>Father's Name:</b> Mahesh Verma",
            "<b>Permanent Address:</b> Gomti Nagar, District Lucknow, Uttar Pradesh - 226010",
            "Certified that the applicant is a permanent resident (domicile) of Uttar Pradesh.",
        ],
        "Priya Verma",
        "UP-DOM-2025-665432",
        "Lucknow",
    ),
]


def _write_pdf(dest: Path, title: str, lines: list[str]) -> None:
    doc = SimpleDocTemplate(str(dest), pagesize=A4)
    styles = getSampleStyleSheet()
    story = [Paragraph(title, styles["Title"]), Spacer(1, 10)]
    for line in lines:
        story.append(Paragraph(line, styles["BodyText"]))
        story.append(Spacer(1, 6))
    doc.build(story)


def generate_docs() -> list[str]:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    created: list[str] = []

    for slug, name, roll, college, course, pct, cgpa, cat, dob, age, subj, smarks in STUDENTS:
        fn = f"marksheet_{slug}.pdf"
        _write_pdf(
            DOCS_DIR / fn,
            f"{college.upper()} — STATEMENT OF MARKS (FICTIONAL)",
            [
                f"<b>Student Name:</b> {name} | <b>Roll Number:</b> {roll}",
                f"<b>Course:</b> {course} | <b>Date of Birth:</b> {dob} | <b>Age:</b> {age} years",
                f"<b>Category:</b> {cat} | <b>Featured Subject:</b> {subj} ({smarks}/100)",
                f"<b>Aggregate Percentage:</b> {pct}% | <b>CGPA:</b> {cgpa} / 10 | <b>Result:</b> PASS",
                f"<b>Bonafide / Institutional Verification:</b> Certified full-time student at {college}, Uttar Pradesh.",
            ],
        )
        created.append(fn)

    for slug, name, proj, cert, award, grad_date, skills in RESUMES:
        fn = f"resume_{slug}.pdf"
        _write_pdf(
            DOCS_DIR / fn,
            f"{name.upper()} — CURRICULUM VITAE (FICTIONAL)",
            [
                f"<b>Candidate Name:</b> {name} | <b>State:</b> Uttar Pradesh",
                f"<b>Technical Skills:</b> {skills}",
                f"<b>Key Project:</b> {proj}",
                f"<b>Certifications:</b> {cert}",
                f"<b>Achievements:</b> {award}",
                f"<b>Expected Graduation Date:</b> {grad_date}",
            ],
        )
        created.append(fn)

    for slug, name, father, cert_no, tehsil, inc, issued, valid_until in INCOMES:
        fn = f"income_{slug}.pdf"
        _write_pdf(
            DOCS_DIR / fn,
            "GOVERNMENT OF UTTAR PRADESH — INCOME CERTIFICATE (FICTIONAL)",
            [
                f"<b>Certificate Number:</b> {cert_no} | <b>Issue Date:</b> {issued} | <b>Valid Until:</b> {valid_until}",
                f"<b>Applicant Name:</b> {name} | <b>Father's Name:</b> {father}",
                f"Certified that the total Annual Family Income from all sources is <b>Rs. {inc:,}</b> per annum.",
                f"<b>Issuing Authority:</b> Tehsildar Office, {tehsil}, Uttar Pradesh.",
            ],
        )
        created.append(fn)

    for slug, name, cert_no, cat_code, cat_full, dist in CASTES:
        fn = f"caste_{slug}.pdf"
        _write_pdf(
            DOCS_DIR / fn,
            "GOVERNMENT OF UTTAR PRADESH — CASTE / CATEGORY CERTIFICATE (FICTIONAL)",
            [
                f"<b>Caste Certificate Number:</b> {cert_no}",
                f"<b>Applicant Name:</b> {name} | <b>District:</b> {dist}, Uttar Pradesh",
                f"<b>Category:</b> {cat_code} ({cat_full})",
            ],
        )
        created.append(fn)

    for slug, name, masked, pin, ifsc, addr, gender in AADHAARS:
        fn = f"aadhaar_{slug}.pdf"
        _write_pdf(
            DOCS_DIR / fn,
            "UIDAI e-KYC AADHAAR EXTRACT (FICTIONAL)",
            [
                f"<b>Name:</b> {name} | <b>Gender:</b> {gender}",
                f"<b>Masked Aadhaar Number:</b> {masked} | <b>PIN Code:</b> {pin}",
                f"<b>Address:</b> {addr} - {pin}",
                f"<b>Bank Account Linked:</b> Yes (IFSC: {ifsc})",
            ],
        )
        created.append(fn)

    for fn, title, lines, *_ in EXTRA_DOCS:
        _write_pdf(DOCS_DIR / fn, title, lines)
        created.append(fn)

    return created


def build_questions() -> list[dict]:
    questions: list[dict] = []
    qid = 1

    def add_q(item: dict) -> None:
        nonlocal qid
        item["id"] = f"Q{qid:03d}"
        qid += 1
        questions.append(item)

    # 1. 28 Answerable questions across all 32 fictional documents
    for slug, name, roll, _college, _course, pct, cgpa, _cat, _dob, _age, subj, smarks in STUDENTS:
        fn = f"marksheet_{slug}.pdf"
        add_q({
            "type": "answerable",
            "question": f"What is {name}'s roll number and aggregate percentage on the marksheet?",
            "expected_substrings": [roll, f"{pct}"],
            "expected_sources": [{"filename": fn, "page": 1}],
        })
        add_q({
            "type": "answerable",
            "question": f"How many marks did {name} score in subject {subj} and what is their CGPA?",
            "expected_substrings": [str(smarks), str(cgpa)],
            "expected_sources": [{"filename": fn, "page": 1}],
        })

    for slug, name, proj, cert, _award, _grad_date, _skills in RESUMES:
        fn = f"resume_{slug}.pdf"
        add_q({
            "type": "answerable",
            "question": f"Which key project and certification are listed on {name}'s resume?",
            "expected_substrings": [proj, cert.split()[0]],
            "expected_sources": [{"filename": fn, "page": 1}],
        })

    for slug, name, _father, cert_no, _tehsil, inc, _issued, _valid_until in INCOMES:
        fn = f"income_{slug}.pdf"
        add_q({
            "type": "answerable",
            "question": f"What is the income certificate number and annual family income for {name}?",
            "expected_substrings": [cert_no, f"{inc:,}"],
            "expected_sources": [{"filename": fn, "page": 1}],
        })

    # 2. 16 Follow-up questions relying on conversation history
    for slug, name, _father, cert_no, _tehsil, inc, issued, valid_until in INCOMES:
        fn = f"income_{slug}.pdf"
        add_q({
            "type": "followup",
            "prior_history": [
                {"role": "user", "content": f"Check {name}'s income certificate {cert_no}."},
                {"role": "model", "content": f"{name}'s income certificate {cert_no} shows annual family income of Rs. {inc:,}."},
            ],
            "question": f"When was that certificate ({cert_no}) issued and until what date is it valid?",
            "expected_substrings": [issued, valid_until],
            "expected_sources": [{"filename": fn, "page": 1}],
        })

    for slug, name, proj, _cert, award, grad_date, _skills in RESUMES:
        fn = f"resume_{slug}.pdf"
        add_q({
            "type": "followup",
            "prior_history": [
                {"role": "user", "content": f"Tell me about {name}'s resume and project {proj}."},
                {"role": "model", "content": f"{name} built {proj}."},
            ],
            "question": f"Which achievement or award did {name} win and when do they graduate?",
            "expected_substrings": [award.split()[0], grad_date],
            "expected_sources": [{"filename": fn, "page": 1}],
        })

    for slug, name, masked, pin, ifsc, _addr, _gender in AADHAARS:
        fn = f"aadhaar_{slug}.pdf"
        add_q({
            "type": "followup",
            "prior_history": [
                {"role": "user", "content": f"What is {name}'s masked Aadhaar number?"},
                {"role": "model", "content": f"{name}'s masked Aadhaar number is {masked}."},
            ],
            "question": f"Which bank IFSC code and PIN code are linked to {name}'s Aadhaar ({masked})?",
            "expected_substrings": [ifsc, pin],
            "expected_sources": [{"filename": fn, "page": 1}],
        })

    # 3. 20 Deliberately-absent ('Not Found') questions
    absent_topics = [
        "What is Aarav Sharma's Indian Passport number?",
        "What is Priya Verma's blood group?",
        "What score did Rohan Gupta get in GATE 2026?",
        "What is Ananya Singh's driving license number?",
        "What is Mohd Zaid's voter ID EPIC number?",
        "Which hostel room number does Kavya Mishra live in?",
        "What is Dev Paswan's JEE Advanced All India Rank?",
        "What is Neha Yadav's mother's maiden name?",
        "What is Aarav Sharma's savings bank account balance in rupees?",
        "Which hospital was Priya Verma born in?",
        "What was Rohan Gupta's Class X Sanskrit score?",
        "What is Ananya Singh's TOEFL score?",
        "What is Mohd Zaid's ration card number?",
        "Which international airline ticket is booked for Kavya Mishra?",
        "What is Ramesh Kumar's tractor registration number?",
        "What is Arjun Rathore's NEET UG percentile?",
        "What is Rajesh Sharma's personal email address?",
        "What is the credit card limit of Aarav Sharma?",
        "Which foreign university admitted Priya Verma for MS?",
        "What is the electricity consumer number on the marksheet?",
    ]
    for topic in absent_topics:
        add_q({
            "type": "not_found",
            "question": topic,
            "expected_substrings": [],
            "expected_sources": [],
        })

    # 4. 41 Scheme Eligibility Checklist Comparison questions against real schemes
    scheme_cases = [
        ("nsp_central_sector", ["marksheet_aarav_sharma.pdf", "income_aarav_sharma.pdf", "aadhaar_aarav_sharma.pdf"]),
        ("nsp_central_sector", ["marksheet_aarav_sharma.pdf"]),
        ("nsp_central_sector", ["income_aarav_sharma.pdf"]),
        ("nsp_central_sector", ["marksheet_ananya_singh.pdf", "income_ananya_singh.pdf", "aadhaar_ananya_singh.pdf"]),
        ("pms_sc_central", ["marksheet_priya_verma.pdf", "income_priya_verma.pdf", "caste_priya_verma.pdf", "aadhaar_priya_verma.pdf"]),
        ("pms_sc_central", ["marksheet_priya_verma.pdf", "caste_priya_verma.pdf"]),
        ("pms_sc_central", ["marksheet_dev_paswan.pdf", "caste_dev_paswan.pdf"]),
        ("pm_yasasvi", ["marksheet_aarav_sharma.pdf", "income_aarav_sharma.pdf", "caste_aarav_sharma.pdf", "aadhaar_aarav_sharma.pdf", "fee_receipt_aarav.pdf"]),
        ("pm_yasasvi", ["marksheet_neha_yadav.pdf", "caste_neha_yadav.pdf"]),
        ("pm_yasasvi", ["marksheet_mohd_zaid.pdf", "income_mohd_zaid.pdf"]),
        ("aicte_pragati", ["marksheet_priya_verma.pdf", "income_priya_verma.pdf", "aadhaar_priya_verma.pdf"]),
        ("aicte_pragati", ["marksheet_kavya_mishra.pdf", "income_kavya_mishra.pdf", "aadhaar_kavya_mishra.pdf"]),
        ("aicte_pragati", ["marksheet_priya_verma.pdf"]),
        ("aicte_saksham", ["udid_disability_arjun.pdf", "marksheet_aarav_sharma.pdf", "income_aarav_sharma.pdf", "aadhaar_aarav_sharma.pdf"]),
        ("aicte_saksham", ["udid_disability_arjun.pdf"]),
        ("nmmss_central", ["marksheet_aarav_sharma.pdf", "income_aarav_sharma.pdf", "aadhaar_aarav_sharma.pdf"]),
        ("nmmss_central", ["income_priya_verma.pdf"]),
        ("pm_usp_csis", ["marksheet_aarav_sharma.pdf", "income_aarav_sharma.pdf", "aadhaar_aarav_sharma.pdf", "fee_receipt_aarav.pdf"]),
        ("pm_usp_csis", ["marksheet_rohan_gupta.pdf", "income_rohan_gupta.pdf"]),
        ("pm_vidyalaxmi", ["marksheet_aarav_sharma.pdf", "income_aarav_sharma.pdf", "aadhaar_aarav_sharma.pdf", "fee_receipt_aarav.pdf"]),
        ("pm_vidyalaxmi", ["marksheet_kavya_mishra.pdf", "income_kavya_mishra.pdf"]),
        ("pmkvy_skill_india", ["marksheet_mohd_zaid.pdf", "aadhaar_aarav_sharma.pdf"]),
        ("pmkvy_skill_india", ["marksheet_dev_paswan.pdf"]),
        ("naps_apprenticeship", ["marksheet_rohan_gupta.pdf", "aadhaar_aarav_sharma.pdf"]),
        ("pm_vishwakarma", ["aadhaar_aarav_sharma.pdf", "domicile_priya_verma.pdf"]),
        ("pm_kisan", ["khatauni_ramesh_kisan.pdf", "aadhaar_aarav_sharma.pdf"]),
        ("pm_kisan", ["khatauni_ramesh_kisan.pdf"]),
        ("pm_kisan", ["marksheet_aarav_sharma.pdf"]),
        ("pm_fasal_bima", ["khatauni_ramesh_kisan.pdf", "aadhaar_aarav_sharma.pdf"]),
        ("pm_fasal_bima", ["aadhaar_priya_verma.pdf"]),
        ("ayushman_pmjay", ["aadhaar_priya_verma.pdf", "domicile_priya_verma.pdf"]),
        ("ayushman_pmjay", ["marksheet_aarav_sharma.pdf"]),
        ("pm_mudra_yojana", ["aadhaar_aarav_sharma.pdf", "domicile_priya_verma.pdf"]),
        ("up_post_matric_dashmottar", ["marksheet_priya_verma.pdf", "income_priya_verma.pdf", "caste_priya_verma.pdf", "domicile_priya_verma.pdf", "aadhaar_priya_verma.pdf"]),
        ("up_post_matric_dashmottar", ["marksheet_aarav_sharma.pdf", "income_aarav_sharma.pdf", "caste_aarav_sharma.pdf", "aadhaar_aarav_sharma.pdf", "fee_receipt_aarav.pdf"]),
        ("up_pre_matric_scholarship", ["marksheet_priya_verma.pdf", "income_priya_verma.pdf", "caste_priya_verma.pdf", "domicile_priya_verma.pdf", "aadhaar_priya_verma.pdf"]),
        ("up_kanya_sumangala", ["marksheet_priya_verma.pdf", "income_priya_verma.pdf", "domicile_priya_verma.pdf", "aadhaar_priya_verma.pdf"]),
        ("up_abhyuday_coaching", ["marksheet_ananya_singh.pdf", "aadhaar_ananya_singh.pdf", "domicile_priya_verma.pdf"]),
        ("up_swami_vivekananda_tablet", ["marksheet_aarav_sharma.pdf", "income_aarav_sharma.pdf", "aadhaar_aarav_sharma.pdf", "fee_receipt_aarav.pdf", "domicile_priya_verma.pdf"]),
        ("up_cm_yuva_udyami", ["marksheet_mohd_zaid.pdf", "aadhaar_aarav_sharma.pdf", "domicile_priya_verma.pdf"]),
        ("up_krishak_durghatna_kalyan", ["khatauni_ramesh_kisan.pdf", "aadhaar_aarav_sharma.pdf", "domicile_priya_verma.pdf"]),
    ]

    for scheme_id, c_docs in scheme_cases:
        add_q({
            "type": "scheme",
            "scheme_id": scheme_id,
            "citizen_docs": c_docs,
            "question": f"Check available vs missing documents for scheme {scheme_id} given {', '.join(c_docs)}.",
            "expected_sources": [{"filename": c_docs[0], "page": 1}],
        })

    return questions


def main() -> None:
    docs = generate_docs()
    questions = build_questions()
    payload = {
        "metadata": {
            "description": f"{len(questions)} benchmark questions across {len(docs)} fictional citizen documents with distractors",
            "document_count": len(docs),
            "question_count": len(questions),
        },
        "questions": questions,
    }
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    (EVAL_DIR / "questions.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if LEGACY_EVAL_DIR.exists():
        (LEGACY_EVAL_DIR / "questions.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )
    print(f"Generated {len(docs)} fictional PDFs in {DOCS_DIR} and {len(questions)} questions.")


if __name__ == "__main__":
    main()
