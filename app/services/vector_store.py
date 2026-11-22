"""Cached MiniLM embedder, per-session ChromaDB vector store, and hybrid BM25+RRF retrieval."""

from __future__ import annotations

import logging
import math
import os
import re
import threading
from dataclasses import dataclass
from typing import Any

from rank_bm25 import BM25Okapi

from app.services.chunker import DocumentChunk

logger = logging.getLogger(__name__)

_EMBEDDER_LOCK = threading.Lock()
_EMBEDDER_CACHE: dict[str, Any] = {}
_RERANKER_LOCK = threading.Lock()
_RERANKER_CACHE: dict[str, Any] = {}
_CHROMA_CLIENT_LOCK = threading.Lock()
_CHROMA_CLIENT: Any = None


def get_embeddings_backend() -> str:
    return os.getenv("EMBEDDINGS_BACKEND", "local").strip().lower() or "local"


def get_embedder(model_name: str = "all-MiniLM-L6-v2") -> Any:
    """Lazy-load and cache SentenceTransformer once (local dev/eval only)."""
    from sentence_transformers import SentenceTransformer

    with _EMBEDDER_LOCK:
        if model_name not in _EMBEDDER_CACHE:
            logger.info("Loading embedding model %s ...", model_name)
            try:
                _EMBEDDER_CACHE[model_name] = SentenceTransformer(
                    model_name, local_files_only=True
                )
            except Exception:
                _EMBEDDER_CACHE[model_name] = SentenceTransformer(model_name)
        return _EMBEDDER_CACHE[model_name]


def get_reranker(
    model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
) -> Any | None:
    """Lazily load optional CrossEncoder reranker; degrade gracefully if unavailable."""
    with _RERANKER_LOCK:
        if model_name not in _RERANKER_CACHE:
            try:
                from sentence_transformers import CrossEncoder

                _RERANKER_CACHE[model_name] = CrossEncoder(model_name)
            except Exception as exc:
                logger.warning("CrossEncoder %s unavailable (%s); skipping rerank.", model_name, exc)
                _RERANKER_CACHE[model_name] = None
        return _RERANKER_CACHE[model_name]


def get_chroma_client() -> Any:
    """Return shared in-memory EphemeralClient so document text is never written to disk."""
    import chromadb
    from chromadb.config import Settings

    global _CHROMA_CLIENT
    with _CHROMA_CLIENT_LOCK:
        if _CHROMA_CLIENT is None:
            _CHROMA_CLIENT = chromadb.EphemeralClient(
                settings=Settings(anonymized_telemetry=False)
            )
        return _CHROMA_CLIENT


def collection_name_for_session(session_id: str, prefix: str = "citizen_documents") -> str:
    """Map a session id to a valid ChromaDB collection name (base: 'citizen_documents')."""
    if not session_id or session_id == "default":
        return prefix
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", session_id)[:40]
    name = f"{prefix}_{safe}".strip("_")
    if len(name) < 3:
        name = f"{prefix}_sess"
    return name


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9\u0900-\u097F]+", (text or "").lower())


@dataclass
class RetrievedChunk:
    chunk_id: str
    text: str
    filename: str
    page: int
    score: float
    ocr: bool = False
    has_table: bool = False


class SessionVectorIndex:
    """Per-session ChromaDB collection paired with BM25 lexical index."""

    def __init__(
        self,
        session_id: str,
        embedding_model: str = "all-MiniLM-L6-v2",
        collection_prefix: str = "citizen_documents",
        backend: str | None = None,
    ) -> None:
        self.session_id = session_id
        self.embedding_model = embedding_model
        self.collection_name = collection_name_for_session(session_id, collection_prefix)
        self.backend = (backend or get_embeddings_backend()).lower()
        self._client: Any = None
        self.chunks: list[DocumentChunk] = []
        self._chunk_map: dict[str, DocumentChunk] = {}
        self._bm25: BM25Okapi | None = None
        self._tokenized_corpus: list[list[str]] = []
        self._gemini_embeddings: list[list[float]] = []

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = get_chroma_client()
        return self._client

    def rebuild(self, chunks: list[DocumentChunk]) -> int:
        """Drop previous collection for this session and index new chunks."""
        self.clear()
        self.chunks = list(chunks)
        self._chunk_map = {c.chunk_id: c for c in self.chunks}
        if not self.chunks:
            return 0

        self._tokenized_corpus = [_tokenize(c.text) for c in self.chunks]
        if any(self._tokenized_corpus):
            self._bm25 = BM25Okapi(self._tokenized_corpus)

        if self.backend == "gemini":
            return len(self.chunks)

        embedder = get_embedder(self.embedding_model)
        texts = [c.text for c in self.chunks]
        embeddings = embedder.encode(texts, normalize_embeddings=True).tolist()

        collection = self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        batch_size = 200
        for start in range(0, len(self.chunks), batch_size):
            batch = self.chunks[start : start + batch_size]
            collection.add(
                ids=[c.chunk_id for c in batch],
                documents=[c.text for c in batch],
                embeddings=embeddings[start : start + batch_size],
                metadatas=[c.to_metadata() for c in batch],
            )
        return len(self.chunks)

    def clear(self) -> None:
        """Delete the session's ChromaDB collection and reset lexical state."""
        if self._client is not None:
            try:
                self._client.delete_collection(name=self.collection_name)
            except Exception:
                pass
        self.chunks = []
        self._chunk_map = {}
        self._bm25 = None
        self._tokenized_corpus = []
        self._gemini_embeddings = []

    def count(self) -> int:
        return len(self.chunks)

    def retrieve(
        self,
        query: str,
        *,
        top_k_max: int = 20,
        mode: str = "hybrid",
        enable_reranker: bool = False,
        reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
        adaptive_k: bool = True,
    ) -> list[RetrievedChunk]:
        """Retrieve chunks using paper baseline (pure vector) or hybrid BM25+RRF (+rerank)."""
        n_total = len(self.chunks)
        if n_total == 0:
            return []

        k_paper = min(top_k_max, n_total)
        if mode == "baseline":
            return self._vector_search(query, k=k_paper)

        # Hybrid mode: adaptive k when corpus is large, still bounded by min(top_k_max, N)
        target_k = k_paper
        if adaptive_k and n_total > 12:
            query_tokens = len(_tokenize(query))
            base_k = 10 if query_tokens <= 6 else 15
            if any(
                w in query.lower()
                for w in ["scheme", "eligible", "missing", "available", "all", "list", "compare"]
            ):
                base_k = top_k_max
            target_k = min(base_k, k_paper)

        candidate_pool = min(max(target_k * 2, 20), n_total)
        vec_hits = self._vector_search(query, k=candidate_pool)
        bm25_hits = self._bm25_search(query, k=candidate_pool)

        fused = self._reciprocal_rank_fusion(vec_hits, bm25_hits, k_rrf=60)
        results = fused[: max(target_k, min(15, n_total)) if enable_reranker else target_k]

        if enable_reranker and len(results) > 1:
            reranker = get_reranker(reranker_model)
            if reranker is not None:
                pairs = [[query, item.text] for item in results]
                scores = reranker.predict(pairs)
                for item, r_score in zip(results, scores, strict=True):
                    item.score = float(r_score)
                results.sort(key=lambda x: x.score, reverse=True)

        return results[:target_k]

    def _gemini_embed_texts(self, texts: list[str]) -> list[list[float]]:
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key or not texts:
            return []
        try:
            from google import genai

            client = genai.Client(api_key=api_key)
            resp = client.models.embed_content(model="gemini-embedding-001", contents=texts)
            embs = getattr(resp, "embeddings", None) or []
            return [list(e.values) for e in embs if getattr(e, "values", None)]
        except Exception as exc:
            logger.warning("Gemini embeddings unavailable (%s); using lexical BM25 fallback.", exc)
            return []

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b, strict=False))
        na = math.sqrt(sum(x * x for x in a)) or 1.0
        nb = math.sqrt(sum(y * y for y in b)) or 1.0
        return dot / (na * nb)

    def _vector_search(self, query: str, k: int) -> list[RetrievedChunk]:
        if k <= 0 or not self.chunks:
            return []
        if self.backend == "gemini":
            if not self._gemini_embeddings:
                self._gemini_embeddings = self._gemini_embed_texts([c.text for c in self.chunks])
            q_vecs = self._gemini_embed_texts([query]) if self._gemini_embeddings else []
            if not q_vecs or len(self._gemini_embeddings) != len(self.chunks):
                return self._bm25_search(query, k=k)
            qv = q_vecs[0]
            scored = [
                (self._cosine(qv, dv), c) for dv, c in zip(self._gemini_embeddings, self.chunks, strict=True)
            ]
            scored.sort(key=lambda x: x[0], reverse=True)
            return [
                RetrievedChunk(
                    chunk_id=c.chunk_id,
                    text=c.text,
                    filename=c.filename,
                    page=c.page,
                    score=float(sim),
                    ocr=c.ocr,
                    has_table=c.has_table,
                )
                for sim, c in scored[:k]
            ]

        collection = self.client.get_collection(name=self.collection_name)
        embedder = get_embedder(self.embedding_model)
        query_emb = embedder.encode([query], normalize_embeddings=True).tolist()
        res = collection.query(
            query_embeddings=query_emb,
            n_results=min(k, len(self.chunks)),
            include=["documents", "metadatas", "distances"],
        )
        ids = (res.get("ids") or [[]])[0]
        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]

        hits: list[RetrievedChunk] = []
        for cid, text, meta, dist in zip(ids, docs, metas, dists, strict=True):
            # cosine distance in [0, 2] -> similarity score in [-1, 1]
            sim = 1.0 - float(dist)
            hits.append(
                RetrievedChunk(
                    chunk_id=cid,
                    text=text,
                    filename=str(meta.get("filename", "")),
                    page=int(meta.get("page", 1)),
                    score=sim,
                    ocr=bool(meta.get("ocr", False)),
                    has_table=bool(meta.get("has_table", False)),
                )
            )
        return hits

    def _bm25_search(self, query: str, k: int) -> list[RetrievedChunk]:
        if not self._bm25 or k <= 0:
            return []
        q_tokens = _tokenize(query)
        if not q_tokens:
            return []
        scores = self._bm25.get_scores(q_tokens)
        ranked_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:k]
        hits: list[RetrievedChunk] = []
        for idx in ranked_indices:
            if scores[idx] <= 0:
                continue
            chunk = self.chunks[idx]
            hits.append(
                RetrievedChunk(
                    chunk_id=chunk.chunk_id,
                    text=chunk.text,
                    filename=chunk.filename,
                    page=chunk.page,
                    score=float(scores[idx]),
                    ocr=chunk.ocr,
                    has_table=chunk.has_table,
                )
            )
        return hits

    @staticmethod
    def _reciprocal_rank_fusion(
        vec_hits: list[RetrievedChunk],
        bm25_hits: list[RetrievedChunk],
        k_rrf: int = 60,
    ) -> list[RetrievedChunk]:
        scores: dict[str, float] = {}
        by_id: dict[str, RetrievedChunk] = {}

        for rank, item in enumerate(vec_hits, start=1):
            by_id[item.chunk_id] = item
            scores[item.chunk_id] = scores.get(item.chunk_id, 0.0) + 1.0 / (k_rrf + rank)

        for rank, item in enumerate(bm25_hits, start=1):
            if item.chunk_id not in by_id:
                by_id[item.chunk_id] = item
            scores[item.chunk_id] = scores.get(item.chunk_id, 0.0) + 1.0 / (k_rrf + rank)

        ordered_ids = sorted(scores, key=lambda cid: scores[cid], reverse=True)
        fused: list[RetrievedChunk] = []
        for cid in ordered_ids:
            chunk = by_id[cid]
            fused.append(
                RetrievedChunk(
                    chunk_id=chunk.chunk_id,
                    text=chunk.text,
                    filename=chunk.filename,
                    page=chunk.page,
                    score=scores[cid],
                    ocr=chunk.ocr,
                    has_table=chunk.has_table,
                )
            )
        return fused
