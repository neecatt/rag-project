import io
import sys
import types
import zipfile

from app.services.text_extraction import DocumentTextExtractor


def test_markdown_extraction_emits_heading_and_bullet_structure():
    extractor = DocumentTextExtractor()

    result = extractor.extract_bytes(
        b"# Benefits\n\n## Enrollment\n\n- Open enrollment starts in November\n- Coverage begins in January\n",
        filename="benefits.md",
    )

    assert result.content_type == "text/markdown"
    assert result.metadata["section_titles"] == ["Benefits", "Enrollment"]
    assert result.metadata["structure_blocks"][0]["kind"] == "heading"
    assert result.metadata["structure_blocks"][1]["kind"] == "heading"
    assert result.metadata["structure_blocks"][2]["section_path"] == ["Benefits", "Enrollment"]
    assert result.metadata["structure_blocks"][2]["kind"] == "bullet"


def test_pdf_extraction_captures_page_titles_and_slide_like_metadata(monkeypatch):
    class FakePage:
        def __init__(self, text: str) -> None:
            self._text = text

        def extract_text(self) -> str:
            return self._text

    class FakeReader:
        def __init__(self, _buffer: io.BytesIO) -> None:
            self.pages = [
                FakePage("Quarterly Review\n- Revenue grew 18%\n- Margin improved 5%"),
                FakePage("Architecture Update\nParser now tracks page titles and slide labels."),
            ]

    monkeypatch.setitem(sys.modules, "pypdf", types.SimpleNamespace(PdfReader=FakeReader))
    extractor = DocumentTextExtractor()

    result = extractor.extract_bytes(b"%PDF-1.4 fake", filename="deck.pdf")

    assert result.content_type == "application/pdf"
    assert result.metadata["page_count"] == 2
    assert result.metadata["is_presentation_like"] is True
    assert result.metadata["pages"][0]["page_title"] == "Quarterly Review"
    assert result.metadata["pages"][0]["slide_label"] == "Slide 1"
    assert result.metadata["structure_blocks"][0]["kind"] == "slide_heading"
    assert result.metadata["structure_blocks"][1]["kind"] == "bullet"
    assert result.metadata["structure_blocks"][1]["page_number"] == 1


def test_docx_extraction_preserves_heading_structure():
    document_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body>
        <w:p>
          <w:pPr><w:pStyle w:val="Heading1"/></w:pPr>
          <w:r><w:t>Policy Overview</w:t></w:r>
        </w:p>
        <w:p>
          <w:r><w:t>Employees must complete onboarding within five days.</w:t></w:r>
        </w:p>
      </w:body>
    </w:document>
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", document_xml)

    extractor = DocumentTextExtractor()
    result = extractor.extract_bytes(buffer.getvalue(), filename="policy.docx")

    assert result.metadata["paragraph_count"] == 2
    assert result.metadata["section_titles"] == ["Policy Overview"]
    assert result.metadata["structure_blocks"][0]["heading_level"] == 1
    assert result.metadata["structure_blocks"][1]["section_path"] == ["Policy Overview"]
