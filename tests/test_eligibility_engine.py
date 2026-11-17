"""Tests for the deterministic Python eligibility rules engine."""

from __future__ import annotations

from app.services.eligibility_engine import evaluate_eligibility

SCHEME_TEXT = """
NSP Post-Matric Scholarship Guidelines
Eligibility Criteria:
Applicants must have secured minimum 60% marks in the qualifying examination.
Annual family income must not exceed Rs. 4,50,000 per annum.
Age between 17 to 30 years.
Required Documents:
1) Aadhaar Card
2) Income Certificate
3) Academic Marksheet / Transcript
4) Caste / Category Certificate
"""


def test_eligibility_engine_available_vs_missing_and_verdict():
    citizen_docs = {
        "citizen_marksheet.pdf": "Student Age: 21 years. Aggregate Percentage: 86.0%. Statement of Marks.",
        "income_cert.pdf": "Annual Family Income is Rs. 1,80,000 per annum issued by Tehsildar.",
    }
    res = evaluate_eligibility(
        scheme_name="NSP Post-Matric",
        scheme_text=SCHEME_TEXT,
        citizen_texts_by_file=citizen_docs,
        gemini=None,
    )
    assert res["rule_based_verdict"] == "CONDITIONALLY ELIGIBLE (DOCUMENTS MISSING)"
    avail_names = {d["document"]: d["supporting_filename"] for d in res["available_documents"]}
    assert avail_names["Academic Marksheet / Transcript"] == "citizen_marksheet.pdf"
    assert avail_names["Income Certificate"] == "income_cert.pdf"
    assert "Aadhaar Card" in res["missing_documents"]
    assert "Caste / Category Certificate" in res["missing_documents"]

    statuses = {c["criterion"]: c["status"] for c in res["criteria_checks"]}
    assert statuses["Minimum Marks / Percentage"] == "PASS"
    assert statuses["Annual Family Income Ceiling"] == "PASS"
    assert statuses["Age Requirement"] == "PASS"


def test_eligibility_engine_not_eligible_when_income_exceeds_cap():
    citizen_docs = {
        "citizen_marksheet.pdf": "Age: 20 years. Aggregate Percentage: 82.0%. Marksheet.",
        "income_cert.pdf": "Annual Family Income is Rs. 6,00,000 per annum.",
        "aadhaar.pdf": "UIDAI Aadhaar Card verified.",
        "caste_cert.pdf": "OBC Caste Certificate.",
    }
    res = evaluate_eligibility(
        scheme_name="NSP Post-Matric",
        scheme_text=SCHEME_TEXT,
        citizen_texts_by_file=citizen_docs,
        gemini=None,
    )
    assert res["rule_based_verdict"] == "NOT ELIGIBLE"
    assert res["missing_documents"] == []
