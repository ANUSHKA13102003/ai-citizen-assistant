"""LangChain RecursiveCharacterTextSplitter chunking matching the IEEE paper."""

from __future__ import annotations

from dataclasses import dataclass

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.services.pdf_extractor import ExtractedDocument


@dataclass
class DocumentChunk:
    chunk_id: str
    text: str
    filename: str
    page: int
    ocr: bool = False
    has_table: bool = False
    chunk_index: int = 0

    def to_metadata(self) -> dict:
        return {
            "filename": self.filename,
            "page": int(self.page),
            "ocr": bool(self.ocr),
            "has_table": bool(self.has_table),
            "chunk_index": int(self.chunk_index),
        }


def chunk_documents(
    documents: list[ExtractedDocument],
    chunk_size: int = 500,
    chunk_overlap: int = 50,
) -> list[DocumentChunk]:
    """Split extracted PDF pages into overlapping chunks while preserving file+page metadata."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    chunks: list[DocumentChunk] = []
    global_idx = 0
    for doc in documents:
        for page_content in doc.pages:
            split_texts = splitter.split_text(page_content.text)
            for part in split_texts:
                cleaned = part.strip()
                if not cleaned:
                    continue
                chunks.append(
                    DocumentChunk(
                        chunk_id=f"{doc.filename}::p{page_content.page}::c{global_idx}",
                        text=cleaned,
                        filename=doc.filename,
                        page=page_content.page,
                        ocr=page_content.ocr,
                        has_table=page_content.has_table,
                        chunk_index=global_idx,
                    )
                )
                global_idx += 1
    return chunks
