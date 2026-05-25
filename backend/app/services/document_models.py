from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


Metadata = dict[str, Any]


@dataclass(slots=True)
class ExtractionResult:
    text: str
    content_type: str
    metadata: Metadata = field(default_factory=dict)


@dataclass(slots=True)
class Citation:
    document_id: str
    chunk_id: str
    title: str
    locator: str
    source_id: str | None = None
    page_number: int | None = None
    section_title: str | None = None


@dataclass(slots=True)
class SourceChunk:
    chunk_id: str
    document_id: str
    document_version_id: str
    chunk_index: int
    text: str
    metadata: Metadata = field(default_factory=dict)
    source_id: str | None = None
    tenant_id: str | None = None
    workspace_id: str | None = None
    document_title: str | None = None
    section_title: str | None = None
    page_number: int | None = None
    token_count: int | None = None
    char_start: int | None = None
    char_end: int | None = None

    def locator(self) -> str:
        if self.page_number is not None:
            return f"Page {self.page_number}"
        if self.section_title:
            return self.section_title
        if self.chunk_index >= 0:
            return f"Chunk {self.chunk_index + 1}"
        return "Chunk"

    def to_citation(self) -> Citation:
        return Citation(
            document_id=self.document_id,
            chunk_id=self.chunk_id,
            title=self.document_title or self.metadata.get("document_title", "Untitled Document"),
            locator=self.locator(),
            source_id=self.source_id,
            page_number=self.page_number,
            section_title=self.section_title,
        )


@dataclass(slots=True)
class SearchResult:
    chunk: SourceChunk
    score: float
    vector_score: float | None = None
    keyword_score: float | None = None
    rank: int | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk.chunk_id,
            "document_id": self.chunk.document_id,
            "document_title": self.chunk.document_title,
            "score": self.score,
            "snippet": self.chunk.text,
            "source_id": self.chunk.source_id,
            "citation": self.chunk.to_citation(),
        }
