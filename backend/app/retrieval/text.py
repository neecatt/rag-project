from __future__ import annotations

from app.services.document_models import SourceChunk


def build_index_text(chunk: SourceChunk) -> str:
    parts: list[str] = []
    if chunk.document_title:
        parts.extend([chunk.document_title, chunk.document_title])
    if chunk.section_title:
        parts.append(chunk.section_title)
    parts.append(chunk.text)
    return " ".join(part.strip() for part in parts if part and part.strip())
