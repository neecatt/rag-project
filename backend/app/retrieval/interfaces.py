from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.services.document_models import SearchResult, SourceChunk


@dataclass(slots=True)
class RetrievalQuery:
    text: str
    top_k: int = 10
    filters: dict[str, Any] = field(default_factory=dict)


class VectorSearchBackend(ABC):
    @abstractmethod
    def search(self, query: RetrievalQuery) -> list[SearchResult]:
        raise NotImplementedError


class KeywordSearchBackend(ABC):
    @abstractmethod
    def search(self, query: RetrievalQuery) -> list[SearchResult]:
        raise NotImplementedError


class ChunkRepository(ABC):
    @abstractmethod
    def upsert_chunks(self, chunks: list[SourceChunk]) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_chunk(self, chunk_id: str) -> SourceChunk | None:
        raise NotImplementedError
