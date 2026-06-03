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
        sentences = [segment.strip() for segment in re.split(r"(?<=[.!?])\s+|\n+", " ".join(text.split())) if segment.strip()]
        if not sentences:
            return self._trim_text(text, limit=220)

        query_terms = set(_tokenize(question))
        ranked = sorted(
            sentences,
            key=lambda sentence: (
                self._sentence_overlap_score(sentence, query_terms),
                len(sentence),
            ),
            reverse=True,
        )
        return self._trim_text(ranked[0], limit=220)

    def _sentence_overlap_score(self, sentence: str, query_terms: set[str]) -> int:
        if not query_terms:
            return len(_tokenize(sentence))
        sentence_terms = set(_tokenize(sentence))
        return len(sentence_terms & query_terms)

    def _trim_text(self, text: str, *, limit: int) -> str:
        normalized_text = " ".join(text.split())
        if len(normalized_text) <= limit:
            return normalized_text
        return f"{normalized_text[: limit - 3].rstrip()}..."


class HeuristicFallbackAnswerGenerator:
    async def generate(self, request: GroundedGenerationRequest) -> str:
        if not request.evidence:
            return "I could not find a grounded answer in the processed documents for that question."

        if self._is_skills_question(request.question):
            skills = self._extract_skills(request.evidence)
            if skills:
                return f"Skills: {', '.join(skills)}."

        if len(request.evidence) == 1 and not self._is_broad_question(request.question):
            direct_answer = self._direct_answer(question=request.question, evidence=request.evidence[0])
            if direct_answer:
                return direct_answer

        if self._is_broad_question(request.question) or len(request.evidence) >= 3:
            snippets = [self._trim_text(evidence.content, limit=180) for evidence in request.evidence[:2]]
            summary = " ".join(snippet for snippet in snippets if snippet)
            evidence_lines = "\n".join(
                f"- {evidence.title} ({evidence.locator}): {self._trim_text(evidence.content, limit=180)}"
                for evidence in request.evidence[:3]
            )
            source_line = ", ".join(f"{evidence.title} [{evidence.locator}]" for evidence in request.evidence[:3])
            return f"Based on the processed documents, {summary}\nSupporting evidence:\n{evidence_lines}\nSources: {source_line}"

        snippets = [self._trim_text(evidence.content, limit=180) for evidence in request.evidence[:2]]
        return f"Based on the processed documents, {' '.join(snippets)}"

    def _direct_answer(self, *, question: str, evidence: GroundedGenerationEvidence) -> str | None:
        sentence = self._trim_text(evidence.content, limit=220)
        if not sentence:
            return None

        quantified_answer = self._extract_quantified_phrase(sentence)
        if quantified_answer and self._question_seeks_quantity(question):
            return quantified_answer

        labeled_answer = self._extract_labeled_phrase(question=question, sentence=sentence)
        if labeled_answer:
            return labeled_answer

        if len(sentence) <= 120:
            if sentence.endswith((".", "!", "?")):
                return sentence
            return f"{sentence}."
        return None

    def _is_broad_question(self, question: str) -> bool:
        lowered = question.lower()
        return any(
            keyword in lowered
            for keyword in {
                "summarize",
                "summary",
                "explain",
                "compare",
                "list",
                "overview",
                "review",
                "extract",
                "skills",
                "experience",
                "education",
                "resume",
                "cv",
            }
        )

    def _is_skills_question(self, question: str) -> bool:
        lowered = question.lower()
        return "skill" in lowered or "technolog" in lowered or "tool" in lowered

    def _extract_skills(self, evidence_items: list[GroundedGenerationEvidence]) -> list[str]:
        candidates: list[str] = []
        for evidence in evidence_items:
            sections = self._extract_named_sections(
                evidence.content,
                names={"skills", "technical skills", "core skills", "technologies", "tools"},
            )
            if sections:
                candidates.extend(self._split_skill_items(" ".join(sections)))
                continue
            candidates.extend(self._split_skill_items(self._skill_like_sentences(evidence.content)))
        return self._dedupe_preserving_order(candidates)[:20]

    def _extract_named_sections(self, text: str, *, names: set[str]) -> list[str]:
        lines = [line.strip() for line in text.splitlines()]
        sections: list[str] = []
        collecting = False
        current: list[str] = []
        for line in lines:
            if not line:
                continue
            heading = line.rstrip(":").strip().lower()
            is_heading = len(line) <= 80 and bool(re.match(r"^[A-Za-z][A-Za-z /&+-]+:?$", line))
            if is_heading and heading in names:
                if current:
                    sections.append(" ".join(current))
                    current = []
                collecting = True
                inline_value = line.split(":", 1)[1].strip() if ":" in line else ""
                if inline_value:
                    current.append(inline_value)
                continue
            if collecting and is_heading and heading not in names:
                if current:
                    sections.append(" ".join(current))
                    current = []
                collecting = False
                continue
            if collecting:
                current.append(line)
        if current:
            sections.append(" ".join(current))
        return sections

    def _skill_like_sentences(self, text: str) -> str:
        sentences = re.split(r"(?<=[.!?])\s+|\n+", text)
        matching = [
            sentence
            for sentence in sentences
            if re.search(r"\b(skills?|technologies|tools|proficient|experienced with|expertise)\b", sentence, flags=re.IGNORECASE)
        ]
        return " ".join(matching)

    def _split_skill_items(self, text: str) -> list[str]:
        normalized = re.sub(r"\b(skills?|technical skills|core skills|technologies|tools)\b\s*:?", "", text, flags=re.IGNORECASE)
        pieces = re.split(r",|;|\||/|\u2022|\n|\s+-\s+", normalized)
        skills: list[str] = []
        for piece in pieces:
            cleaned = " ".join(piece.strip(" .:-").split())
            if not cleaned or len(cleaned) > 60:
                continue
            if len(cleaned.split()) > 6:
                continue
            skills.append(cleaned)
        return skills

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

    def _question_seeks_quantity(self, question: str) -> bool:
        lowered = question.lower()
        return lowered.startswith("how many") or lowered.startswith("how much") or "how long" in lowered

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

    def _trim_text(self, text: str, *, limit: int) -> str:
        normalized_text = " ".join(text.split())
        if len(normalized_text) <= limit:
            return normalized_text
        truncated = normalized_text[:limit].rsplit(" ", 1)[0].strip()
        if not truncated:
            truncated = normalized_text[:limit].strip()
        return truncated.rstrip(".") + "."


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
        self._answer_generator = answer_generator or ConfigurableAnswerGenerator(
            self._settings,
            fallback_generator=HeuristicFallbackAnswerGenerator(),
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
        answer = await self._answer_generator.generate(generation_request)
        normalized_answer = self._normalize_answer(answer, generation_request.evidence) or (
            "I could not find a grounded answer in the processed documents for that question."
        )
        return ChatReply(
            content=normalized_answer,
            citations=[item.result.chunk.to_citation() for item in selected_evidence],
        )

    def _generation_context(self, *, question: str, evidence: SelectedEvidence) -> str:
        if self._needs_expanded_context(question):
            return self._trim_context(evidence.result.chunk.text, limit=5000)
        return evidence.best_sentence or self._trim_context(evidence.result.chunk.text, limit=1200)

    def _needs_expanded_context(self, question: str) -> bool:
        lowered = question.lower()
        return any(
            keyword in lowered
            for keyword in {
                "review",
                "extract",
                "summarize",
                "summary",
                "skills",
                "experience",
                "education",
                "resume",
                "cv",
            }
        )

    def _trim_context(self, text: str, *, limit: int) -> str:
        if len(text) <= limit:
            return text
        trimmed = text[:limit].rsplit("\n", 1)[0].strip()
        if len(trimmed) < limit * 0.5:
            trimmed = text[:limit].rsplit(" ", 1)[0].strip()
        return trimmed or text[:limit].strip()

    def _normalize_answer(self, answer: str, evidence: list[GroundedGenerationEvidence]) -> str:
        normalized = " ".join(answer.split()).strip()
        if normalized.endswith("...") and not any("..." in item.content for item in evidence):
            normalized = normalized.rstrip(".").rstrip()
            if normalized:
                normalized = f"{normalized}."
        return normalized
