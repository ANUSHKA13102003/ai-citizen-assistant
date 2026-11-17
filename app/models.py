"""SQLAlchemy models for operational metadata ONLY (never document content)."""

from __future__ import annotations

from datetime import UTC, datetime

from app.extensions import db


def utcnow() -> datetime:
    return datetime.now(UTC)


class SessionLog(db.Model):
    """Tracks citizen session lifecycle and aggregate document metadata."""

    __tablename__ = "session_logs"

    id = db.Column(db.String(64), primary_key=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    last_active_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    doc_count = db.Column(db.Integer, default=0, nullable=False)
    total_pages = db.Column(db.Integer, default=0, nullable=False)
    total_chunks = db.Column(db.Integer, default=0, nullable=False)
    filenames_json = db.Column(db.Text, default="[]", nullable=False)
    is_cleared = db.Column(db.Boolean, default=False, nullable=False)
    is_demo = db.Column(db.Boolean, default=False, nullable=False)

    queries = db.relationship("QueryLog", backref="session_log", lazy="dynamic")


class QueryLog(db.Model):
    """Logs aggregate query metrics and categories without storing sensitive user text."""

    __tablename__ = "query_logs"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    session_id = db.Column(
        db.String(64), db.ForeignKey("session_logs.id"), nullable=False, index=True
    )
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    mode = db.Column(db.String(32), nullable=False)  # analyze | qa | eligibility
    category = db.Column(db.String(64), nullable=False, default="General")
    language = db.Column(db.String(8), nullable=False, default="en")
    retrieval_mode = db.Column(db.String(16), nullable=False, default="hybrid")
    retrieval_latency_ms = db.Column(db.Float, nullable=False, default=0.0)
    llm_latency_ms = db.Column(db.Float, nullable=False, default=0.0)
    total_latency_ms = db.Column(db.Float, nullable=False, default=0.0)
    chunks_retrieved = db.Column(db.Integer, nullable=False, default=0)
    cited_files_json = db.Column(db.Text, default="[]", nullable=False)
    is_not_found = db.Column(db.Boolean, default=False, nullable=False)
    is_demo = db.Column(db.Boolean, default=False, nullable=False)


class FeedbackLog(db.Model):
    """Stores thumbs up/down feedback on assistant responses."""

    __tablename__ = "feedback_logs"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    session_id = db.Column(db.String(64), nullable=False, index=True)
    query_log_id = db.Column(
        db.Integer, db.ForeignKey("query_logs.id"), nullable=True, index=True
    )
    rating = db.Column(db.Integer, nullable=False)  # 1 (up) or -1 (down)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    is_demo = db.Column(db.Boolean, default=False, nullable=False)
