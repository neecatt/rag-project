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
    blocks: list[dict[str, object]] = []
    for match in re.finditer(r"[^\n]+(?:\n(?!\n)[^\n]+)*", text):
        block_text = match.group(0).strip()
        if not block_text:
            continue
        kind = "bullet" if _looks_like_bullets(block_text.splitlines()) else "paragraph"
        blocks.append(
            {
                "text": block_text,
                "char_start": match.start(),
                "char_end": match.end(),
                "kind": kind,
                "section_title": None,
                "section_path": [],
                "page_number": None,
                "slide_label": None,
                "heading_level": None,
            }
        )
    return {
        "structure_blocks": blocks,
        "section_titles": [],
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
    is_slide_like = bullet_count >= 2 or (title is not None and len(lines) <= 12)
    slide_label = f"Slide {page_number}" if is_slide_like else None
    page_label = slide_label or f"Page {page_number}"
    blocks: list[dict[str, object]] = []

    if title:
        section_path = _update_section_path(section_path, title, 1)

    cursor = 0
    current_paragraph: list[str] = []
    current_paragraph_start: int | None = None

    def flush_paragraph() -> None:
        nonlocal current_paragraph, current_paragraph_start
        if not current_paragraph or current_paragraph_start is None:
            return
        paragraph_text = " ".join(current_paragraph).strip()
        paragraph_end = current_paragraph_start + len(paragraph_text)
        blocks.append(
            {
                "text": paragraph_text,
                "char_start": base_offset + current_paragraph_start,
                "char_end": base_offset + paragraph_end,
                "kind": "paragraph",
                "section_title": section_path[-1] if section_path else title,
                "section_path": list(section_path),
                "page_number": page_number,
                "slide_label": slide_label,
                "heading_level": None,
            }
        )
        current_paragraph = []
        current_paragraph_start = None

    title_consumed = False
    for line in lines:
        line_start = page_text.find(line, cursor)
        line_end = line_start + len(line)
        cursor = line_end

        if title and not title_consumed and line == title:
            flush_paragraph()
            blocks.append(
                {
                    "text": line,
                    "char_start": base_offset + line_start,
                    "char_end": base_offset + line_end,
                    "kind": "slide_heading" if is_slide_like else "page_heading",
                    "section_title": title,
                    "section_path": list(section_path),
                    "page_number": page_number,
                    "slide_label": slide_label,
                    "heading_level": 1,
                }
            )
            title_consumed = True
            continue

        if _is_bullet_line(line):
            flush_paragraph()
            blocks.append(
                {
                    "text": line,
                    "char_start": base_offset + line_start,
                    "char_end": base_offset + line_end,
                    "kind": "bullet",
                    "section_title": section_path[-1] if section_path else title,
                    "section_path": list(section_path),
                    "page_number": page_number,
                    "slide_label": slide_label,
                    "heading_level": None,
                }
            )
            continue

        if current_paragraph_start is None:
            current_paragraph_start = line_start
        current_paragraph.append(line)

    flush_paragraph()

    return blocks, {
        "page_number": page_number,
        "char_start": base_offset,
        "char_end": base_offset + len(page_text),
        "page_title": title,
        "line_count": len(lines),
        "bullet_count": bullet_count,
        "is_slide_like": is_slide_like,
        "slide_label": slide_label,
        "page_label": page_label,
    }, section_path


def _detect_page_title(lines: list[str]) -> str | None:
    if not lines:
        return None
    first = lines[0].strip()
    if len(first) > 100:
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
