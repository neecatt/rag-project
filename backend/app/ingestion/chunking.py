from __future__ import annotations

from dataclasses import dataclass, field
import re
from uuid import uuid4

from app.services.document_models import SourceChunk


@dataclass(slots=True)
class ChunkingConfig:
    max_chars: int = 900
    overlap_chars: int = 150
    min_chunk_chars: int = 150


@dataclass(slots=True)
class ChunkingRequest:
    document_id: str
    document_version_id: str
    text: str
    metadata: dict[str, object] = field(default_factory=dict)
    source_id: str | None = None
    tenant_id: str | None = None
    workspace_id: str | None = None
    document_title: str | None = None


class DocumentChunker:
    def __init__(self, config: ChunkingConfig | None = None) -> None:
        self.config = config or ChunkingConfig()

    def chunk(self, request: ChunkingRequest) -> list[SourceChunk]:
        text = _normalize_newlines(request.text).strip()
        if not text:
            return []

        segments = _segment_text(text, request.metadata)
        chunks: list[SourceChunk] = []
        current_segments: list[dict[str, object]] = []
        current_text = ""

        for segment in segments:
            boundary_break = bool(current_segments and _should_break_on_structure_change(current_segments[-1], segment))
            should_flush_for_boundary = bool(
                boundary_break
                and (
                    _is_hard_boundary(current_segments[-1], segment)
                    or _requires_tight_boundary(current_segments[-1], segment)
                    or len(current_text) >= max(self.config.min_chunk_chars // 2, 80)
                )
            )
            proposed = _join_segments(current_text, str(segment["text"]))
            if should_flush_for_boundary or (current_text and len(proposed) > self.config.max_chars):
                chunks.append(self._build_chunk(request=request, chunk_index=len(chunks), segments=current_segments))
                current_segments = [] if should_flush_for_boundary else _carry_overlap_segments(current_segments, self.config.overlap_chars)
                current_text = _segments_text(current_segments)

            current_segments.append(segment)
            current_text = _join_segments(current_text, str(segment["text"]))

        if current_segments:
            if chunks and len(current_text.strip()) < self.config.min_chunk_chars and _can_merge_trailing_chunk(
                list(chunks[-1].metadata["_segments"]),
                current_segments,
            ):
                previous = chunks.pop()
                merged_segments = list(previous.metadata["_segments"]) + current_segments
                chunks.append(
                    self._build_chunk(
                        request=request,
                        chunk_index=previous.chunk_index,
                        segments=merged_segments,
                        chunk_id=previous.chunk_id,
                    )
                )
            else:
                chunks.append(self._build_chunk(request=request, chunk_index=len(chunks), segments=current_segments))

        for chunk in chunks:
            chunk.metadata.pop("_segments", None)
        return chunks

    def _build_chunk(
        self,
        *,
        request: ChunkingRequest,
        chunk_index: int,
        segments: list[dict[str, object]],
        chunk_id: str | None = None,
    ) -> SourceChunk:
        normalized = _segments_text(segments).strip()
        char_start = int(segments[0]["char_start"])
        char_end = int(segments[-1]["char_end"])
        section_path = _chunk_section_path(segments)
        section_title = section_path[-1] if section_path else _last_value(segments, "section_title")
        page_start = _first_numeric(segments, "page_number")
        page_end = _last_numeric(segments, "page_number")
        page_number = page_start if page_start == page_end else page_start
        slide_label = _last_value(segments, "slide_label")
        heading_level = _last_numeric(segments, "heading_level")
        kinds = _unique_values(segments, "kind")

        metadata = dict(request.metadata)
        metadata.update(
            {
                "char_start": char_start,
                "char_end": char_end,
                "chunk_index": chunk_index,
                "section_title": section_title,
                "section_path": section_path,
                "heading_level": heading_level,
                "page_number": page_number,
                "page_start": page_start,
                "page_end": page_end,
                "slide_label": slide_label,
                "segment_kinds": kinds,
                "word_count": len(normalized.split()),
                "_segments": segments,
            }
        )
        if slide_label:
            metadata["locator_hint"] = slide_label
        elif page_start is not None and page_end is not None and page_start != page_end:
            metadata["locator_hint"] = f"Pages {page_start}-{page_end}"
        elif page_start is not None:
            metadata["locator_hint"] = f"Page {page_start}"
        elif section_title:
            metadata["locator_hint"] = section_title

        return SourceChunk(
            chunk_id=chunk_id or str(uuid4()),
            document_id=request.document_id,
            document_version_id=request.document_version_id,
            chunk_index=chunk_index,
            text=normalized,
            metadata=metadata,
            source_id=request.source_id,
            tenant_id=request.tenant_id,
            workspace_id=request.workspace_id,
            document_title=request.document_title,
            section_title=section_title,
            page_number=page_number,
            token_count=_estimate_token_count(normalized),
            char_start=char_start,
            char_end=char_end,
        )


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _segment_text(text: str, metadata: dict[str, object]) -> list[dict[str, object]]:
    blocks = metadata.get("structure_blocks")
    if isinstance(blocks, list) and blocks:
        return [_normalize_segment(block) for block in blocks if isinstance(block, dict) and str(block.get("text", "")).strip()]
    return _segment_text_fallback(text)


def _normalize_segment(block: dict[str, object]) -> dict[str, object]:
    return {
        "text": str(block.get("text", "")).strip(),
        "char_start": int(block.get("char_start", 0)),
        "char_end": int(block.get("char_end", 0)),
        "section_title": block.get("section_title"),
        "section_path": list(block.get("section_path") or []),
        "page_number": block.get("page_number"),
        "slide_label": block.get("slide_label"),
        "heading_level": block.get("heading_level"),
        "kind": block.get("kind", "paragraph"),
    }


def _segment_text_fallback(text: str) -> list[dict[str, object]]:
    segments: list[dict[str, object]] = []
    page_number = 1
    section_title: str | None = None
    section_path: list[str] = []
    cursor = 0

    for block in re.split(r"\n\s*\n", text):
        stripped = block.strip()
        if not stripped:
            cursor += len(block) + 2
            continue
        while stripped.startswith("\f"):
            stripped = stripped[1:].lstrip()
            page_number += 1
        if not stripped:
            continue
        heading_match = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        heading_level = None
        kind = "paragraph"
        if heading_match:
            heading_level = len(heading_match.group(1))
            section_title = heading_match.group(2).strip()
            section_path = _update_section_path(section_path, section_title, heading_level)
            kind = "heading"
        elif re.match(r"^(?:[\-\*\u2022]|[0-9]+[.)])\s+\S+", stripped.splitlines()[0]):
            kind = "bullet"
        char_start = text.find(stripped, cursor)
        char_end = char_start + len(stripped)
        cursor = char_end
        segments.append(
            {
                "text": stripped,
                "char_start": char_start,
                "char_end": char_end,
                "section_title": section_title,
                "section_path": list(section_path),
                "page_number": page_number if "\f" in block or page_number > 1 else None,
                "slide_label": None,
                "heading_level": heading_level,
                "kind": kind,
            }
        )
        page_number += block.count("\f")
    return segments


def _carry_overlap_segments(segments: list[dict[str, object]], overlap_chars: int) -> list[dict[str, object]]:
    if overlap_chars <= 0 or not segments:
        return []
    carried: list[dict[str, object]] = []
    total = 0
    for segment in reversed(segments):
        carried.insert(0, segment)
        total += len(str(segment["text"]))
        if total >= overlap_chars:
            break
    return carried


def _segments_text(segments: list[dict[str, object]]) -> str:
    return _join_segments("", *[str(segment["text"]) for segment in segments]).strip()


def _join_segments(initial: str, *parts: str) -> str:
    text = initial
    for part in parts:
        if not text:
            text = part
        elif part:
            text = f"{text}\n\n{part}"
    return text


def _should_break_on_structure_change(left: dict[str, object], right: dict[str, object]) -> bool:
    left_page = left.get("page_number")
    right_page = right.get("page_number")
    if left_page is not None and right_page is not None and left_page != right_page:
        return True
    left_slide = left.get("slide_label")
    right_slide = right.get("slide_label")
    if left_slide and right_slide and left_slide != right_slide:
        return True
    if right.get("kind") in {"heading", "resume_heading", "page_heading", "slide_heading", "slide_section_heading"}:
        return True
    left_path = list(left.get("section_path") or [])
    right_path = list(right.get("section_path") or [])
    return bool(left_path and right_path and left_path != right_path)


def _is_hard_boundary(left: dict[str, object], right: dict[str, object]) -> bool:
    return (
        left.get("page_number") != right.get("page_number")
        or left.get("slide_label") != right.get("slide_label")
    )


def _requires_tight_boundary(left: dict[str, object], right: dict[str, object]) -> bool:
    left_kind = left.get("kind")
    right_kind = right.get("kind")
    if left_kind in {"header", "resume_heading", "slide_heading", "slide_section_heading"}:
        return True
    if right_kind in {"resume_heading", "slide_heading", "slide_section_heading"}:
        return True
    left_path = list(left.get("section_path") or [])
    right_path = list(right.get("section_path") or [])
    return bool(right_path and left_path != right_path)


def _chunk_section_path(segments: list[dict[str, object]]) -> list[str]:
    for segment in reversed(segments):
        path = list(segment.get("section_path") or [])
        if path:
            return path
    return []


def _last_value(segments: list[dict[str, object]], key: str):
    for segment in reversed(segments):
        value = segment.get(key)
        if value not in (None, "", []):
            return value
    return None


def _first_numeric(segments: list[dict[str, object]], key: str) -> int | None:
    for segment in segments:
        value = segment.get(key)
        if isinstance(value, int):
            return value
    return None


def _last_numeric(segments: list[dict[str, object]], key: str) -> int | None:
    for segment in reversed(segments):
        value = segment.get(key)
        if isinstance(value, int):
            return value
    return None


def _unique_values(segments: list[dict[str, object]], key: str) -> list[object]:
    values: list[object] = []
    for segment in segments:
        value = segment.get(key)
        if value in (None, "", []):
            continue
        if value not in values:
            values.append(value)
    return values


def _update_section_path(section_path: list[str], title: str, level: int) -> list[str]:
    while len(section_path) >= level:
        section_path.pop()
    section_path.append(title)
    return list(section_path)


def _estimate_token_count(text: str) -> int:
    return len(text.split())


def _can_merge_trailing_chunk(
    previous_segments: list[dict[str, object]],
    current_segments: list[dict[str, object]],
) -> bool:
    if not previous_segments or not current_segments:
        return True
    return not _requires_tight_boundary(previous_segments[-1], current_segments[0])
