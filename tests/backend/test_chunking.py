import unittest

from backend.app.ingestion.chunking import ChunkingConfig, ChunkingRequest, DocumentChunker


class ChunkingTests(unittest.TestCase):
    def test_chunking_preserves_section_page_and_overlap_metadata(self) -> None:
        text = (
            "# PTO Policy\n\n"
            "Employees accrue paid time off monthly. Carryover is limited to forty hours. "
            "Unused hours beyond the cap are forfeited at year end.\n\n"
            "\f# Exceptions\n\n"
            "Managers may approve emergency carryover for statutory or medical reasons. "
            "Approvals must be documented in writing and retained with payroll records."
        )
        chunker = DocumentChunker(ChunkingConfig(max_chars=140, overlap_chars=30, min_chunk_chars=40))

        chunks = chunker.chunk(
            ChunkingRequest(
                document_id="doc-1",
                document_version_id="ver-1",
                document_title="Employee Handbook",
                source_id="source-1",
                tenant_id="tenant-1",
                text=text,
                metadata={"classification": "internal"},
            )
        )

        self.assertGreaterEqual(len(chunks), 2)
        self.assertEqual(chunks[0].section_title, "PTO Policy")
        self.assertEqual(chunks[-1].section_title, "Exceptions")
        self.assertEqual(chunks[-1].page_number, 2)
        self.assertEqual(chunks[0].metadata["classification"], "internal")
        self.assertEqual(chunks[0].char_start, 0)
        self.assertIsNotNone(chunks[0].char_end)
        self.assertIsNotNone(chunks[1].char_start)
        self.assertLess(chunks[1].char_start, chunks[0].char_end)
        self.assertEqual(chunks[-1].to_citation().locator, "Page 2")
        self.assertEqual(chunks[-1].metadata["section_path"], ["Exceptions"])
        self.assertIn("segment_kinds", chunks[-1].metadata)

    def test_chunking_uses_structure_blocks_for_slide_boundaries_and_metadata(self) -> None:
        text = (
            "Quarterly Review\n"
            "- Revenue grew 18%\n"
            "- Margin improved 5%\f"
            "Roadmap\n"
            "- Launch OCR sync\n"
            "- Add durable retries"
        )
        chunker = DocumentChunker(ChunkingConfig(max_chars=220, overlap_chars=0, min_chunk_chars=20))

        chunks = chunker.chunk(
            ChunkingRequest(
                document_id="doc-2",
                document_version_id="ver-2",
                document_title="QBR Deck",
                text=text,
                metadata={
                    "structure_blocks": [
                        {
                            "text": "Quarterly Review",
                            "char_start": 0,
                            "char_end": 16,
                            "kind": "slide_heading",
                            "page_number": 1,
                            "slide_label": "Slide 1",
                            "section_title": "Quarterly Review",
                            "section_path": ["Quarterly Review"],
                            "heading_level": 1,
                        },
                        {
                            "text": "- Revenue grew 18%\n- Margin improved 5%",
                            "char_start": 17,
                            "char_end": 57,
                            "kind": "bullet",
                            "page_number": 1,
                            "slide_label": "Slide 1",
                            "section_title": "Quarterly Review",
                            "section_path": ["Quarterly Review"],
                            "heading_level": None,
                        },
                        {
                            "text": "Roadmap",
                            "char_start": 58,
                            "char_end": 65,
                            "kind": "slide_heading",
                            "page_number": 2,
                            "slide_label": "Slide 2",
                            "section_title": "Roadmap",
                            "section_path": ["Roadmap"],
                            "heading_level": 1,
                        },
                        {
                            "text": "- Launch OCR sync\n- Add durable retries",
                            "char_start": 66,
                            "char_end": 106,
                            "kind": "bullet",
                            "page_number": 2,
                            "slide_label": "Slide 2",
                            "section_title": "Roadmap",
                            "section_path": ["Roadmap"],
                            "heading_level": None,
                        },
                    ]
                },
            )
        )

        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0].metadata["slide_label"], "Slide 1")
        self.assertEqual(chunks[1].metadata["slide_label"], "Slide 2")
        self.assertEqual(chunks[0].metadata["page_start"], 1)
        self.assertEqual(chunks[1].metadata["page_start"], 2)
        self.assertEqual(chunks[1].section_title, "Roadmap")
        self.assertEqual(chunks[1].metadata["segment_kinds"], ["slide_heading", "bullet"])
        self.assertEqual(chunks[1].metadata["locator_hint"], "Slide 2")

    def test_chunking_keeps_resume_header_skills_and_experience_separate(self) -> None:
        text = (
            "Jane Doe\njane@example.com | berlin\n\n"
            "TECHNICAL SKILLS\nPython, SQL, OCR\n\n"
            "WORK EXPERIENCE\nBuilt parsers for resumes.\n"
        )
        chunker = DocumentChunker(ChunkingConfig(max_chars=220, overlap_chars=0, min_chunk_chars=20))

        chunks = chunker.chunk(
            ChunkingRequest(
                document_id="doc-4",
                document_version_id="ver-4",
                document_title="Resume",
                text=text,
                metadata={
                    "structure_blocks": [
                        {
                            "text": "Jane Doe\njane@example.com | berlin",
                            "char_start": 0,
                            "char_end": 34,
                            "kind": "header",
                            "section_title": None,
                            "section_path": [],
                            "page_number": 1,
                            "slide_label": None,
                            "heading_level": None,
                        },
                        {
                            "text": "TECHNICAL SKILLS",
                            "char_start": 36,
                            "char_end": 52,
                            "kind": "resume_heading",
                            "section_title": "Technical Skills",
                            "section_path": ["Technical Skills"],
                            "page_number": 1,
                            "slide_label": None,
                            "heading_level": 1,
                        },
                        {
                            "text": "Python, SQL, OCR",
                            "char_start": 53,
                            "char_end": 69,
                            "kind": "skills_group",
                            "section_title": "Technical Skills",
                            "section_path": ["Technical Skills"],
                            "page_number": 1,
                            "slide_label": None,
                            "heading_level": None,
                        },
                        {
                            "text": "WORK EXPERIENCE",
                            "char_start": 71,
                            "char_end": 86,
                            "kind": "resume_heading",
                            "section_title": "Work Experience",
                            "section_path": ["Work Experience"],
                            "page_number": 1,
                            "slide_label": None,
                            "heading_level": 1,
                        },
                        {
                            "text": "Built parsers for resumes.",
                            "char_start": 87,
                            "char_end": 113,
                            "kind": "experience_entry",
                            "section_title": "Work Experience",
                            "section_path": ["Work Experience"],
                            "page_number": 1,
                            "slide_label": None,
                            "heading_level": None,
                        },
                    ]
                },
            )
        )

        self.assertEqual(len(chunks), 3)
        self.assertEqual(chunks[0].metadata["segment_kinds"], ["header"])
        self.assertEqual(chunks[1].section_title, "Technical Skills")
        self.assertEqual(chunks[1].metadata["segment_kinds"], ["resume_heading", "skills_group"])
        self.assertEqual(chunks[2].section_title, "Work Experience")
        self.assertEqual(chunks[2].metadata["segment_kinds"], ["resume_heading", "experience_entry"])

    def test_chunking_splits_slide_sections_and_preserves_timing_metadata(self) -> None:
        text = "Quarterly Planning\nAgenda\n- Pipeline metrics\n10:00 - OCR review"
        chunker = DocumentChunker(ChunkingConfig(max_chars=220, overlap_chars=0, min_chunk_chars=20))

        chunks = chunker.chunk(
            ChunkingRequest(
                document_id="doc-5",
                document_version_id="ver-5",
                document_title="Planning Deck",
                text=text,
                metadata={
                    "structure_blocks": [
                        {
                            "text": "Quarterly Planning",
                            "char_start": 0,
                            "char_end": 18,
                            "kind": "slide_heading",
                            "page_number": 1,
                            "slide_label": "Slide 1",
                            "section_title": "Quarterly Planning",
                            "section_path": ["Quarterly Planning"],
                            "heading_level": 1,
                        },
                        {
                            "text": "Agenda",
                            "char_start": 19,
                            "char_end": 25,
                            "kind": "slide_section_heading",
                            "page_number": 1,
                            "slide_label": "Slide 1",
                            "section_title": "Agenda",
                            "section_path": ["Quarterly Planning", "Agenda"],
                            "heading_level": 2,
                        },
                        {
                            "text": "- Pipeline metrics",
                            "char_start": 26,
                            "char_end": 44,
                            "kind": "bullet_group",
                            "page_number": 1,
                            "slide_label": "Slide 1",
                            "section_title": "Agenda",
                            "section_path": ["Quarterly Planning", "Agenda"],
                            "heading_level": None,
                        },
                        {
                            "text": "10:00 - OCR review",
                            "char_start": 45,
                            "char_end": 63,
                            "kind": "timing_group",
                            "page_number": 1,
                            "slide_label": "Slide 1",
                            "section_title": "Agenda",
                            "section_path": ["Quarterly Planning", "Agenda"],
                            "heading_level": None,
                        },
                    ]
                },
            )
        )

        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0].metadata["slide_label"], "Slide 1")
        self.assertEqual(chunks[0].metadata["segment_kinds"], ["slide_heading"])
        self.assertEqual(chunks[1].metadata["segment_kinds"], ["slide_section_heading", "bullet_group", "timing_group"])
        self.assertEqual(chunks[1].metadata["section_path"], ["Quarterly Planning", "Agenda"])
        self.assertEqual(chunks[1].metadata["locator_hint"], "Slide 1")

    def test_small_trailing_chunk_is_merged(self) -> None:
        text = (
            "First paragraph with enough text to stand alone for chunking purposes.\n\n"
            "Second paragraph also contains enough words to trigger a split in the chunker.\n\n"
            "Tiny tail."
        )
        chunker = DocumentChunker(ChunkingConfig(max_chars=90, overlap_chars=0, min_chunk_chars=20))

        chunks = chunker.chunk(
            ChunkingRequest(
                document_id="doc-3",
                document_version_id="ver-3",
                text=text,
            )
        )

        self.assertEqual(len(chunks), 2)
        self.assertIn("Tiny tail.", chunks[-1].text)


if __name__ == "__main__":
    unittest.main()
