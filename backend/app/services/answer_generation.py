from __future__ import annotations

from dataclasses import dataclass
import json
import logging
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
                        "For narrow factual questions, answer directly in one short sentence when possible. "
                        "For synthesis, comparison, or summary questions, answer in two to four concise sentences that cover the needed points. "
                        "Use only the evidence that is necessary for the answer, and do not add generic preambles, source lists, or unsupported filler. "
                        "If the evidence contains labeled fields, sections, or lists that answer the question, extract only the relevant facts. "
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
        return GroundedGenerationResult(
            content=answer,
            used_evidence_indices=list(range(len(request_payload.evidence))),
        )


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
            normalized = " ".join(result.content.split()).strip()
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
