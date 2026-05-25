from __future__ import annotations

from collections import Counter
from math import log

from app.retrieval.interfaces import KeywordSearchBackend, RetrievalQuery
from app.retrieval.text import build_index_text
from app.services.document_models import SearchResult, SourceChunk
from app.services.embeddings import _tokenize


class InMemoryKeywordSearch(KeywordSearchBackend):
    def __init__(self, chunks: list[SourceChunk] | None = None) -> None:
        self._chunks = chunks or []
        self._document_frequencies: Counter[str] = Counter()
        self._term_frequencies_by_chunk_id: dict[str, Counter[str]] = {}
        self._length_by_chunk_id: dict[str, int] = {}
        self._average_document_length = 0.0
        self._reindex()

    def upsert_chunks(self, chunks: list[SourceChunk]) -> None:
        chunk_by_id = {chunk.chunk_id: chunk for chunk in self._chunks}
        for chunk in chunks:
            chunk_by_id[chunk.chunk_id] = chunk
        self._chunks = list(chunk_by_id.values())
        self._reindex()

    def search(self, query: RetrievalQuery) -> list[SearchResult]:
        query_terms = _tokenize(query.text)
        if not query_terms:
            return []

        results: list[SearchResult] = []
        total_docs = max(len(self._chunks), 1)
        for chunk in self._chunks:
            if not _matches_filters(chunk, query.filters):
                continue
            term_counts = self._term_frequencies_by_chunk_id.get(chunk.chunk_id, Counter())
            document_length = self._length_by_chunk_id.get(chunk.chunk_id, 0)
            score = 0.0
            for term in query_terms:
                frequency = term_counts[term]
                if frequency == 0:
                    continue
                idf = log(1 + ((total_docs - self._document_frequencies[term] + 0.5) / (self._document_frequencies[term] + 0.5)))
                normalization = 1.2 * (
                    1 - 0.75 + 0.75 * (document_length / max(self._average_document_length, 1.0))
                )
                score += idf * ((frequency * (1.2 + 1)) / (frequency + normalization))
            if score:
                results.append(SearchResult(chunk=chunk, score=score, keyword_score=score))

        ranked = sorted(results, key=lambda result: result.score, reverse=True)[: query.top_k]
        for index, result in enumerate(ranked, start=1):
            result.rank = index
        return ranked

    def _reindex(self) -> None:
        self._document_frequencies = Counter()
        self._term_frequencies_by_chunk_id = {}
        self._length_by_chunk_id = {}
        for chunk in self._chunks:
            terms = _tokenize(build_index_text(chunk))
            term_counts = Counter(terms)
            self._term_frequencies_by_chunk_id[chunk.chunk_id] = term_counts
            self._length_by_chunk_id[chunk.chunk_id] = len(terms)
            self._document_frequencies.update(set(terms))
        if self._length_by_chunk_id:
            self._average_document_length = sum(self._length_by_chunk_id.values()) / len(self._length_by_chunk_id)
        else:
            self._average_document_length = 0.0


def _matches_filters(chunk: SourceChunk, filters: dict[str, object]) -> bool:
    for key, expected in filters.items():
        actual = getattr(chunk, key, chunk.metadata.get(key))
        if isinstance(expected, (list, tuple, set)):
            if actual not in expected:
                return False
        elif actual != expected:
            return False
    return True
