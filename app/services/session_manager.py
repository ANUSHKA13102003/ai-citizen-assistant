"""Per-session in-memory state manager with TTL auto-expiry and strict isolation."""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from app.services.chunker import DocumentChunk
from app.services.pdf_extractor import ExtractedDocument
from app.services.vector_store import SessionVectorIndex


@dataclass
class SessionDocInfo:
    filename: str
    total_pages: int
    extracted_pages: int
    ocr_pages: int
    table_pages: int
    skipped_image_pages: int
    warnings: list[str] = field(default_factory=list)


@dataclass
class SessionState:
    session_id: str
    vector_index: SessionVectorIndex
    expires_at: datetime
    consent_given: bool = False
    file_set_hash: str = ""
    documents: list[SessionDocInfo] = field(default_factory=list)
    chunks: list[DocumentChunk] = field(default_factory=list)
    raw_texts_by_file: dict[str, str] = field(default_factory=dict)
    chat_history: list[dict[str, str]] = field(default_factory=list)
    last_summary: dict | None = None

    def touch(self, ttl_minutes: int) -> None:
        self.expires_at = datetime.now(UTC) + timedelta(minutes=ttl_minutes)

    def is_expired(self) -> bool:
        return datetime.now(UTC) > self.expires_at

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
        """Remove expired sessions and wipe their ChromaDB collections."""
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

    def update_documents(
        self,
        session_id: str,
        extracted_docs: list[ExtractedDocument],
        chunks: list[DocumentChunk],
        file_hashes: list[str],
    ) -> tuple[SessionState, bool]:
        """Rebuild session collection and clear chat history when file set changes."""
        state = self.get_or_create(session_id)
        combined_hash = hashlib.sha256("|".join(sorted(file_hashes)).encode("utf-8")).hexdigest()
        file_set_changed = combined_hash != state.file_set_hash

        if file_set_changed:
            state.chat_history.clear()
            state.last_summary = None
            state.vector_index.rebuild(chunks)
            state.file_set_hash = combined_hash
            state.chunks = list(chunks)
            state.raw_texts_by_file = {
                doc.filename: "\n\n".join(p.text for p in doc.pages) for doc in extracted_docs
            }
            state.documents = [
                SessionDocInfo(
                    filename=doc.filename,
                    total_pages=doc.total_pages,
                    extracted_pages=len(doc.pages),
                    ocr_pages=doc.ocr_pages,
                    table_pages=doc.table_pages,
                    skipped_image_pages=doc.skipped_image_pages,
                    warnings=list(doc.warnings),
                )
                for doc in extracted_docs
            ]

        state.touch(self.ttl_minutes)
        return state, file_set_changed

    def clear_session(self, session_id: str) -> bool:
        """Delete all documents, vectors, and chat history for a session immediately."""
        with self._lock:
            state = self._sessions.pop(session_id, None)
            if state is not None:
                state.vector_index.clear()
                state.chat_history.clear()
                state.chunks.clear()
                state.raw_texts_by_file.clear()
                return True
        return False
