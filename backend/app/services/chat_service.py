from __future__ import annotations

from dataclasses import dataclass
import re

from app.core.config import Settings, get_settings
from app.models.chat import ChatMessage, ChatSession
from app.retrieval.rerank import DeterministicReranker
from app.retrieval.text import build_index_text
from app.services.answer_generation import (
    AnswerGenerator,
    ConfigurableAnswerGenerator,
    GroundedGenerationEvidence,
    GroundedGenerationRequest,
    GroundedGenerationResult,
)
from app.services.document_models import Citation, SearchResult
from app.services.embeddings import _tokenize
from app.services.retrieval_service import DatabaseRetrievalService


@dataclass(slots=True)
class ChatReply:
    content: str
    citations: list[Citation]


@dataclass(slots=True)
class SelectedEvidence:
    result: SearchResult
    best_sentence: str
    overlap_terms: set[str]
    covered_segments: set[int]
    answerability_score: float


@dataclass(slots=True)
class SelectedAnswer:
    content: str
    supporting_results: list[SearchResult]


@dataclass(slots=True)
class QuestionProfile:
    wants_summary: bool
    wants_comparison: bool
    wants_structured_extraction: bool
    seeks_quantity: bool
    segment_count: int

    @property
    def needs_synthesis(self) -> bool:
        return self.wants_summary or self.wants_comparison or self.segment_count > 1

    @property
    def prefers_direct_answer(self) -> bool:
        return not self.needs_synthesis and not self.wants_structured_extraction

    @property
    def needs_expanded_context(self) -> bool:
        return self.wants_summary or self.wants_structured_extraction or self.segment_count > 1

    @classmethod
    def from_question(cls, question: str) -> QuestionProfile:
        lowered = question.lower()
        segments = [segment for segment in re.split(r"\?|,|\band\b|\bbut\b|\bor\b", lowered) if segment.strip()]
        return cls(
            wants_summary=any(keyword in lowered for keyword in {"summarize", "summary", "overview", "review", "explain"}),
            wants_comparison=any(keyword in lowered for keyword in {"compare", "difference", "different", "versus", "pros and cons"}),
            wants_structured_extraction=(
                lowered.startswith(("list ", "name ", "identify ", "extract "))
                or "what are" in lowered
                or "which are" in lowered
                or "tell me" in lowered
            ),
            seeks_quantity=lowered.startswith("how many") or lowered.startswith("how much") or "how long" in lowered,
            segment_count=len(segments) or 1,
        )


@dataclass(slots=True)
class AnswerDraft:
    content: str
    used_evidence_indices: list[int]


class GroundedEvidenceSelector:
    def select(self, *, question: str, results: list[SearchResult]) -> list[SelectedEvidence]:
        if not results:
            return []

        query_terms = set(_tokenize(question))
        segments = self._question_segments(question)
        candidates = [
            self._build_candidate(question=question, result=result, query_terms=query_terms, segments=segments)
            for result in results
        ]
        candidates = [candidate for candidate in candidates if candidate.answerability_score > 0]
        if not candidates:
            fallback = self._build_candidate(question=question, result=results[0], query_terms=query_terms, segments=segments)
            return [fallback]

        candidates.sort(
            key=lambda candidate: (
                candidate.answerability_score,
                len(candidate.covered_segments),
                len(candidate.overlap_terms),
                candidate.result.score,
                -candidate.result.chunk.chunk_index,
            ),
            reverse=True,
        )

        selected: list[SelectedEvidence] = []
        covered_terms: set[str] = set()
        covered_segments: set[int] = set()

        for candidate in candidates:
            if self._is_redundant(candidate, selected):
                continue

            new_terms = candidate.overlap_terms - covered_terms
            new_segments = candidate.covered_segments - covered_segments
            if not selected:
                selected.append(candidate)
                covered_terms.update(candidate.overlap_terms)
                covered_segments.update(candidate.covered_segments)
                if self._single_chunk_is_sufficient(candidate, query_terms, segments):
                    break
                continue

            if new_terms or new_segments:
                selected.append(candidate)
                covered_terms.update(candidate.overlap_terms)
                covered_segments.update(candidate.covered_segments)

            if len(selected) >= 3 or covered_terms >= query_terms or covered_segments >= set(range(len(segments))):
                break

        return selected or [candidates[0]]

    def _build_candidate(
        self,
        *,
        question: str,
        result: SearchResult,
        query_terms: set[str],
        segments: list[set[str]],
    ) -> SelectedEvidence:
        indexed_text = build_index_text(result.chunk)
        indexed_terms = set(_tokenize(indexed_text))
        best_sentence = self._best_sentence(question, result.chunk.text)
        sentence_terms = set(_tokenize(best_sentence))
        overlap_terms = indexed_terms & query_terms if query_terms else sentence_terms
        covered_segments = {
            index
            for index, segment_terms in enumerate(segments)
            if segment_terms and len(indexed_terms & segment_terms) >= max(1, min(2, len(segment_terms)))
        }
        answerability_score = (
            (2.0 * len(sentence_terms & query_terms))
            + len(overlap_terms)
            + (0.5 * len(covered_segments))
            + min(result.score, 1.5)
        )
        if self._contains_concrete_fact(best_sentence):
            answerability_score += 1.0
        return SelectedEvidence(
            result=result,
            best_sentence=best_sentence,
            overlap_terms=overlap_terms,
            covered_segments=covered_segments,
            answerability_score=answerability_score,
        )

    def _question_segments(self, question: str) -> list[set[str]]:
        raw_segments = re.split(r"\?|,|\band\b|\bbut\b|\bor\b", question, flags=re.IGNORECASE)
        segments = [set(_tokenize(segment)) for segment in raw_segments if set(_tokenize(segment))]
        return segments or [set(_tokenize(question))]

    def _single_chunk_is_sufficient(
        self,
        candidate: SelectedEvidence,
        query_terms: set[str],
        segments: list[set[str]],
    ) -> bool:
        if not query_terms:
            return True
        coverage_ratio = len(candidate.overlap_terms) / max(len(query_terms), 1)
        segment_count = len(candidate.covered_segments)
        return coverage_ratio >= 0.7 and (segment_count >= len(segments) or self._contains_concrete_fact(candidate.best_sentence))

    def _is_redundant(self, candidate: SelectedEvidence, selected: list[SelectedEvidence]) -> bool:
        candidate_terms = set(_tokenize(candidate.best_sentence))
        for existing in selected:
            existing_terms = set(_tokenize(existing.best_sentence))
            overlap = len(candidate_terms & existing_terms)
            union = len(candidate_terms | existing_terms)
            if union and (overlap / union) >= 0.8:
                return True
            if candidate.result.chunk.document_id == existing.result.chunk.document_id and candidate.best_sentence == existing.best_sentence:
                return True
        return False

    def _contains_concrete_fact(self, text: str) -> bool:
        if re.search(r"\b\d+\b", text):
            return True
        return ":" in text or "-" in text

    def _best_sentence(self, question: str, text: str) -> str:
        sentences = _split_text_units(text)
        if not sentences:
            return _normalize_complete_text(text)

        query_terms = set(_tokenize(question))
        ranked = sorted(
            sentences,
            key=lambda sentence: (
                self._sentence_overlap_score(sentence, query_terms),
                len(sentence),
            ),
            reverse=True,
        )
        return _normalize_complete_text(ranked[0])

    def _sentence_overlap_score(self, sentence: str, query_terms: set[str]) -> int:
        if not query_terms:
            return len(_tokenize(sentence))
        sentence_terms = set(_tokenize(sentence))
        return len(sentence_terms & query_terms)

class HeuristicFallbackAnswerGenerator:
    async def generate(self, request: GroundedGenerationRequest) -> GroundedGenerationResult:
        if not request.evidence:
            return GroundedGenerationResult(
                content="I could not find a grounded answer in the processed documents for that question.",
                used_evidence_indices=[],
            )

        profile = QuestionProfile.from_question(request.question)

        if profile.wants_structured_extraction:
            structured_answer = self._extract_structured_answer(question=request.question, evidence_items=request.evidence)
            if structured_answer is not None:
                return GroundedGenerationResult(
                    content=structured_answer.content,
                    used_evidence_indices=structured_answer.used_evidence_indices,
                )

        if len(request.evidence) == 1 and profile.prefers_direct_answer:
            direct_answer = self._direct_answer(
                question=request.question,
                evidence=request.evidence[0],
                seeks_quantity=profile.seeks_quantity,
            )
            if direct_answer:
                return GroundedGenerationResult(content=direct_answer, used_evidence_indices=[0])

        if profile.prefers_direct_answer:
            direct_multi = self._direct_multi_evidence_answer(
                question=request.question,
                evidence_items=request.evidence,
                seeks_quantity=profile.seeks_quantity,
            )
            if direct_multi is not None:
                return GroundedGenerationResult(
                    content=direct_multi.content,
                    used_evidence_indices=direct_multi.used_evidence_indices,
                )

        synthesis = self._synthesis_answer(
            question=request.question,
            evidence_items=request.evidence,
            max_units=3 if profile.needs_synthesis or len(request.evidence) > 1 else 2,
        )
        if synthesis is not None:
            return GroundedGenerationResult(
                content=synthesis.content,
                used_evidence_indices=synthesis.used_evidence_indices,
            )

        return GroundedGenerationResult(
            content=_normalize_complete_text(request.evidence[0].content),
            used_evidence_indices=[0],
        )

    def _direct_answer(
        self,
        *,
        question: str,
        evidence: GroundedGenerationEvidence,
        seeks_quantity: bool,
    ) -> str | None:
        sentence = _first_complete_unit(evidence.content)
        if not sentence:
            return None

        quantified_answer = self._extract_quantified_phrase(sentence)
        if quantified_answer and seeks_quantity:
            return quantified_answer

        labeled_answer = self._extract_labeled_phrase(question=question, sentence=sentence)
        if labeled_answer:
            return labeled_answer

        if len(sentence) <= 160:
            return _normalize_complete_text(sentence)
        return None

    def _extract_structured_answer(
        self,
        *,
        question: str,
        evidence_items: list[GroundedGenerationEvidence],
    ) -> AnswerDraft | None:
        salient_terms = self._salient_terms(question)
        if not salient_terms:
            return None

        for index, evidence in enumerate(evidence_items):
            lines = [line.strip() for line in evidence.content.splitlines() if line.strip()]
            for line_index, line in enumerate(lines):
                label, inline_value = self._split_label(line)
                if label and self._line_matches_question(label, salient_terms):
                    values = self._parse_structured_items(inline_value)
                    if not values and line_index + 1 < len(lines):
                        values = self._parse_structured_items(lines[line_index + 1])
                    if values:
                        return AnswerDraft(content=self._format_structured_answer(values), used_evidence_indices=[index])
                if not label and self._line_matches_question(line, salient_terms) and line_index + 1 < len(lines):
                    values = self._parse_structured_items(lines[line_index + 1])
                    if len(values) >= 3:
                        return AnswerDraft(content=self._format_structured_answer(values), used_evidence_indices=[index])
        return None

    def _parse_structured_items(self, text: str) -> list[str]:
        normalized = re.sub(r"^[A-Za-z][A-Za-z /&+-]{1,60}:\s*", "", text.strip())
        pieces = re.split(r",|;|\||\u2022|\n|\s+-\s+", normalized)
        values: list[str] = []
        for piece in pieces:
            cleaned = " ".join(piece.strip(" .:-").split())
            if not cleaned or len(cleaned) > 60 or len(cleaned.split()) > 6:
                continue
            values.append(cleaned)
        return self._dedupe_preserving_order(values)

    def _format_structured_answer(self, values: list[str]) -> str:
        return f"{', '.join(values[:8])}."

    def _dedupe_preserving_order(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for value in values:
            key = value.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(value)
        return deduped

    def _extract_quantified_phrase(self, sentence: str) -> str | None:
        match = re.search(
            r"\b(\d{1,3}(?:\.\d+)?)\s*(minutes?|hours?|days?|slides?|pages?|percent|%)\b",
            sentence,
            flags=re.IGNORECASE,
        )
        if not match:
            match = re.search(
                r"\b(\d{1,3}(?:\.\d+)?)\s*-\s*(minutes?|hours?|days?|slides?|pages?)\b",
                sentence,
                flags=re.IGNORECASE,
            )
        if not match:
            return None

        quantity = match.group(1)
        unit = match.group(2).lower()
        if unit == "%":
            return f"{quantity}%."
        if unit.endswith("s"):
            return f"{quantity} {unit}."
        return f"{quantity} {unit}s."

    def _extract_labeled_phrase(self, *, question: str, sentence: str) -> str | None:
        if ":" not in sentence:
            return None
        prefix, suffix = sentence.split(":", 1)
        prefix_terms = set(_tokenize(prefix))
        question_terms = set(_tokenize(question))
        if prefix_terms & question_terms and suffix.strip():
            value = suffix.strip()
            if value.endswith((".", "!", "?")):
                return value
            return f"{value}."
        return None

    def _direct_multi_evidence_answer(
        self,
        *,
        question: str,
        evidence_items: list[GroundedGenerationEvidence],
        seeks_quantity: bool,
    ) -> AnswerDraft | None:
        direct_answers: list[tuple[int, str]] = []
        for index, evidence in enumerate(evidence_items[:2]):
            direct_answer = self._direct_answer(question=question, evidence=evidence, seeks_quantity=seeks_quantity)
            if direct_answer:
                direct_answers.append((index, direct_answer))

        if direct_answers:
            first_index, first_answer = direct_answers[0]
            if len(direct_answers) == 1 or first_answer == direct_answers[1][1]:
                return AnswerDraft(content=first_answer, used_evidence_indices=[first_index])
        return None

    def _synthesis_answer(
        self,
        *,
        question: str,
        evidence_items: list[GroundedGenerationEvidence],
        max_units: int,
    ) -> AnswerDraft | None:
        supporting_units: list[tuple[int, str]] = []
        for index, evidence in enumerate(evidence_items[:3]):
            units = self._best_supporting_units(question=question, text=evidence.content, limit=1 if len(evidence_items) > 1 else 2)
            for unit in units:
                supporting_units.append((index, unit))

        deduped_units: list[tuple[int, str]] = []
        seen: set[str] = set()
        for index, unit in supporting_units:
            normalized = unit.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            deduped_units.append((index, unit))
            if len(deduped_units) >= max_units:
                break

        if not deduped_units:
            return None

        return AnswerDraft(
            content=" ".join(unit for _, unit in deduped_units),
            used_evidence_indices=self._dedupe_indices(index for index, _ in deduped_units),
        )

    def _best_supporting_units(self, *, question: str, text: str, limit: int) -> list[str]:
        units = _split_text_units(text)
        if not units:
            return []

        query_terms = set(_tokenize(question))
        ranked = sorted(
            units,
            key=lambda unit: (
                self._sentence_overlap_score(unit, query_terms),
                self._contains_concrete_fact(unit),
                -abs(len(unit) - 120),
            ),
            reverse=True,
        )

        selected: list[str] = []
        for unit in ranked:
            completed = _normalize_complete_text(unit)
            if not completed or completed in selected:
                continue
            selected.append(completed)
            if len(selected) >= limit:
                break
        return selected

    def _sentence_overlap_score(self, unit: str, query_terms: set[str]) -> int:
        if not query_terms:
            return len(_tokenize(unit))
        return len(set(_tokenize(unit)) & query_terms)

    def _contains_concrete_fact(self, text: str) -> bool:
        if re.search(r"\b\d+\b", text):
            return True
        return ":" in text or "-" in text

    def _salient_terms(self, question: str) -> set[str]:
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
        return {term for term in _tokenize(question) if term not in ignored and len(term) > 2}

    def _split_label(self, line: str) -> tuple[str | None, str]:
        if ":" not in line:
            return None, line
        label, value = line.split(":", 1)
        cleaned_label = label.strip()
        if not cleaned_label or len(cleaned_label) > 60:
            return None, line
        return cleaned_label, value.strip()

    def _line_matches_question(self, line: str, salient_terms: set[str]) -> bool:
        return bool(set(_tokenize(line)) & salient_terms)

    def _dedupe_indices(self, indices) -> list[int]:
        deduped: list[int] = []
        seen: set[int] = set()
        for index in indices:
            if index in seen:
                continue
            seen.add(index)
            deduped.append(index)
        return deduped


class GroundedChatService:
    def __init__(
        self,
        retrieval_service: DatabaseRetrievalService,
        *,
        settings: Settings | None = None,
        evidence_selector: GroundedEvidenceSelector | None = None,
        reranker: DeterministicReranker | None = None,
        answer_generator: AnswerGenerator | None = None,
    ) -> None:
        self._retrieval_service = retrieval_service
        self._settings = settings or get_settings()
        self._evidence_selector = evidence_selector or GroundedEvidenceSelector()
        self._reranker = reranker or DeterministicReranker()
        self._completion_fallback = HeuristicFallbackAnswerGenerator()
        self._answer_generator = answer_generator or ConfigurableAnswerGenerator(
            self._settings,
            fallback_generator=self._completion_fallback,
        )

    async def generate_reply(
        self,
        *,
        session: ChatSession,
        user_message: ChatMessage,
        top_k: int = 3,
    ) -> ChatReply:
        candidate_count = max(5, top_k)
        results = self._retrieval_service.search(
            query=user_message.content,
            top_k=candidate_count,
            workspace_id=session.workspace_id,
        )
        if not results:
            return ChatReply(
                content="I could not find a grounded answer in the processed documents for that question.",
                citations=[],
            )

        reranked_results = self._reranker.rerank(query=user_message.content, results=results)
        selected_evidence = self._evidence_selector.select(question=user_message.content, results=reranked_results)
        generation_request = GroundedGenerationRequest(
            question=user_message.content,
            evidence=[
                GroundedGenerationEvidence(
                    title=item.result.chunk.document_title or "Untitled Document",
                    locator=item.result.chunk.locator(),
                    content=self._generation_context(question=user_message.content, evidence=item),
                )
                for item in selected_evidence
            ],
        )
        generation_result = await self._answer_generator.generate(generation_request)
        normalized_answer = self._normalize_answer(generation_result.content, generation_request.evidence)
        if not normalized_answer:
            generation_result = await self._completion_fallback.generate(generation_request)
            normalized_answer = self._normalize_answer(generation_result.content, generation_request.evidence)

        if not normalized_answer:
            normalized_answer = "I could not find a grounded answer in the processed documents for that question."

        used_indices = self._resolve_used_evidence_indices(
            generation_result.used_evidence_indices,
            answer=normalized_answer,
            evidence=generation_request.evidence,
            evidence_count=len(selected_evidence),
        )
        return ChatReply(
            content=normalized_answer,
            citations=[selected_evidence[index].result.chunk.to_citation() for index in used_indices],
        )

    def _generation_context(self, *, question: str, evidence: SelectedEvidence) -> str:
        if QuestionProfile.from_question(question).needs_expanded_context:
            return self._trim_context(evidence.result.chunk.text, limit=5000)
        return evidence.best_sentence or self._trim_context(evidence.result.chunk.text, limit=1200)

    def _trim_context(self, text: str, *, limit: int) -> str:
        if len(text) <= limit:
            return text
        trimmed = _trim_to_complete_unit(text, limit=limit)
        return trimmed or text[:limit].strip()

    def _normalize_answer(self, answer: str, evidence: list[GroundedGenerationEvidence]) -> str:
        normalized = _normalize_complete_text(answer)
        if not normalized:
            return ""
        if normalized.endswith("...") and not any("..." in item.content for item in evidence):
            return ""
        return normalized

    def _resolve_used_evidence_indices(
        self,
        indices: list[int] | None,
        *,
        answer: str,
        evidence: list[GroundedGenerationEvidence],
        evidence_count: int,
    ) -> list[int]:
        if evidence_count <= 0:
            return []
        if indices is not None:
            resolved = [index for index in indices if 0 <= index < evidence_count]
            return resolved or [0]
        return self._infer_used_evidence_indices(answer=answer, evidence=evidence)

    def _infer_used_evidence_indices(self, *, answer: str, evidence: list[GroundedGenerationEvidence]) -> list[int]:
        answer_terms = set(_tokenize(answer))
        if not answer_terms:
            return []

        matched: list[tuple[int, float]] = []
        for index, item in enumerate(evidence):
            content_terms = set(_tokenize(item.content))
            if not content_terms:
                continue
            overlap = answer_terms & content_terms
            if not overlap:
                continue
            sentence_match = 1.0 if self._answer_is_supported_by_content(answer, item.content) else 0.0
            coverage = len(overlap) / max(len(answer_terms), 1)
            density = len(overlap) / max(len(content_terms), 1)
            score = (1.5 * coverage) + density + sentence_match
            if sentence_match or coverage >= 0.45 or (coverage >= 0.25 and len(overlap) >= 3):
                matched.append((index, score))

        if not matched:
            return []

        matched.sort(key=lambda item: (item[1], -item[0]), reverse=True)
        top_score = matched[0][1]
        return [index for index, score in matched if score >= max(0.9, top_score - 0.35)][:2]

    def _answer_is_supported_by_content(self, answer: str, content: str) -> bool:
        normalized_answer = " ".join(answer.split()).lower().strip(" .")
        if not normalized_answer:
            return False
        return any(
            normalized_answer in unit or unit in normalized_answer
            for unit in _normalized_units(content)
        )


def _split_text_units(text: str) -> list[str]:
    units = [
        " ".join(segment.split()).strip()
        for segment in re.split(r"(?<=[.!?])\s+|\n+", text)
        if segment.strip()
    ]
    return units


def _normalized_units(text: str) -> list[str]:
    return [unit.lower().strip(" .") for unit in _split_text_units(text)]


def _first_complete_unit(text: str) -> str:
    units = _split_text_units(text)
    if not units:
        return _normalize_complete_text(text)
    return _normalize_complete_text(units[0])


def _trim_to_complete_unit(text: str, *, limit: int) -> str:
    if len(text) <= limit:
        return text

    candidate = text[:limit]
    punctuation_positions = [candidate.rfind(marker) for marker in (". ", "! ", "? ", ".\n", "!\n", "?\n")]
    last_punctuation = max(punctuation_positions)
    if last_punctuation >= 0:
        return candidate[: last_punctuation + 1].strip()

    line_break = candidate.rfind("\n")
    if line_break >= 0:
        return candidate[:line_break].strip()

    return candidate.rsplit(" ", 1)[0].strip()


def _normalize_complete_text(text: str) -> str:
    normalized = " ".join(text.split()).strip()
    if not normalized:
        return ""
    if normalized.endswith("..."):
        return ""
    if normalized[-1] in ".!?":
        return normalized
    if normalized[-1] in ",:;-/(":
        return ""
    tokens = [token.lower().strip(".,:;!?") for token in normalized.split()]
    if tokens and tokens[-1] in {
        "and",
        "or",
        "but",
        "with",
        "without",
        "for",
        "to",
        "from",
        "of",
        "in",
        "on",
        "by",
        "when",
        "while",
        "because",
        "that",
        "which",
        "who",
    }:
        return ""
    return f"{normalized}."
