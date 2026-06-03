from __future__ import annotations

from dataclasses import dataclass
import re

from app.retrieval.text import build_index_text
from app.services.document_models import SearchResult, SourceChunk
from app.services.embeddings import _tokenize


@dataclass(slots=True)
class RerankFeatures:
    coverage_score: float
    phrase_score: float
    locator_score: float
    intent_score: float
    retrieval_score: float

    @property
    def total(self) -> float:
        return (
            (6.0 * self.coverage_score)
            + (3.0 * self.phrase_score)
            + (3.0 * self.locator_score)
            + (4.0 * self.intent_score)
            + self.retrieval_score
        )


class DeterministicReranker:
    def rerank(self, *, query: str, results: list[SearchResult], top_k: int | None = None) -> list[SearchResult]:
        if not results:
            return []

        query_terms = set(_tokenize(query))
        query_phrases = _query_phrases(query)
        scored_results = [
            (
                self._score(query=query, query_terms=query_terms, query_phrases=query_phrases, result=result),
                index,
                result,
            )
            for index, result in enumerate(results)
        ]
        ordered = sorted(
            scored_results,
            key=lambda item: (
                item[0].total,
                item[0].intent_score,
                item[0].coverage_score,
                item[0].retrieval_score,
                -item[1],
            ),
            reverse=True,
        )
        limit = top_k or len(ordered)
        reranked: list[SearchResult] = []
        for rank, (features, _, result) in enumerate(ordered[:limit], start=1):
            reranked.append(
                SearchResult(
                    chunk=result.chunk,
                    score=features.total,
                    vector_score=result.vector_score,
                    keyword_score=result.keyword_score,
                    rank=rank,
                )
            )
        return reranked

    def _score(
        self,
        *,
        query: str,
        query_terms: set[str],
        query_phrases: list[str],
        result: SearchResult,
    ) -> RerankFeatures:
        index_text = build_index_text(result.chunk)
        normalized_index_text = _normalize_text(index_text)
        index_terms = set(_tokenize(index_text))
        matched_terms = index_terms & query_terms
        coverage_score = len(matched_terms) / max(len(query_terms), 1)
        phrase_score = _phrase_score(normalized_index_text, query_phrases)
        locator_score = _locator_score(query, result.chunk)
        intent_score = _intent_score(query, result.chunk)
        retrieval_score = min(max(result.score, 0.0), 2.0) / 2.0
        return RerankFeatures(
            coverage_score=coverage_score,
            phrase_score=phrase_score,
            locator_score=locator_score,
            intent_score=intent_score,
            retrieval_score=retrieval_score,
        )


def _intent_score(query: str, chunk: SourceChunk) -> float:
    lowered = query.lower()
    index_text = build_index_text(chunk)
    score = 0.0
    if _has_any(lowered, {"skill", "technolog", "tool", "stack"}):
        score += _section_match_score(index_text, {"skills", "technical skills", "core skills", "technologies", "tools"})
    if _has_any(lowered, {"education", "degree", "school", "university"}):
        score += _section_match_score(index_text, {"education", "academic background", "degrees"})
    if _has_any(lowered, {"experience", "work", "employment", "role"}):
        score += _section_match_score(index_text, {"experience", "work experience", "employment", "professional experience"})
    if _has_any(lowered, {"slide", "page"}):
        score += _slide_or_page_score(lowered, chunk)
    return min(score, 1.0)


def _section_match_score(text: str, headings: set[str]) -> float:
    lines = [line.strip().lower().rstrip(":") for line in text.splitlines() if line.strip()]
    for line in lines:
        if line in headings:
            return 1.0
        if any(line.startswith(f"{heading}:") for heading in headings):
            return 1.0
    normalized_text = _normalize_text(text)
    if any(re.search(rf"\b{re.escape(heading)}\b", normalized_text) for heading in headings):
        return 0.6
    return 0.0


def _slide_or_page_score(query: str, chunk: SourceChunk) -> float:
    requested_slide = _extract_number_after_label(query, "slide")
    requested_page = _extract_number_after_label(query, "page")
    normalized_text = _normalize_text(build_index_text(chunk))
    if requested_slide is not None and re.search(rf"\bslide\s+{requested_slide}\b", normalized_text):
        return 1.0
    if requested_page is not None:
        if chunk.page_number == requested_page:
            return 1.0
        if re.search(rf"\bpage\s+{requested_page}\b", normalized_text):
            return 1.0
    return 0.0


def _locator_score(query: str, chunk: SourceChunk) -> float:
    lowered = query.lower()
    if "slide" in lowered or "page" in lowered:
        return _slide_or_page_score(lowered, chunk)
    locator_terms = set(_tokenize(chunk.locator()))
    query_terms = set(_tokenize(query))
    if not locator_terms:
        return 0.0
    return len(locator_terms & query_terms) / len(locator_terms)


def _phrase_score(text: str, phrases: list[str]) -> float:
    if not phrases:
        return 0.0
    matches = sum(1 for phrase in phrases if phrase in text)
    return min(matches / len(phrases), 1.0)


def _query_phrases(query: str) -> list[str]:
    terms = _tokenize(query)
    phrases: list[str] = []
    phrases.extend(" ".join(terms[index : index + 2]) for index in range(len(terms) - 1))
    phrases.extend(" ".join(terms[index : index + 3]) for index in range(len(terms) - 2))
    return phrases


def _extract_number_after_label(text: str, label: str) -> int | None:
    match = re.search(rf"\b{label}\s+(\d+)\b", text, flags=re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1))


def _has_any(text: str, needles: set[str]) -> bool:
    return any(needle in text for needle in needles)


def _normalize_text(text: str) -> str:
    return " ".join(text.lower().split())
