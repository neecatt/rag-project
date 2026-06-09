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

        query_terms = _salient_terms(query) or set(_unigram_terms(query))
        query_phrases = _query_phrases(query)
        query_term_document_frequency = _query_term_document_frequency(query_terms, results)
        scored_results = [
            (
                self._score(
                    query=query,
                    query_terms=query_terms,
                    query_phrases=query_phrases,
                    query_term_document_frequency=query_term_document_frequency,
                    result=result,
                ),
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
        query_term_document_frequency: dict[str, int],
        result: SearchResult,
    ) -> RerankFeatures:
        index_text = build_index_text(result.chunk)
        normalized_index_text = _normalize_text(index_text)
        index_terms = set(_unigram_terms(index_text))
        matched_terms = index_terms & query_terms
        coverage_score = _weighted_term_coverage(
            matched_terms=matched_terms,
            query_terms=query_terms,
            query_term_document_frequency=query_term_document_frequency,
        )
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
    score = _generic_heading_match_score(query, chunk)
    if "slide" in lowered or "page" in lowered:
        score += _slide_or_page_score(lowered, chunk)
    return min(score, 1.0)


def _generic_heading_match_score(query: str, chunk: SourceChunk) -> float:
    query_terms = _salient_terms(query)
    if not query_terms:
        return 0.0

    chunk_text = chunk.text
    heading_source = "\n".join(part for part in (chunk.section_title, chunk.text) if part)
    headings = _extract_heading_terms(heading_source)
    if not headings:
        return 0.0

    overlap = len(query_terms & headings)
    if overlap == 0:
        return 0.0

    heading_coverage = overlap / max(len(query_terms), 1)
    structured_support = _structured_section_score(chunk_text, query_terms, headings)
    return min(max(heading_coverage, structured_support), 1.0)


def _structured_section_score(text: str, query_terms: set[str], heading_terms: set[str]) -> float:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return 0.0

    heading_overlap = query_terms & heading_terms
    if not heading_overlap:
        return 0.0

    body = " ".join(lines[1:])
    body_terms = set(_unigram_terms(body))
    if not body_terms:
        return 0.0

    list_marker_count = sum(body.count(marker) for marker in (",", ";", "|", "\u2022"))
    item_density = min(len(body_terms - heading_terms) / 8.0, 1.0)
    list_signal = min(list_marker_count / 4.0, 1.0)
    body_line_signal = 1.0 if len(lines) >= 3 else 0.5
    return max(list_signal, min(item_density, body_line_signal))


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
    locator_terms = set(_unigram_terms(chunk.locator()))
    query_terms = set(_unigram_terms(query))
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


def _query_term_document_frequency(query_terms: set[str], results: list[SearchResult]) -> dict[str, int]:
    frequencies = {term: 0 for term in query_terms}
    for result in results:
        result_terms = set(_unigram_terms(build_index_text(result.chunk)))
        for term in query_terms & result_terms:
            frequencies[term] += 1
    return frequencies


def _weighted_term_coverage(
    *,
    matched_terms: set[str],
    query_terms: set[str],
    query_term_document_frequency: dict[str, int],
) -> float:
    if not query_terms:
        return 0.0

    def weight(term: str) -> float:
        return 1.0 / max(query_term_document_frequency.get(term, 1), 1)

    matched_weight = sum(weight(term) for term in matched_terms)
    total_weight = sum(weight(term) for term in query_terms)
    return matched_weight / max(total_weight, 1e-6)


def _extract_number_after_label(text: str, label: str) -> int | None:
    match = re.search(rf"\b{label}\s+(\d+)\b", text, flags=re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1))


def _normalize_text(text: str) -> str:
    return " ".join(text.lower().split())


def _salient_terms(text: str) -> set[str]:
    ignored = {
        "what",
        "which",
        "tell",
        "give",
        "list",
        "name",
        "identify",
        "extract",
        "show",
        "about",
        "from",
        "does",
        "the",
        "this",
        "that",
        "with",
        "and",
        "for",
        "are",
        "can",
        "should",
    }
    return {term for term in _unigram_terms(text) if term not in ignored and len(term) > 2}


def _extract_heading_terms(text: str) -> set[str]:
    heading_terms: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip().rstrip(":")
        if not stripped:
            continue
        if len(stripped) <= 80 and re.match(r"^[A-Za-z][A-Za-z /&+-]+$", stripped):
            heading_terms.update(_unigram_terms(stripped))
            continue
        if ":" in stripped:
            label = stripped.split(":", 1)[0]
            if len(label) <= 60 and re.match(r"^[A-Za-z][A-Za-z /&+-]+$", label):
                heading_terms.update(_unigram_terms(label))
    return heading_terms


def _unigram_terms(text: str) -> list[str]:
    return [term for term in _tokenize(text) if "_" not in term]
