from __future__ import annotations

from dataclasses import dataclass

from app.retrieval.interfaces import KeywordSearchBackend, RetrievalQuery, VectorSearchBackend
from app.services.document_models import SearchResult


@dataclass(slots=True)
class HybridScoringConfig:
    vector_weight: float = 0.65
    keyword_weight: float = 0.35
    rrf_k: int = 60


class HybridRetriever:
    def __init__(
        self,
        vector_backend: VectorSearchBackend,
        keyword_backend: KeywordSearchBackend,
        config: HybridScoringConfig | None = None,
    ) -> None:
        self._vector_backend = vector_backend
        self._keyword_backend = keyword_backend
        self._config = config or HybridScoringConfig()

    def search(self, query: RetrievalQuery) -> list[SearchResult]:
        vector_results = self._vector_backend.search(query)
        keyword_results = self._keyword_backend.search(query)
        merged: dict[str, SearchResult] = {}
        max_vector_score = max((result.score for result in vector_results), default=0.0)
        max_keyword_score = max((result.score for result in keyword_results), default=0.0)

        for rank, result in enumerate(vector_results, start=1):
            merged[result.chunk.chunk_id] = SearchResult(
                chunk=result.chunk,
                score=self._blend_score(result.score, max_vector_score, rank, self._config.vector_weight),
                vector_score=result.vector_score if result.vector_score is not None else result.score,
                rank=rank,
            )

        for rank, result in enumerate(keyword_results, start=1):
            existing = merged.get(result.chunk.chunk_id)
            weighted_score = self._blend_score(result.score, max_keyword_score, rank, self._config.keyword_weight)
            if existing:
                existing.score += weighted_score
                existing.keyword_score = result.keyword_score if result.keyword_score is not None else result.score
                existing.score += 0.05
            else:
                merged[result.chunk.chunk_id] = SearchResult(
                    chunk=result.chunk,
                    score=weighted_score,
                    keyword_score=result.keyword_score if result.keyword_score is not None else result.score,
                    rank=rank,
                )

        ordered = sorted(
            merged.values(),
            key=lambda result: (
                result.score,
                result.vector_score or 0.0,
                result.keyword_score or 0.0,
                -(result.chunk.chunk_index),
                result.chunk.chunk_id,
            ),
            reverse=True,
        )[: query.top_k]
        for index, result in enumerate(ordered, start=1):
            result.rank = index
        return ordered

    def _rrf(self, rank: int) -> float:
        return 1.0 / (self._config.rrf_k + rank)

    def _blend_score(self, raw_score: float, max_score: float, rank: int, weight: float) -> float:
        normalized_score = raw_score / max_score if max_score > 0 else 0.0
        return weight * ((0.75 * normalized_score) + (0.25 * self._rrf(rank)))
