"""Seed or clear clearly-marked demo analytics logs in SQLite (--seed-demo / --clear-demo)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import FeedbackLog, QueryLog, SessionLog  # noqa: E402


def clear_demo_data() -> int:
    fb_del = FeedbackLog.query.filter_by(is_demo=True).delete()
    q_del = QueryLog.query.filter_by(is_demo=True).delete()
    s_del = SessionLog.query.filter_by(is_demo=True).delete()
    db.session.commit()
    return fb_del + q_del + s_del


def seed_demo_data() -> None:
    clear_demo_data()
    now = datetime.now(UTC)
    demo_sessions = [
        ("demo-sess-01", 3, 7, 34, [{"filename": "sample_citizen_marksheet.pdf", "pages": 1}, {"filename": "sample_citizen_resume.pdf", "pages": 2}, {"filename": "scheme_nsp_post_matric.pdf", "pages": 1}], 5),
        ("demo-sess-02", 2, 3, 18, [{"filename": "sample_income_certificate.pdf", "pages": 1}, {"filename": "scheme_aicte_pragati.pdf", "pages": 1}], 3),
        ("demo-sess-03", 2, 2, 12, [{"filename": "sample_aadhaar_extract.pdf", "pages": 1}, {"filename": "scheme_pm_kisan.pdf", "pages": 1}], 1),
    ]
    for sid, doc_c, pages, chunks, files, days_ago in demo_sessions:
        ts = now - timedelta(days=days_ago)
        db.session.add(
            SessionLog(
                id=sid,
                created_at=ts,
                last_active_at=ts,
                expires_at=ts + timedelta(hours=1),
                doc_count=doc_c,
                total_pages=pages,
                total_chunks=chunks,
                filenames_json=json.dumps(files),
                is_cleared=False,
                is_demo=True,
            )
        )
    db.session.commit()

    demo_queries = [
        ("demo-sess-01", 5, "qa", "Education & Marksheets", "en", "hybrid", 14.2, 610.5, 624.7, 10, [{"filename": "sample_citizen_marksheet.pdf", "page": 1}], False),
        ("demo-sess-01", 5, "qa", "Scholarship / Scheme", "en", "hybrid", 16.8, 720.1, 736.9, 14, [{"filename": "scheme_nsp_post_matric.pdf", "page": 1}, {"filename": "sample_citizen_marksheet.pdf", "page": 1}], False),
        ("demo-sess-01", 4, "qa", "General", "en", "baseline", 11.4, 540.0, 551.4, 20, [], True),
        ("demo-sess-01", 4, "analyze", "Document Summary", "en", "all_chunks", 0.0, 980.3, 980.3, 34, [{"filename": "sample_citizen_resume.pdf", "page": 1}], False),
        ("demo-sess-02", 3, "qa", "Personal & Identity", "hi", "hybrid", 13.5, 690.4, 703.9, 10, [{"filename": "sample_income_certificate.pdf", "page": 1}], False),
        ("demo-sess-02", 2, "eligibility", "Scholarship / Scheme", "en", "deterministic", 4.1, 410.0, 414.1, 2, [{"filename": "sample_income_certificate.pdf", "page": 1}], False),
        ("demo-sess-03", 1, "qa", "Scholarship / Scheme", "en", "hybrid", 12.0, 645.2, 657.2, 12, [{"filename": "scheme_pm_kisan.pdf", "page": 1}], False),
        ("demo-sess-03", 0, "qa", "Dates & Deadlines", "en", "hybrid", 11.8, 580.6, 592.4, 10, [{"filename": "sample_citizen_resume.pdf", "page": 2}], False),
    ]
    for sid, days_ago, mode, cat, lang, rmode, r_ms, l_ms, t_ms, ch, cited, nf in demo_queries:
        ql = QueryLog(
            session_id=sid,
            created_at=now - timedelta(days=days_ago),
            mode=mode,
            category=cat,
            language=lang,
            retrieval_mode=rmode,
            retrieval_latency_ms=r_ms,
            llm_latency_ms=l_ms,
            total_latency_ms=t_ms,
            chunks_retrieved=ch,
            cited_files_json=json.dumps(cited),
            is_not_found=nf,
            is_demo=True,
        )
        db.session.add(ql)
        db.session.flush()
        db.session.add(
            FeedbackLog(
                session_id=sid,
                query_log_id=ql.id,
                rating=-1 if nf and cat == "General" else 1,
                created_at=now - timedelta(days=days_ago),
                is_demo=True,
            )
        )
    db.session.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage clearly-marked demo analytics rows.")
    parser.add_argument("--seed-demo", action="store_true", help="Insert demo analytics records.")
    parser.add_argument("--clear-demo", action="store_true", help="Delete demo analytics records.")
    args = parser.parse_args()

    app = create_app("development")
    with app.app_context():
        if args.clear_demo:
            removed = clear_demo_data()
            print(f"Cleared {removed} demo rows.")
        elif args.seed_demo:
            seed_demo_data()
            print("Seeded clearly-marked demo analytics records.")
        else:
            parser.print_help()


if __name__ == "__main__":
    main()
