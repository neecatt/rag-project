from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import re
from typing import Protocol
from urllib import error, request

from app.core.config import Settings

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class GroundedGenerationEvidence:
    title: str
    locator: str
    content: str


@dataclass(slots=True)
class GroundedGenerationRequest:
    question: str
    evidence: list[GroundedGenerationEvidence]


@dataclass(slots=True)
class GroundedGenerationResult:
    content: str
    used_evidence_indices: list[int] | None = None


class AnswerGenerator(Protocol):
    async def generate(self, request: GroundedGenerationRequest) -> GroundedGenerationResult: ...


class OpenAICompatibleAnswerGenerator:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def generate(self, request_payload: GroundedGenerationRequest) -> GroundedGenerationResult:
        body = {
            "model": self._settings.chat_answer_model,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Answer using only the provided evidence. "
                        "For narrow factual questions, answer directly in one short complete sentence when possible. "
                        "For synthesis, comparison, or summary questions, answer in two to four concise complete sentences that cover the needed points. "
                        "If the answer is a list, return a clearly complete list line rather than a fragment. "
                        "Do not add generic preambles, source lists, or unsupported filler. "
                        "Only stop when the answer is complete. "
                        "If the evidence is insufficient, say so plainly."
                    ),
                },
                {
                    "role": "user",
                    "content": _build_user_prompt(request_payload),
                },
            ],
        }
        answer = await _run_blocking_http_json(
            url=str(self._settings.chat_answer_base_url),
            api_key=self._settings.chat_answer_api_key or "",
            timeout_seconds=self._settings.chat_answer_timeout_seconds,
            body=body,
        )
        return GroundedGenerationResult(content=answer, used_evidence_indices=None)


class ConfigurableAnswerGenerator:
    def __init__(self, settings: Settings, fallback_generator: AnswerGenerator) -> None:
        self._settings = settings
        self._fallback_generator = fallback_generator
        self._live_generator: AnswerGenerator | None = None
        if (
            self._settings.chat_answer_provider == "openai_compatible"
            and self._settings.chat_answer_api_key
            and self._settings.chat_answer_model
        ):
            self._live_generator = OpenAICompatibleAnswerGenerator(settings)

    async def generate(self, request: GroundedGenerationRequest) -> GroundedGenerationResult:
        if self._live_generator is None:
            return await self._fallback_generator.generate(request)

        try:
            result = await self._live_generator.generate(request)
            normalized = _finalize_generated_text(result.content, request.evidence)
            if normalized:
                return GroundedGenerationResult(
                    content=normalized,
                    used_evidence_indices=result.used_evidence_indices,
                )
        except Exception:
            logger.exception("grounded answer model call failed; falling back to local generator")
        return await self._fallback_generator.generate(request)


async def _run_blocking_http_json(
    *,
    url: str,
    api_key: str,
    timeout_seconds: int,
    body: dict,
) -> str:
    import asyncio

    return await asyncio.to_thread(
        _post_json,
        url=url,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
        body=body,
    )


def _post_json(*, url: str, api_key: str, timeout_seconds: int, body: dict) -> str:
    http_request = request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with request.urlopen(http_request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        message = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"grounded answer request failed: {exc.code} {message}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"grounded answer request failed: {exc.reason}") from exc

    content = payload.get("choices", [{}])[0].get("message", {}).get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("grounded answer response did not contain message content")
    return content


def _build_user_prompt(request_payload: GroundedGenerationRequest) -> str:
    evidence_lines = []
    for index, evidence in enumerate(request_payload.evidence, start=1):
        evidence_lines.append(f"[{index}] {evidence.title} | {evidence.locator}")
        evidence_lines.append(evidence.content)
    evidence_block = "\n".join(evidence_lines)
    return (
        f"Question: {request_payload.question}\n\n"
        f"Evidence:\n{evidence_block}\n\n"
        "Answer the question using only this evidence."
    )


def _finalize_generated_text(text: str, evidence: list[GroundedGenerationEvidence]) -> str | None:
    normalized = " ".join(text.split()).strip()
    if not normalized or normalized.endswith("..."):
        return None
    if normalized[-1] in ",:;-/(":
        return None

    tokens = [token.lower().strip(".,:;!?") for token in normalized.rstrip(")").split()]
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
        return None

    completed = normalized if normalized[-1] in ".!?" else f"{normalized}."
    if _looks_like_truncated_supported_unit(completed, evidence):
        return None
    return completed


def _looks_like_truncated_supported_unit(answer: str, evidence: list[GroundedGenerationEvidence]) -> bool:
    normalized_answer = _normalize_text(answer).strip(" .")
    if not normalized_answer:
        return True

    for item in evidence:
        for unit in _split_evidence_units(item.content):
            normalized_unit = _normalize_text(unit).strip(" .")
            if not normalized_unit or normalized_unit == normalized_answer:
                continue
            if normalized_unit.startswith(normalized_answer):
                trailing = normalized_unit[len(normalized_answer) :].strip()
                if trailing:
                    return True
    return False


def _split_evidence_units(text: str) -> list[str]:
    return [
        " ".join(segment.split()).strip()
        for segment in re.split(r"(?<=[.!?])\s+|\n+", text)
        if segment.strip()
    ]


def _normalize_text(text: str) -> str:
    return " ".join(text.lower().split())
