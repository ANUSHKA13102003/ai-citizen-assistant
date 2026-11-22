"""Per-session in-memory state manager with separate citizen vs scheme stores and deduplication."""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from app.services.chunker import DocumentChunk, chunk_documents
from app.services.doc_intel import DocumentInsight, analyze_document, build_profile
from app.services.pdf_extractor import ExtractedDocument
from app.services.vector_store import SessionVectorIndex


@dataclass
class SessionDocInfo:
    filename: str
    content_hash: str
    doc_type: str
    doc_type_label: str
    total_pages: int
    extracted_pages: int
    ocr_pages: int
    table_pages: int
    skipped_image_pages: int
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "filename": self.filename,
            "doc_type": self.doc_type,
            "doc_type_label": self.doc_type_label,
            "total_pages": self.total_pages,
            "extracted_pages": self.extracted_pages,
            "ocr_pages": self.ocr_pages,
            "table_pages": self.table_pages,
            "skipped_image_pages": self.skipped_image_pages,
            "warnings": self.warnings,
        }


@dataclass
class UploadedSchemeDoc:
    filename: str
    content_hash: str
    total_pages: int
    text: str
    pages: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "filename": self.filename,
            "total_pages": self.total_pages,
        }


@dataclass
class SessionState:
    session_id: str
    vector_index: SessionVectorIndex
    expires_at: datetime
    consent_given: bool = False
    file_set_hash: str = ""
    # Citizen document store (never mixes with scheme PDFs)
    documents: list[SessionDocInfo] = field(default_factory=list)
    extracted_docs: list[ExtractedDocument] = field(default_factory=list)
    insights: list[DocumentInsight] = field(default_factory=list)
    profile_overrides: dict = field(default_factory=dict)
    content_hashes: dict[str, str] = field(default_factory=dict)  # sha256 -> filename
    chunks: list[DocumentChunk] = field(default_factory=list)
    raw_texts_by_file: dict[str, str] = field(default_factory=dict)
    pages_by_file: dict[str, list[dict]] = field(default_factory=dict)
    # Separate uploaded scheme store
    scheme_documents: dict[str, UploadedSchemeDoc] = field(default_factory=dict)
    active_uploaded_scheme: str | None = None
    # Conversation & wizard state
    chat_history: list[dict[str, str]] = field(default_factory=list)
    last_summary: dict | None = None
    wizard_answers: dict = field(default_factory=dict)
    checked_docs: dict[str, list[str]] = field(default_factory=dict)
    language: str = "en"

    def touch(self, ttl_minutes: int) -> None:
        self.expires_at = datetime.now(UTC) + timedelta(minutes=ttl_minutes)

    def is_expired(self) -> bool:
        return datetime.now(UTC) > self.expires_at

    def get_profile(self) -> dict:
        return build_profile(self.insights, self.profile_overrides)

    def append_chat_turn(self, user_msg: str, assistant_msg: str, history_window: int = 6) -> None:
        self.chat_history.append({"role": "user", "content": user_msg})
        self.chat_history.append({"role": "model", "content": assistant_msg})
        if len(self.chat_history) > history_window:
            self.chat_history = self.chat_history[-history_window:]

    def get_history_window(self, history_window: int = 6) -> list[dict[str, str]]:
        return list(self.chat_history[-history_window:])


class SessionManager:
    """Thread-safe in-memory manager for isolated citizen sessions."""

    def __init__(
        self,
        embedding_model: str = "all-MiniLM-L6-v2",
        collection_prefix: str = "citizen_documents",
        ttl_minutes: int = 60,
    ) -> None:
        self.embedding_model = embedding_model
        self.collection_prefix = collection_prefix
        self.ttl_minutes = ttl_minutes
        self._lock = threading.Lock()
        self._sessions: dict[str, SessionState] = {}

    def purge_expired(self) -> list[str]:
        expired_ids: list[str] = []
        with self._lock:
            for sid, state in list(self._sessions.items()):
                if state.is_expired():
                    state.vector_index.clear()
                    del self._sessions[sid]
                    expired_ids.append(sid)
        return expired_ids

    def get_or_create(self, session_id: str) -> SessionState:
        self.purge_expired()
        with self._lock:
            state = self._sessions.get(session_id)
            if state is None:
                idx = SessionVectorIndex(
                    session_id=session_id,
                    embedding_model=self.embedding_model,
                    collection_prefix=self.collection_prefix,
                )
                state = SessionState(
                    session_id=session_id,
                    vector_index=idx,
                    expires_at=datetime.now(UTC) + timedelta(minutes=self.ttl_minutes),
                )
                self._sessions[session_id] = state
            else:
                state.touch(self.ttl_minutes)
            return state

    def add_or_update_citizen_docs(
        self,
        session_id: str,
        new_docs: list[tuple[ExtractedDocument, str]],
        *,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        replace: bool = False,
    ) -> tuple[SessionState, bool, list[str]]:
        """Add citizen documents with content-hash deduplication; route scheme PDFs to scheme store."""
        state = self.get_or_create(session_id)
        if replace:
            state.documents.clear()
            state.extracted_docs.clear()
            state.insights.clear()
            state.content_hashes.clear()
            state.raw_texts_by_file.clear()
            state.pages_by_file.clear()

        duplicates: list[str] = []
        added_any = False

        for doc, content_hash in new_docs:
            insight = analyze_document(doc)
            # If user uploaded a scheme guideline PDF into the general uploader, store it in scheme_documents
            if insight.doc_type == "scheme_guideline" and "scheme" in doc.filename.lower():
                self.store_scheme_doc(session_id, doc, content_hash)
                continue

            if content_hash in state.content_hashes:
                duplicates.append(doc.filename)
                continue

            # Ensure unique filename if user uploads a different file with the same name
            existing_names = {d.filename for d in state.documents}
            if doc.filename in existing_names:
                stem = doc.filename[:-4]
                doc.filename = f"{stem}_{content_hash[:6]}.pdf"
                for p in doc.pages:
                    p.filename = doc.filename
                insight = analyze_document(doc)

            state.content_hashes[content_hash] = doc.filename
            state.extracted_docs.append(doc)
            state.insights.append(insight)
            state.raw_texts_by_file[doc.filename] = "\n\n".join(p.text for p in doc.pages)
            state.pages_by_file[doc.filename] = [
                {"page": p.page, "text": p.text, "ocr": p.ocr, "has_table": p.has_table}
                for p in doc.pages
            ]
            state.documents.append(
                SessionDocInfo(
                    filename=doc.filename,
                    content_hash=content_hash,
                    doc_type=insight.doc_type,
                    doc_type_label=insight.doc_type_label,
                    total_pages=doc.total_pages,
                    extracted_pages=len(doc.pages),
                    ocr_pages=doc.ocr_pages,
                    table_pages=doc.table_pages,
                    skipped_image_pages=doc.skipped_image_pages,
                    warnings=list(doc.warnings),
                )
            )
            added_any = True

        combined_hash = hashlib.sha256(
            "|".join(sorted(state.content_hashes.keys())).encode("utf-8")
        ).hexdigest()
        file_set_changed = combined_hash != state.file_set_hash and (added_any or replace)

        if file_set_changed:
            chunks = chunk_documents(
                state.extracted_docs, chunk_size=chunk_size, chunk_overlap=chunk_overlap
            )
            state.chat_history.clear()
            state.last_summary = None
            state.vector_index.rebuild(chunks)
            state.chunks = chunks
            state.file_set_hash = combined_hash

        state.touch(self.ttl_minutes)
        return state, file_set_changed, duplicates

    def update_documents(
        self,
        session_id: str,
        extracted_docs: list[ExtractedDocument],
        chunks: list[DocumentChunk],
        file_hashes: list[str],
    ) -> tuple[SessionState, bool]:
        """Backwards-compatible full-replacement document update used by existing unit tests."""
        state = self.get_or_create(session_id)
        combined_hash = hashlib.sha256("|".join(sorted(file_hashes)).encode("utf-8")).hexdigest()
        file_set_changed = combined_hash != state.file_set_hash

        if file_set_changed:
            state.chat_history.clear()
            state.last_summary = None
            state.vector_index.rebuild(chunks)
            state.file_set_hash = combined_hash
            state.chunks = list(chunks)
            state.extracted_docs = list(extracted_docs)
            state.insights = [analyze_document(d) for d in extracted_docs]
            state.content_hashes = {
                h: d.filename for d, h in zip(extracted_docs, file_hashes, strict=False)
            }
            state.raw_texts_by_file = {
                doc.filename: "\n\n".join(p.text for p in doc.pages) for doc in extracted_docs
            }
            state.pages_by_file = {
                doc.filename: [
                    {"page": p.page, "text": p.text, "ocr": p.ocr, "has_table": p.has_table}
                    for p in doc.pages
                ]
                for doc in extracted_docs
            }
            state.documents = [
                SessionDocInfo(
                    filename=doc.filename,
                    content_hash=h,
                    doc_type=ins.doc_type,
                    doc_type_label=ins.doc_type_label,
                    total_pages=doc.total_pages,
                    extracted_pages=len(doc.pages),
                    ocr_pages=doc.ocr_pages,
                    table_pages=doc.table_pages,
                    skipped_image_pages=doc.skipped_image_pages,
                    warnings=list(doc.warnings),
                )
                for doc, ins, h in zip(
                    extracted_docs, state.insights, file_hashes, strict=False
                )
            ]

        state.touch(self.ttl_minutes)
        return state, file_set_changed

    def store_scheme_doc(
        self, session_id: str, doc: ExtractedDocument, content_hash: str
    ) -> tuple[UploadedSchemeDoc, bool]:
        """Store an uploaded scheme PDF separately from citizen documents."""
        state = self.get_or_create(session_id)
        already = any(s.content_hash == content_hash for s in state.scheme_documents.values())
        sdoc = UploadedSchemeDoc(
            filename=doc.filename,
            content_hash=content_hash,
            total_pages=doc.total_pages,
            text="\n\n".join(p.text for p in doc.pages),
            pages=[{"page": p.page, "text": p.text} for p in doc.pages],
        )
        state.scheme_documents[doc.filename] = sdoc
        state.active_uploaded_scheme = doc.filename
        state.pages_by_file[doc.filename] = sdoc.pages
        state.touch(self.ttl_minutes)
        return sdoc, already

    def clear_uploaded_scheme(self, session_id: str) -> None:
        state = self.get_or_create(session_id)
        state.active_uploaded_scheme = None

    def clear_session(self, session_id: str) -> bool:
        with self._lock:
            state = self._sessions.pop(session_id, None)
            if state is not None:
                state.vector_index.clear()
                state.chat_history.clear()
                state.chunks.clear()
                state.raw_texts_by_file.clear()
                state.pages_by_file.clear()
                state.scheme_documents.clear()
                return True
        return False
