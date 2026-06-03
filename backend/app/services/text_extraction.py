from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from xml.etree import ElementTree
import io
import re
import zipfile

from app.services.document_models import ExtractionResult


class TextExtractionError(RuntimeError):
    pass


class TextExtractor(ABC):
    supported_extensions: tuple[str, ...] = ()

    @abstractmethod
    def extract(self, content: bytes, *, filename: str | None = None) -> ExtractionResult:
        raise NotImplementedError


class PlainTextExtractor(TextExtractor):
    supported_extensions = (".txt",)

    def extract(self, content: bytes, *, filename: str | None = None) -> ExtractionResult:
        text = _normalize_newlines(_decode_text(content))
        structure = _structure_from_line_blocks(text)
        return ExtractionResult(
            text=text,
            content_type="text/plain",
            metadata={
                "filename": filename,
                "line_count": len(text.splitlines()),
                **structure,
            },
        )


class MarkdownExtractor(TextExtractor):
    supported_extensions = (".md", ".markdown")

    def extract(self, content: bytes, *, filename: str | None = None) -> ExtractionResult:
        text = _normalize_newlines(_decode_text(content))
        structure = _structure_from_markdown(text)
        return ExtractionResult(
            text=text,
            content_type="text/markdown",
            metadata={
                "filename": filename,
                "line_count": len(text.splitlines()),
                **structure,
            },
        )


class DocxExtractor(TextExtractor):
    supported_extensions = (".docx",)

    def extract(self, content: bytes, *, filename: str | None = None) -> ExtractionResult:
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                document_xml = archive.read("word/document.xml")
        except (KeyError, zipfile.BadZipFile) as exc:
            raise TextExtractionError("Invalid DOCX document") from exc

        root = ElementTree.fromstring(document_xml)
        namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        paragraphs: list[dict[str, object]] = []
        section_path: list[str] = []

        for paragraph in root.findall(".//w:p", namespace):
            parts = [node.text or "" for node in paragraph.findall(".//w:t", namespace)]
            text = "".join(parts).strip()
            if not text:
                continue

            style = paragraph.find("./w:pPr/w:pStyle", namespace)
            style_value = style.get(f"{{{namespace['w']}}}val") if style is not None else None

            heading_level = _docx_heading_level(style_value)
            is_bullet = paragraph.find("./w:pPr/w:numPr", namespace) is not None or bool(re.match(r"^[\-\*\u2022]\s+", text))

            if heading_level is not None:
                section_path = _update_section_path(section_path, text, heading_level)
                kind = "heading"
            elif is_bullet:
                kind = "bullet"
            else:
                kind = "paragraph"

            paragraphs.append(
                {
                    "text": text,
                    "kind": kind,
                    "heading_level": heading_level,
                    "section_title": section_path[-1] if section_path else None,
                    "section_path": list(section_path),
                }
            )

        text, structure = _assemble_blocks(paragraphs)
        return ExtractionResult(
            text=text,
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            metadata={
                "filename": filename,
                "paragraph_count": len(paragraphs),
                **structure,
            },
        )


class PdfExtractor(TextExtractor):
    supported_extensions = (".pdf",)

    def extract(self, content: bytes, *, filename: str | None = None) -> ExtractionResult:
        reader = _get_pdf_reader(io.BytesIO(content))
        all_pages: list[str] = []
        all_blocks: list[dict[str, object]] = []
        pages: list[dict[str, object]] = []
        section_path: list[str] = []
        offset = 0

        for index, page in enumerate(reader.pages, start=1):
            raw_text = page.extract_text() or ""
            page_text = _normalize_newlines(raw_text).strip()
            if not page_text:
                continue

            if all_pages:
                offset += 1

            page_blocks, page_metadata, section_path = _pdf_page_structure(
                page_text=page_text,
                page_number=index,
                base_offset=offset,
                section_path=section_path,
            )
            all_pages.append(page_text)
            all_blocks.extend(page_blocks)
            pages.append(page_metadata)
            offset += len(page_text)

        text = "\f".join(all_pages)
        return ExtractionResult(
            text=text,
            content_type="application/pdf",
            metadata={
                "filename": filename,
                "page_count": len(pages),
                "pages": pages,
                "structure_blocks": all_blocks,
                "section_titles": _unique_section_titles(all_blocks),
                "is_presentation_like": any(page.get("is_slide_like") for page in pages),
            },
        )


class DocumentTextExtractor:
    def __init__(self) -> None:
        self._extractors = (
            PlainTextExtractor(),
            MarkdownExtractor(),
            DocxExtractor(),
            PdfExtractor(),
        )

    def extract_bytes(self, content: bytes, *, filename: str) -> ExtractionResult:
        suffix = Path(filename).suffix.lower()
        for extractor in self._extractors:
            if suffix in extractor.supported_extensions:
                return extractor.extract(content, filename=filename)
        raise TextExtractionError(f"Unsupported file type: {suffix or 'unknown'}")

    def extract_file(self, path: str | Path) -> ExtractionResult:
        file_path = Path(path)
        return self.extract_bytes(file_path.read_bytes(), filename=file_path.name)


def _get_pdf_reader(buffer: io.BytesIO):
    try:
        from pypdf import PdfReader
    except ImportError:
        try:
            from PyPDF2 import PdfReader
        except ImportError as exc:
            raise TextExtractionError("PDF extraction requires pypdf or PyPDF2") from exc
    return PdfReader(buffer)


def _decode_text(content: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise TextExtractionError("Unable to decode text content")


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _structure_from_line_blocks(text: str) -> dict[str, object]:
    raw_blocks = _iter_nonempty_blocks(text)
    context = _new_structure_context()
    blocks = _build_structured_blocks(raw_blocks, context=context)
    return {
        "structure_blocks": blocks,
        "section_titles": _unique_section_titles(blocks),
    }


def _structure_from_markdown(text: str) -> dict[str, object]:
    blocks: list[dict[str, object]] = []
    section_path: list[str] = []
    position = 0

    for raw_block in re.split(r"\n\s*\n", text):
        block = raw_block.strip()
        raw_start = text.find(raw_block, position)
        raw_end = raw_start + len(raw_block)
        position = raw_end
        if not block:
            continue

        char_start = text.find(block, raw_start, raw_end if raw_end > raw_start else None)
        char_end = char_start + len(block)
        heading_match = re.match(r"^(#{1,6})\s+(.*)$", block)
        if heading_match:
            heading_level = len(heading_match.group(1))
            title = heading_match.group(2).strip()
            section_path = _update_section_path(section_path, title, heading_level)
            kind = "heading"
            section_title = title
        else:
            heading_level = None
            section_title = section_path[-1] if section_path else None
            if _looks_like_bullets(block.splitlines()):
                kind = "bullet"
            else:
                kind = "paragraph"

        blocks.append(
            {
                "text": block,
                "char_start": char_start,
                "char_end": char_end,
                "kind": kind,
                "section_title": section_title,
                "section_path": list(section_path),
                "page_number": None,
                "slide_label": None,
                "heading_level": heading_level,
            }
        )

    return {
        "structure_blocks": blocks,
        "section_titles": _unique_section_titles(blocks),
    }


def _assemble_blocks(paragraphs: list[dict[str, object]]) -> tuple[str, dict[str, object]]:
    assembled_blocks: list[dict[str, object]] = []
    text_parts: list[str] = []
    offset = 0

    for paragraph in paragraphs:
        block_text = str(paragraph["text"]).strip()
        if not block_text:
            continue
        if text_parts:
            text_parts.append("\n\n")
            offset += 2
        char_start = offset
        text_parts.append(block_text)
        offset += len(block_text)
        assembled_blocks.append(
            {
                "text": block_text,
                "char_start": char_start,
                "char_end": offset,
                "kind": paragraph.get("kind", "paragraph"),
                "section_title": paragraph.get("section_title"),
                "section_path": paragraph.get("section_path", []),
                "page_number": paragraph.get("page_number"),
                "slide_label": paragraph.get("slide_label"),
                "heading_level": paragraph.get("heading_level"),
            }
        )

    return "".join(text_parts), {
        "structure_blocks": assembled_blocks,
        "section_titles": _unique_section_titles(assembled_blocks),
    }


def _pdf_page_structure(
    *,
    page_text: str,
    page_number: int,
    base_offset: int,
    section_path: list[str],
) -> tuple[list[dict[str, object]], dict[str, object], list[str]]:
    lines = [line.strip() for line in page_text.splitlines() if line.strip()]
    title = _detect_page_title(lines)
    bullet_count = sum(1 for line in lines if _is_bullet_line(line))
    timing_count = sum(1 for line in lines if _is_timing_line(line))
    resume_section_count = sum(1 for line in lines if _resume_section_title(line) is not None)
    is_resume_like = resume_section_count >= 2 or (
        resume_section_count >= 1 and any(_looks_like_contact_line(line) for line in lines[:4])
    )
    is_slide_like = (bullet_count >= 2 or timing_count >= 2 or (title is not None and len(lines) <= 12)) and not is_resume_like
    slide_label = f"Slide {page_number}" if is_slide_like else None
    page_label = slide_label or f"Page {page_number}"
    raw_blocks = _iter_nonempty_blocks(page_text)
    context = _new_structure_context(
        section_path=section_path,
        page_number=page_number,
        slide_label=slide_label,
        page_title=title,
        is_resume_like=is_resume_like,
        is_slide_like=is_slide_like,
    )
    blocks = _build_structured_blocks(raw_blocks, context=context)

    return blocks, {
        "page_number": page_number,
        "char_start": base_offset,
        "char_end": base_offset + len(page_text),
        "page_title": title,
        "line_count": len(lines),
        "bullet_count": bullet_count,
        "timing_count": timing_count,
        "resume_like": is_resume_like,
        "is_slide_like": is_slide_like,
        "slide_label": slide_label,
        "page_label": page_label,
    }, context["section_path"]


def _detect_page_title(lines: list[str]) -> str | None:
    if not lines:
        return None
    first = lines[0].strip()
    if len(first) > 100:
        return None
    if _resume_section_title(first) is not None or _looks_like_contact_line(first):
        return None
    if len(lines) == 1:
        return first
    if first.isupper():
        return first.title()
    second = lines[1].strip() if len(lines) > 1 else ""
    if _is_bullet_line(second) or first.endswith(":"):
        return first.rstrip(":")
    words = first.split()
    if 1 <= len(words) <= 8:
        return first
    return None


def _looks_like_bullets(lines: list[str]) -> bool:
    return bool(lines) and sum(1 for line in lines if _is_bullet_line(line.strip())) >= max(1, len(lines) // 2)


def _is_bullet_line(line: str) -> bool:
    return bool(re.match(r"^(?:[\-\*\u2022]|[0-9]+[.)])\s+\S+", line))


def _iter_nonempty_blocks(text: str) -> list[dict[str, object]]:
    blocks: list[dict[str, object]] = []
    for match in re.finditer(r"[^\n]+(?:\n(?!\n)[^\n]+)*", text):
        block_text = match.group(0).strip()
        if not block_text:
            continue
        char_start = text.find(block_text, match.start(), match.end())
        blocks.append(
            {
                "text": block_text,
                "char_start": char_start,
                "char_end": char_start + len(block_text),
            }
        )
    return blocks


def _new_structure_context(
    *,
    section_path: list[str] | None = None,
    page_number: int | None = None,
    slide_label: str | None = None,
    page_title: str | None = None,
    is_resume_like: bool = False,
    is_slide_like: bool = False,
) -> dict[str, object]:
    return {
        "section_path": list(section_path or []),
        "page_number": page_number,
        "slide_label": slide_label,
        "page_title": page_title,
        "is_resume_like": is_resume_like,
        "is_slide_like": is_slide_like,
        "seen_structured_section": bool(section_path),
    }


def _build_structured_blocks(raw_blocks: list[dict[str, object]], *, context: dict[str, object]) -> list[dict[str, object]]:
    blocks: list[dict[str, object]] = []
    for raw_block in raw_blocks:
        emitted = _parse_block(raw_block, context=context)
        blocks.extend(emitted)
    return blocks


def _parse_block(raw_block: dict[str, object], *, context: dict[str, object]) -> list[dict[str, object]]:
    text = str(raw_block["text"]).strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return []

    resume_title = _resume_section_title(lines[0])
    if resume_title is not None:
        return _emit_heading_with_optional_body(
            raw_block,
            context=context,
            title=resume_title,
            kind="resume_heading",
            heading_level=1,
            body_kind=_body_kind_for_section(resume_title, lines[1:]),
        )

    if context["is_slide_like"]:
        return _parse_slide_block(raw_block, context=context)

    if _should_emit_header_block(lines, context):
        context["seen_structured_section"] = False
        return [_make_block(raw_block, context=context, kind="header")]

    kind = _classify_content_kind(lines, context=context)
    return [_make_block(raw_block, context=context, kind=kind)]


def _parse_slide_block(raw_block: dict[str, object], *, context: dict[str, object]) -> list[dict[str, object]]:
    text = str(raw_block["text"]).strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return []

    page_title = context.get("page_title")
    if page_title and lines[0] == page_title:
        slide_root = _update_section_path([], page_title, 1)
        context["section_path"] = slide_root
        context["seen_structured_section"] = True
        if len(lines) == 1:
            return [_make_block(raw_block, context=context, kind="slide_heading", heading_level=1)]
        heading_block, remainder = _split_block_after_first_line(raw_block)
        emitted = [_make_block(heading_block, context=context, kind="slide_heading", heading_level=1)]
        if remainder is not None:
            emitted.extend(_parse_slide_block(remainder, context=context))
        return emitted

    inline_title = _inline_slide_subheading(lines[0], page_title=page_title)
    if inline_title is not None:
        context["section_path"] = _section_path_with_root(context=context, title=inline_title)
        context["seen_structured_section"] = True
        if len(lines) == 1:
            return [_make_block(raw_block, context=context, kind="slide_section_heading", heading_level=2)]
        heading_block, remainder = _split_block_after_first_line(raw_block)
        emitted = [_make_block(heading_block, context=context, kind="slide_section_heading", heading_level=2)]
        if remainder is not None:
            emitted.extend(_parse_slide_block(remainder, context=context))
        return emitted

    grouped_blocks = _split_slide_content_groups(raw_block)
    if len(grouped_blocks) > 1:
        return [_make_block(group, context=context, kind=str(group["kind"])) for group in grouped_blocks]
    only_kind = str(grouped_blocks[0]["kind"])
    return [_make_block(raw_block, context=context, kind=only_kind)]


def _emit_heading_with_optional_body(
    raw_block: dict[str, object],
    *,
    context: dict[str, object],
    title: str,
    kind: str,
    heading_level: int,
    body_kind: str,
) -> list[dict[str, object]]:
    context["section_path"] = _update_section_path([], title, heading_level)
    context["seen_structured_section"] = True
    lines = [line.strip() for line in str(raw_block["text"]).splitlines() if line.strip()]
    if len(lines) == 1:
        return [_make_block(raw_block, context=context, kind=kind, heading_level=heading_level)]
    heading_block, remainder = _split_block_after_first_line(raw_block)
    emitted = [_make_block(heading_block, context=context, kind=kind, heading_level=heading_level)]
    if remainder is not None:
        emitted.append(_make_block(remainder, context=context, kind=body_kind))
    return emitted


def _split_block_after_first_line(raw_block: dict[str, object]) -> tuple[dict[str, object], dict[str, object] | None]:
    text = str(raw_block["text"])
    if "\n" not in text:
        return raw_block, None
    first_line, remainder = text.split("\n", 1)
    heading_text = first_line.strip()
    remainder_text = remainder.strip()
    heading_start = int(raw_block["char_start"])
    heading_block = {
        "text": heading_text,
        "char_start": heading_start,
        "char_end": heading_start + len(heading_text),
    }
    if not remainder_text:
        return heading_block, None
    remainder_start = text.find(remainder_text)
    body_start = int(raw_block["char_start"]) + remainder_start
    body_block = {
        "text": remainder_text,
        "char_start": body_start,
        "char_end": body_start + len(remainder_text),
    }
    return heading_block, body_block


def _make_block(
    raw_block: dict[str, object],
    *,
    context: dict[str, object],
    kind: str,
    heading_level: int | None = None,
) -> dict[str, object]:
    section_path = list(context.get("section_path") or [])
    section_title = section_path[-1] if section_path else context.get("page_title")
    return {
        "text": str(raw_block["text"]).strip(),
        "char_start": raw_block["char_start"],
        "char_end": raw_block["char_end"],
        "kind": kind,
        "section_title": section_title,
        "section_path": section_path,
        "page_number": context.get("page_number"),
        "slide_label": context.get("slide_label"),
        "heading_level": heading_level,
    }


def _classify_content_kind(lines: list[str], *, context: dict[str, object]) -> str:
    section_title = str((context.get("section_path") or [None])[-1] or "")
    normalized_section = _normalize_heading_key(section_title)
    if _looks_like_bullets(lines):
        if normalized_section in {"skills", "technical skills", "languages", "certifications"}:
            return "skills_group"
        return "bullet_group"
    if normalized_section in {"skills", "technical skills", "languages", "certifications"}:
        return "skills_group"
    if normalized_section in {"experience", "work experience", "professional experience", "projects"}:
        return "experience_entry"
    if normalized_section == "education":
        return "education_entry"
    return "paragraph"


def _body_kind_for_section(title: str, body_lines: list[str]) -> str:
    if not body_lines:
        return "paragraph"
    normalized_title = _normalize_heading_key(title)
    if normalized_title in {"skills", "technical skills", "languages", "certifications"}:
        return "skills_group"
    if normalized_title in {"experience", "work experience", "professional experience", "projects"}:
        return "experience_entry"
    if normalized_title == "education":
        return "education_entry"
    if _looks_like_bullets(body_lines):
        return "bullet_group"
    return "paragraph"


def _should_emit_header_block(lines: list[str], context: dict[str, object]) -> bool:
    if context.get("seen_structured_section"):
        return False
    if context.get("is_slide_like"):
        return False
    if any(_resume_section_title(line) for line in lines):
        return False
    return _looks_like_contact_line(lines[0]) or _looks_like_profile_header(lines)


def _looks_like_profile_header(lines: list[str]) -> bool:
    if not lines:
        return False
    first = lines[0].strip()
    if len(first.split()) > 5 or len(first) > 60:
        return False
    header_markers = sum(1 for line in lines if _looks_like_contact_line(line))
    return bool(_looks_like_name_line(first) or header_markers >= 1)


def _looks_like_name_line(line: str) -> bool:
    words = [word for word in re.split(r"\s+", line.strip()) if word]
    if not 2 <= len(words) <= 4:
        return False
    return all(word[:1].isalpha() and (word.isupper() or word[:1].isupper()) for word in words)


def _looks_like_contact_line(line: str) -> bool:
    lowered = line.lower()
    return bool(
        re.search(r"[\w.+-]+@[\w.-]+\.[a-z]{2,}", lowered)
        or re.search(r"(?:\+\d{1,3}\s*)?(?:\(?\d{2,4}\)?[\s.-]*){2,}\d{3,4}", line)
        or "linkedin.com" in lowered
        or "github.com" in lowered
        or "portfolio" in lowered
        or re.search(r"\b(?:berlin|london|remote|new york|san francisco)\b", lowered)
    )


def _inline_slide_subheading(line: str, *, page_title: str | None) -> str | None:
    candidate = line.rstrip(":").strip()
    normalized = _normalize_heading_key(candidate)
    if not candidate or candidate == page_title:
        return None
    if normalized in {"agenda", "schedule", "timeline", "timing", "next steps", "discussion"}:
        return candidate
    if len(candidate.split()) <= 5 and (line.endswith(":") or candidate.isupper()):
        return candidate.title() if candidate.isupper() else candidate
    return None


def _section_path_with_root(*, context: dict[str, object], title: str) -> list[str]:
    page_title = context.get("page_title")
    if page_title:
        return [str(page_title), title]
    return [title]


def _resume_section_title(line: str) -> str | None:
    normalized = _normalize_heading_key(line)
    return _RESUME_SECTION_TITLES.get(normalized)


def _normalize_heading_key(line: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", line.lower()).strip()
    return re.sub(r"\s+", " ", normalized)


def _is_timing_line(line: str) -> bool:
    return bool(
        re.match(r"^(?:\d{1,2}[:.]\d{2}|\d{1,2}\s*(?:am|pm))\s*(?:[-:]\s*|\u2013\s*)\S+", line, flags=re.IGNORECASE)
        or re.match(r"^\d+\s*(?:min|mins|minutes|hour|hours)\b", line, flags=re.IGNORECASE)
    )


def _split_slide_content_groups(raw_block: dict[str, object]) -> list[dict[str, object]]:
    grouped: list[dict[str, object]] = []
    current_kind: str | None = None
    current_lines: list[str] = []
    current_start: int | None = None
    current_end: int | None = None

    for line_text, line_start, line_end in _iter_nonempty_lines(raw_block):
        line_kind = _slide_line_kind(line_text)
        if current_kind is None:
            current_kind = line_kind
            current_lines = [line_text]
            current_start = line_start
            current_end = line_end
            continue
        if line_kind == current_kind:
            current_lines.append(line_text)
            current_end = line_end
            continue
        grouped.append(
            {
                "text": "\n".join(current_lines),
                "char_start": current_start,
                "char_end": current_end,
                "kind": current_kind,
            }
        )
        current_kind = line_kind
        current_lines = [line_text]
        current_start = line_start
        current_end = line_end

    if current_kind is not None and current_start is not None and current_end is not None:
        grouped.append(
            {
                "text": "\n".join(current_lines),
                "char_start": current_start,
                "char_end": current_end,
                "kind": current_kind,
            }
        )

    return grouped


def _iter_nonempty_lines(raw_block: dict[str, object]) -> list[tuple[str, int, int]]:
    text = str(raw_block["text"])
    block_start = int(raw_block["char_start"])
    lines: list[tuple[str, int, int]] = []
    for match in re.finditer(r"[^\n]+", text):
        line_text = match.group(0).strip()
        if not line_text:
            continue
        relative_start = text.find(line_text, match.start(), match.end())
        line_start = block_start + relative_start
        lines.append((line_text, line_start, line_start + len(line_text)))
    return lines


def _slide_line_kind(line: str) -> str:
    if _is_timing_line(line):
        return "timing_group"
    if _is_bullet_line(line):
        return "bullet_group"
    return "slide_paragraph"


def _docx_heading_level(style_value: str | None) -> int | None:
    if not style_value:
        return None
    match = re.match(r"Heading([1-6])$", style_value, flags=re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1))


def _update_section_path(section_path: list[str], title: str, level: int) -> list[str]:
    while len(section_path) >= level:
        section_path.pop()
    section_path.append(title)
    return list(section_path)


def _unique_section_titles(blocks: list[dict[str, object]]) -> list[str]:
    seen: list[str] = []
    for block in blocks:
        title = block.get("section_title")
        if isinstance(title, str) and title and title not in seen:
            seen.append(title)
    return seen


_RESUME_SECTION_TITLES = {
    "skills": "Skills",
    "technical skills": "Technical Skills",
    "experience": "Experience",
    "work experience": "Work Experience",
    "professional experience": "Professional Experience",
    "education": "Education",
    "projects": "Projects",
    "certifications": "Certifications",
    "languages": "Languages",
}
