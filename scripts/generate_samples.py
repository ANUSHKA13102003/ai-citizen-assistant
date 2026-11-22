"""Generate realistic synthetic citizen PDFs (made-up individuals ONLY) for testing & eval."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parent.parent
SAMPLES_DIR = ROOT / "data" / "samples"


def generate_marksheet(dest: Path) -> None:
    doc = SimpleDocTemplate(str(dest), pagesize=A4)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("VINDHYA INSTITUTE OF TECHNOLOGY (SYNTHETIC TEST DOCUMENT)", styles["Title"]),
        Paragraph("Statement of Marks — B.Tech Computer Science & Engineering (Semester VI)", styles["Heading2"]),
        Spacer(1, 8),
        Paragraph("<b>Student Name:</b> Aarav Sharma | <b>Roll Number:</b> VIT2026CS042", styles["BodyText"]),
        Paragraph("<b>Father's Name:</b> Rajesh Sharma | <b>Date of Birth:</b> 14-05-2004 | <b>Age:</b> 22 years", styles["BodyText"]),
        Paragraph("<b>Category:</b> OBC-NCL | <b>Exam Session:</b> May 2026", styles["BodyText"]),
        Spacer(1, 12),
    ]
    data = [
        ["Course Code", "Subject Title", "Credits", "Marks Obtained", "Max Marks", "Grade"],
        ["CS601", "Artificial Intelligence & RAG", "4", "89", "100", "A+"],
        ["CS602", "Database Management Systems", "4", "84", "100", "A"],
        ["CS603", "Computer Networks", "4", "79", "100", "A"],
        ["CS604", "Software Engineering", "3", "86", "100", "A+"],
        ["CS605", "Cloud & DevOps Lab", "2", "92", "100", "O"],
    ]
    tbl = Table(data, hAlign="LEFT")
    tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F2942")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("PADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(tbl)
    story.append(Spacer(1, 12))
    story.append(
        Paragraph(
            "<b>Total Marks Obtained:</b> 430 / 500 | <b>Aggregate Percentage:</b> 86.0% | <b>CGPA:</b> 8.84 / 10 | <b>Result:</b> PASS (First Division with Distinction)",
            styles["BodyText"],
        )
    )
    story.append(Spacer(1, 8))
    story.append(
        Paragraph(
            "<b>Bonafide / Institutional Verification:</b> Certified that Aarav Sharma is a bonafide full-time student enrolled in B.Tech CSE (2022-2026). Issue Date: 20-06-2026.",
            styles["BodyText"],
        )
    )
    doc.build(story)


def generate_resume(dest: Path) -> None:
    doc = SimpleDocTemplate(str(dest), pagesize=A4)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("AARAV SHARMA (SYNTHETIC TEST RESUME)", styles["Title"]),
        Paragraph(
            "Email: aarav.sharma.demo@example.in | Phone: +91-90000-12345 | City: Greater Noida, Uttar Pradesh",
            styles["BodyText"],
        ),
        Spacer(1, 10),
        Paragraph("Education", styles["Heading2"]),
        Paragraph(
            "1. B.Tech in Computer Science & Engineering, Vindhya Institute of Technology (2022 - 2026) — CGPA: 8.84/10 (86.0%).",
            styles["BodyText"],
        ),
        Paragraph(
            "2. Class XII (CBSE), Saraswati Public School, Lucknow (2022) — Percentage: 91.4%.",
            styles["BodyText"],
        ),
        Spacer(1, 8),
        Paragraph("Technical Skills", styles["Heading2"]),
        Paragraph(
            "Python, Flask, SQL, Retrieval-Augmented Generation (RAG), ChromaDB, LangChain, Docker, HTML/Tailwind CSS, Git.",
            styles["BodyText"],
        ),
        Spacer(1, 8),
        Paragraph("Certifications", styles["Heading2"]),
        Paragraph(
            "- NPTEL Cloud Computing Silver Medal (Oct 2025)<br/>"
            "- Google Data Analytics Professional Certificate (Jan 2025)<br/>"
            "- AWS Academy Cloud Foundations (Aug 2024)",
            styles["BodyText"],
        ),
        PageBreak(),
        Paragraph("Projects", styles["Heading2"]),
        Paragraph(
            "1. CivicDoc Search: Built an offline PDF search assistant using MiniLM embeddings and SQLite metadata tracking (Mar 2026).<br/>"
            "2. GramSeva Portal: Responsive bilingual grievance tracker built with Flask and Chart.js (Nov 2025).",
            styles["BodyText"],
        ),
        Spacer(1, 8),
        Paragraph("Achievements", styles["Heading2"]),
        Paragraph(
            "- Winner, Smart Campus Civic Hackathon 2025 (1st among 45 teams).<br/>"
            "- Awarded Merit Scholarship Certificate for Academic Excellence in 2024.",
            styles["BodyText"],
        ),
        Spacer(1, 8),
        Paragraph("Important Dates", styles["Heading2"]),
        Paragraph(
            "- Expected B.Tech Graduation: 30-06-2026<br/>"
            "- Scholarship Renewal Deadline: 31-10-2026<br/>"
            "- Summer Internship Tenure: 01-06-2025 to 31-07-2025",
            styles["BodyText"],
        ),
    ]
    doc.build(story)


def generate_income_certificate(dest: Path) -> None:
    doc = SimpleDocTemplate(str(dest), pagesize=A4)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("GOVERNMENT OF UTTAR PRADESH — INCOME CERTIFICATE (SYNTHETIC SAMPLE)", styles["Title"]),
        Spacer(1, 10),
        Paragraph("<b>Certificate Number:</b> UP-INC-2026-884120 | <b>Issue Date:</b> 12-07-2026", styles["BodyText"]),
        Paragraph("<b>Valid Until:</b> 11-07-2029 (3 years from date of issue)", styles["BodyText"]),
        Spacer(1, 8),
        Paragraph(
            "This is to certify that the total Annual Family Income of Shri Rajesh Sharma, father of Aarav Sharma, "
            "resident of Sector Gamma-II, Greater Noida, Gautam Buddha Nagar, Uttar Pradesh, from all sources is "
            "<b>Rs. 1,80,000</b> (Rupees One Lakh Eighty Thousand only) per annum.",
            styles["BodyText"],
        ),
        Spacer(1, 8),
        Paragraph("<b>Issuing Authority:</b> Office of the Tehsildar, Sadar, Gautam Buddha Nagar (Digitally Verified Sample).", styles["BodyText"]),
    ]
    doc.build(story)


def generate_aadhaar_extract(dest: Path) -> None:
    doc = SimpleDocTemplate(str(dest), pagesize=A4)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("UNIQUE IDENTIFICATION AUTHORITY SAMPLE — AADHAAR CARD EXTRACT (SYNTHETIC)", styles["Title"]),
        Spacer(1, 10),
        Paragraph("<b>Name:</b> Aarav Sharma | <b>DOB:</b> 14/05/2004 | <b>Gender:</b> Male", styles["BodyText"]),
        Paragraph("<b>Masked Aadhaar Number:</b> XXXX-XXXX-4912", styles["BodyText"]),
        Paragraph("<b>Address:</b> H.No. 42, Sector Gamma-II, Greater Noida, Uttar Pradesh - 201308", styles["BodyText"]),
        Paragraph("<b>UIDAI e-KYC Status:</b> Verified | <b>Bank Account Linked:</b> Yes (State Bank Sample IFSC: SBIN0001234)", styles["BodyText"]),
    ]
    doc.build(story)


def main() -> None:
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    generate_marksheet(SAMPLES_DIR / "sample_citizen_marksheet.pdf")
    generate_resume(SAMPLES_DIR / "sample_citizen_resume.pdf")
    generate_income_certificate(SAMPLES_DIR / "sample_income_certificate.pdf")
    generate_aadhaar_extract(SAMPLES_DIR / "sample_aadhaar_extract.pdf")
    print("Generated synthetic citizen sample PDFs in", SAMPLES_DIR)


if __name__ == "__main__":
    main()
