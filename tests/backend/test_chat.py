import asyncio
import uuid
from types import SimpleNamespace

from app.services.answer_generation import GroundedGenerationRequest, GroundedGenerationResult
from app.services.chat_service import GroundedChatService
from app.services.document_models import SearchResult, SourceChunk


class RecordingAnswerGenerator:
    def __init__(self, response_text: str, used_evidence_indices: list[int] | None = None) -> None:
        self.response_text = response_text
        self.used_evidence_indices = used_evidence_indices
        self.requests: list[GroundedGenerationRequest] = []

    async def generate(self, request: GroundedGenerationRequest) -> GroundedGenerationResult:
        self.requests.append(request)
        return GroundedGenerationResult(
            content=self.response_text,
            used_evidence_indices=self.used_evidence_indices,
        )


class EmptyRetrievalService:
    def search(self, *, query: str, top_k: int = 10, workspace_id=None, source_ids=None):
        return []


class StaticRetrievalService:
    def __init__(self, results: list[SearchResult]) -> None:
        self._results = results

    def search(self, *, query: str, top_k: int = 10, workspace_id=None, source_ids=None):
        return self._results[:top_k]


def _search_result(chunk_id: str, title: str, text: str, score: float = 1.0) -> SearchResult:
    chunk = SourceChunk(
        chunk_id=chunk_id,
        document_id=f"doc-{chunk_id}",
        document_version_id=f"doc-{chunk_id}",
        chunk_index=0,
        text=text,
        document_title=title,
        metadata={},
    )
    return SearchResult(chunk=chunk, score=score, vector_score=score, keyword_score=score, rank=1)


def test_chat_endpoint_creates_session_and_grounded_reply(client):
    upload_response = client.post(
        "/api/v1/documents/upload",
        files={"file": ("policy.txt", b"PTO carryover policy allows forty hours of unused vacation.", "text/plain")},
    )
    assert upload_response.status_code == 202
    assert upload_response.json()["data"]["status"] == "completed"

    response = client.post(
        "/api/v1/chat",
        json={"message": "Summarize the policy."},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["data"]["session_id"]
    assert len(body["data"]["messages"]) == 2
    assert body["data"]["messages"][0]["role"] == "user"
    assert body["data"]["messages"][0]["content"] == "Summarize the policy."
    assert body["data"]["messages"][1]["role"] == "assistant"
    assert "PTO carryover policy allows forty hours of unused vacation." in body["data"]["messages"][1]["content"]
    assert "Based on the processed documents" not in body["data"]["messages"][1]["content"]
    assert "Supporting evidence:" not in body["data"]["messages"][1]["content"]
    assert "Sources:" not in body["data"]["messages"][1]["content"]
    assert body["data"]["messages"][1]["citations"]
    assert body["data"]["messages"][1]["citations"][0]["title"] == "policy.txt"

    session_id = body["data"]["session_id"]
    list_response = client.get("/api/v1/conversations")
    assert list_response.status_code == 200
    assert list_response.json()["data"][0]["id"] == session_id
    assert list_response.json()["data"][0]["title"] == "Summarize the policy."

    detail_response = client.get(f"/api/v1/conversations/{session_id}")
    assert detail_response.status_code == 200
    assert detail_response.json()["data"]["title"] == "Summarize the policy."


def test_conversation_history_persists_citations_and_refreshes_order(client):
    first_upload = client.post(
        "/api/v1/documents/upload",
        files={"file": ("policy-a.txt", b"PTO carryover policy allows forty hours.", "text/plain")},
    )
    second_upload = client.post(
        "/api/v1/documents/upload",
        files={"file": ("policy-b.txt", b"Managers may approve emergency carryover in writing.", "text/plain")},
    )
    assert first_upload.status_code == 202
    assert second_upload.status_code == 202

    older = client.post("/api/v1/conversations", json={}).json()["data"]["id"]
    newer = client.post("/api/v1/conversations", json={}).json()["data"]["id"]

    message_response = client.post(
        f"/api/v1/conversations/{older}/messages",
        json={"message": "What is the carryover policy?", "options": {"top_k": 2}},
    )
    assert message_response.status_code == 200
    payload = message_response.json()["data"]
    assert payload["citations"]

    list_response = client.get("/api/v1/conversations")
    assert list_response.status_code == 200
    assert list_response.json()["data"][0]["id"] == older
    assert list_response.json()["data"][1]["id"] == newer
    assert list_response.json()["data"][0]["title"] == "What is the carryover policy?"
    assert list_response.json()["data"][1]["title"] == "New conversation"

    history_response = client.get(f"/api/v1/conversations/{older}")
    assert history_response.status_code == 200
    history_payload = history_response.json()["data"]
    assert history_payload["title"] == "What is the carryover policy?"
    history = history_payload["messages"]
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[1]["role"] == "assistant"
    assert history[1]["citations"]
    assert history[1]["citations"][0]["title"] in {"policy-a.txt", "policy-b.txt"}


def test_existing_custom_conversation_title_is_preserved_after_first_message(client):
    conversation_id = client.post("/api/v1/conversations", json={}).json()["data"]["id"]

    first_message = "Keep the custom title intact."
    response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"message": first_message},
    )
    assert response.status_code == 200

    detail_response = client.get(f"/api/v1/conversations/{conversation_id}")
    assert detail_response.status_code == 200
    assert detail_response.json()["data"]["title"] == first_message


def test_chat_returns_not_found_for_unknown_session_id(client):
    response = client.post(
        "/api/v1/chat",
        json={"message": "Continue the missing conversation.", "session_id": str(uuid.uuid4())},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Conversation not found"


def test_conversation_message_rejects_mismatched_session_id(client):
    conversation_id = client.post("/api/v1/conversations", json={}).json()["data"]["id"]

    response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"message": "This should fail.", "session_id": str(uuid.uuid4())},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "session_id must match conversation_id"


def test_existing_custom_conversation_title_is_preserved_after_subsequent_messages(client):
    conversation_id = client.post("/api/v1/conversations", json={}).json()["data"]["id"]

    first_message = "Keep the custom title intact."
    response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"message": first_message},
    )
    assert response.status_code == 200

    second_message = "Second message should not replace a meaningful title."
    response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"message": second_message},
    )
    assert response.status_code == 200

    detail_response = client.get(f"/api/v1/conversations/{conversation_id}")
    assert detail_response.status_code == 200
    assert detail_response.json()["data"]["title"] == first_message


def test_chat_grounds_answer_across_multiple_completed_documents_with_stable_citations(client):
    upload_a = client.post(
        "/api/v1/documents/upload",
        files={"file": ("pto-policy.txt", b"PTO carryover policy allows forty hours of unused vacation for full-time employees.", "text/plain")},
    )
    upload_b = client.post(
        "/api/v1/documents/upload",
        files={"file": ("manager-exceptions.txt", b"Managers may approve emergency carryover exceptions when the request is documented.", "text/plain")},
    )
    assert upload_a.status_code == 202
    assert upload_b.status_code == 202

    response = client.post(
        "/api/v1/chat",
        json={"message": "What does the PTO carryover policy allow, and are exceptions possible?"},
    )

    assert response.status_code == 202
    body = response.json()["data"]
    assistant_message = body["messages"][1]
    assert assistant_message["role"] == "assistant"
    assert "forty hours of unused vacation" in assistant_message["content"]
    assert "emergency carryover exceptions" in assistant_message["content"]
    assert "Based on the processed documents" not in assistant_message["content"]
    assert len(assistant_message["citations"]) >= 2
    assert assistant_message["citations"][0]["chunk_id"]
    assert {citation["title"] for citation in assistant_message["citations"]}.issuperset(
        {"pto-policy.txt", "manager-exceptions.txt"}
    )


def test_chat_answers_duration_questions_directly_with_focused_citations(client):
    outline_upload = client.post(
        "/api/v1/documents/upload",
        files={
            "file": (
                "ReFT_Presentation_Outline.txt",
                (
                    b"REFT Academic Presentation Outline 30-Minute Talk + Discussion Appendix "
                    b"This document contains a complete strategic presentation outline for the paper."
                ),
                "text/plain",
            )
        },
    )
    paper_upload = client.post(
        "/api/v1/documents/upload",
        files={
            "file": (
                "2024.acl-long.410.txt",
                (
                    b"Proceedings of the 62nd Annual Meeting of the Association for Computational Linguistics. "
                    b"REFT: Reasoning with Reinforced Fine-Tuning."
                ),
                "text/plain",
            )
        },
    )
    assert outline_upload.status_code == 202
    assert paper_upload.status_code == 202

    response = client.post(
        "/api/v1/chat",
        json={"message": "How many minutes is the REFT presentation?"},
    )

    assert response.status_code == 202
    assistant_message = response.json()["data"]["messages"][1]
    assert assistant_message["content"] == "30 minutes."
    assert "Supporting evidence:" not in assistant_message["content"]
    assert "Sources:" not in assistant_message["content"]
    assert assistant_message["citations"]
    assert len(assistant_message["citations"]) == 1
    assert assistant_message["citations"][0]["title"] == "ReFT_Presentation_Outline.txt"


def test_chat_preserves_multi_document_citations_for_synthesis_answers(client):
    upload_a = client.post(
        "/api/v1/documents/upload",
        files={"file": ("pto-policy.txt", b"PTO carryover policy allows forty hours of unused vacation for full-time employees.", "text/plain")},
    )
    upload_b = client.post(
        "/api/v1/documents/upload",
        files={"file": ("manager-exceptions.txt", b"Managers may approve emergency carryover exceptions when the request is documented.", "text/plain")},
    )
    assert upload_a.status_code == 202
    assert upload_b.status_code == 202

    response = client.post(
        "/api/v1/chat",
        json={"message": "What does the PTO carryover policy allow, and are exceptions possible?"},
    )

    assert response.status_code == 202
    assistant_message = response.json()["data"]["messages"][1]
    assert "forty hours of unused vacation" in assistant_message["content"]
    assert "emergency carryover exceptions" in assistant_message["content"]
    assert {citation["title"] for citation in assistant_message["citations"]} == {
        "pto-policy.txt",
        "manager-exceptions.txt",
    }


def test_chat_answers_slide_specific_questions_from_one_source_with_narrowed_citations(client):
    outline_upload = client.post(
        "/api/v1/documents/upload",
        files={
            "file": (
                "ReFT_Presentation_Outline.txt",
                (
                    b"Slide 18: Experimental setup and baselines.\n"
                    b"Slide 19: Evaluation results and limitations for ReFT.\n"
                    b"Slide 20: Questions and discussion."
                ),
                "text/plain",
            )
        },
    )
    distractor_upload = client.post(
        "/api/v1/documents/upload",
        files={
            "file": (
                "reft-paper-notes.txt",
                b"ReFT is a fine-tuning method discussed in the paper, but this note does not describe slide 19.",
                "text/plain",
            )
        },
    )
    assert outline_upload.status_code == 202
    assert distractor_upload.status_code == 202

    response = client.post(
        "/api/v1/chat",
        json={"message": "What is slide 19 about in the REFT presentation?"},
    )

    assert response.status_code == 202
    assistant_message = response.json()["data"]["messages"][1]
    assert "Evaluation results and limitations for ReFT." in assistant_message["content"]
    assert "Supporting evidence:" not in assistant_message["content"]
    assert "Sources:" not in assistant_message["content"]
    assert len(assistant_message["citations"]) == 1
    assert assistant_message["citations"][0]["title"] == "ReFT_Presentation_Outline.txt"


def test_redundant_retrieval_candidates_do_not_leak_into_chat_citations(client):
    source_a = client.post(
        "/api/v1/documents/upload",
        files={
            "file": (
                "reft-outline-primary.txt",
                b"REFT presentation outline: 30 minutes total.",
                "text/plain",
            )
        },
    )
    source_b = client.post(
        "/api/v1/documents/upload",
        files={
            "file": (
                "reft-outline-duplicate.txt",
                b"REFT presentation outline: 30 minutes total.",
                "text/plain",
            )
        },
    )
    source_c = client.post(
        "/api/v1/documents/upload",
        files={
            "file": (
                "reft-context.txt",
                b"REFT is a representation fine-tuning approach used in ACL experiments.",
                "text/plain",
            )
        },
    )
    assert source_a.status_code == 202
    assert source_b.status_code == 202
    assert source_c.status_code == 202

    response = client.post(
        "/api/v1/chat",
        json={"message": "How many minutes is the REFT presentation?"},
    )

    assert response.status_code == 202
    assistant_message = response.json()["data"]["messages"][1]
    assert assistant_message["content"] == "30 minutes."
    assert len(assistant_message["citations"]) == 1
    assert assistant_message["citations"][0]["title"] in {
        "reft-outline-primary.txt",
        "reft-outline-duplicate.txt",
    }


def test_grounded_chat_uses_model_generation_with_selected_evidence_only():
    generator = RecordingAnswerGenerator("Model-backed grounded answer.")
    retrieval_service = StaticRetrievalService(
        [
            _search_result("chunk-1", "outline.txt", "REFT presentation outline: 30 minutes total.", score=1.0),
            _search_result("chunk-2", "notes.txt", "General REFT background without the answer.", score=0.8),
        ]
    )
    service = GroundedChatService(retrieval_service, answer_generator=generator)

    reply = asyncio.run(
        service.generate_reply(
            session=SimpleNamespace(workspace_id=None),
            user_message=SimpleNamespace(content="How many minutes is the REFT presentation?"),
        )
    )

    assert reply.content == "Model-backed grounded answer."
    assert len(reply.citations) == 1
    assert reply.citations[0].title == "outline.txt"
    assert len(generator.requests) == 1
    assert len(generator.requests[0].evidence) == 1
    assert generator.requests[0].evidence[0].title == "outline.txt"


def test_grounded_chat_fallback_when_no_evidence_found():
    service = GroundedChatService(EmptyRetrievalService())

    reply = asyncio.run(
        service.generate_reply(
            session=SimpleNamespace(workspace_id=None),
            user_message=SimpleNamespace(content="What is the policy?"),
        )
    )

    assert reply.content == "I could not find a grounded answer in the processed documents for that question."
    assert reply.citations == []


def test_cv_skills_question_extracts_skills_without_dumping_header():
    cv_text = """Nijat Hasanov
Baku, Azerbaijan
Email: nijat@example.com

Professional Summary
Backend engineer focused on data platforms.

Technical Skills
Python, FastAPI, PostgreSQL, Docker, Redis, SQLAlchemy, REST APIs

Experience
Built document ingestion pipelines and retrieval services.
"""
    retrieval_service = StaticRetrievalService(
        [
            _search_result("cv", "Nijat_CV.pdf", cv_text, score=1.0),
            _search_result("other", "team-notes.txt", "Nijat joined the backend team in 2024.", score=0.4),
        ]
    )
    service = GroundedChatService(retrieval_service)

    reply = asyncio.run(
        service.generate_reply(
            session=SimpleNamespace(workspace_id=None),
            user_message=SimpleNamespace(content="Review the Nijat CV and tell me his skills"),
        )
    )

    assert reply.content == "Python, FastAPI, PostgreSQL, Docker, Redis, SQLAlchemy, REST APIs."
    assert not reply.content.startswith("Nijat Hasanov")
    assert not reply.content.endswith("...")
    assert [citation.title for citation in reply.citations] == ["Nijat_CV.pdf"]


def test_chat_reranker_selects_cv_skills_chunk_over_noisy_header_candidate():
    header = _search_result(
        "header",
        "Nijat_CV.pdf",
        "Nijat Hasanov\nBaku, Azerbaijan\nEmail: nijat@example.com\nLinkedIn: linkedin.example/nijat",
        score=2.0,
    )
    skills = _search_result(
        "skills",
        "Nijat_CV.pdf",
        "Technical Skills\nPython, FastAPI, PostgreSQL, Docker, Redis, SQLAlchemy, REST APIs",
        score=0.3,
    )
    service = GroundedChatService(StaticRetrievalService([header, skills]))

    reply = asyncio.run(
        service.generate_reply(
            session=SimpleNamespace(workspace_id=None),
            user_message=SimpleNamespace(content="Review the Nijat CV and tell me his skills"),
        )
    )

    assert reply.content == "Python, FastAPI, PostgreSQL, Docker, Redis, SQLAlchemy, REST APIs."
    assert [citation.chunk_id for citation in reply.citations] == ["skills"]


def test_chat_reranker_selects_slide_chunk_over_related_paper_candidate():
    paper = _search_result(
        "paper",
        "reft-paper-notes.txt",
        "REFT is a fine-tuning method discussed in the paper, but this note does not describe slide 19.",
        score=2.0,
    )
    slide = _search_result(
        "slide",
        "ReFT_Presentation_Outline.txt",
        "Slide 19: Evaluation results and limitations for ReFT.",
        score=0.2,
    )
    service = GroundedChatService(StaticRetrievalService([paper, slide]))

    reply = asyncio.run(
        service.generate_reply(
            session=SimpleNamespace(workspace_id=None),
            user_message=SimpleNamespace(content="What is slide 19 about in the REFT presentation?"),
        )
    )

    assert "Evaluation results and limitations for ReFT." in reply.content
    assert [citation.title for citation in reply.citations] == ["ReFT_Presentation_Outline.txt"]


def test_document_analysis_generation_receives_expanded_context():
    cv_text = """Nijat Hasanov
Baku, Azerbaijan

Technical Skills
Python, FastAPI, PostgreSQL, Docker, Redis, SQLAlchemy, REST APIs

Experience
Built document ingestion pipelines and retrieval services.
"""
    generator = RecordingAnswerGenerator("Skills: Python, FastAPI, PostgreSQL.")
    service = GroundedChatService(
        StaticRetrievalService([_search_result("cv", "Nijat_CV.pdf", cv_text, score=1.0)]),
        answer_generator=generator,
    )

    reply = asyncio.run(
        service.generate_reply(
            session=SimpleNamespace(workspace_id=None),
            user_message=SimpleNamespace(content="Review the Nijat CV and tell me his skills"),
        )
    )

    assert reply.content == "Skills: Python, FastAPI, PostgreSQL."
    assert len(generator.requests) == 1
    assert "Technical Skills" in generator.requests[0].evidence[0].content
    assert "REST APIs" in generator.requests[0].evidence[0].content
    assert [citation.title for citation in reply.citations] == ["Nijat_CV.pdf"]


def test_final_answer_strips_artificial_ellipsis_from_model_output():
    generator = RecordingAnswerGenerator("Skills: Python, FastAPI, PostgreSQL...")
    service = GroundedChatService(
        StaticRetrievalService(
            [
                _search_result(
                    "cv",
                    "Nijat_CV.pdf",
                    "Technical Skills\nPython, FastAPI, PostgreSQL",
                    score=1.0,
                )
            ]
        ),
        answer_generator=generator,
    )

    reply = asyncio.run(
        service.generate_reply(
            session=SimpleNamespace(workspace_id=None),
            user_message=SimpleNamespace(content="Review the Nijat CV and tell me his skills"),
        )
    )

    assert reply.content == "Skills: Python, FastAPI, PostgreSQL."
    assert not reply.content.endswith("...")


def test_direct_factual_answers_stay_short_and_precise():
    service = GroundedChatService(
        StaticRetrievalService(
            [
                _search_result("policy", "vacation-policy.txt", "Vacation carryover is capped at 40 hours.", score=1.0),
                _search_result("faq", "faq.txt", "Carryover rules are reviewed annually.", score=0.6),
            ]
        )
    )

    reply = asyncio.run(
        service.generate_reply(
            session=SimpleNamespace(workspace_id=None),
            user_message=SimpleNamespace(content="How many hours can employees carry over?"),
        )
    )

    assert reply.content == "40 hours."
    assert [citation.title for citation in reply.citations] == ["vacation-policy.txt"]


def test_multi_document_synthesis_covers_each_required_fact_without_boilerplate():
    service = GroundedChatService(
        StaticRetrievalService(
            [
                _search_result(
                    "carryover",
                    "vacation-policy.txt",
                    "Employees may carry over up to 40 hours of unused vacation into the next quarter.",
                    score=1.0,
                ),
                _search_result(
                    "approval",
                    "travel-approval.txt",
                    "International travel requires director approval before any booking is confirmed.",
                    score=0.9,
                ),
            ]
        )
    )

    reply = asyncio.run(
        service.generate_reply(
            session=SimpleNamespace(workspace_id=None),
            user_message=SimpleNamespace(
                content="What vacation carryover is allowed, and what approval is needed for international travel?"
            ),
        )
    )

    assert "40 hours of unused vacation" in reply.content
    assert "director approval" in reply.content
    assert "Based on the processed documents" not in reply.content
    assert {citation.title for citation in reply.citations} == {"vacation-policy.txt", "travel-approval.txt"}


def test_broad_summary_answers_remain_concise():
    strategy_text = (
        "The customer support plan introduces weekend coverage, an escalation rotation, and a monthly quality review. "
        "It also adds response-time targets and a shared knowledge base for repeat issues."
    )
    service = GroundedChatService(StaticRetrievalService([_search_result("strategy", "support-plan.txt", strategy_text, score=1.0)]))

    reply = asyncio.run(
        service.generate_reply(
            session=SimpleNamespace(workspace_id=None),
            user_message=SimpleNamespace(content="Summarize the support plan."),
        )
    )

    assert len(reply.content) < 260
    assert reply.content.count(".") <= 3
    assert "Based on the processed documents" not in reply.content
    assert "Supporting evidence:" not in reply.content


def test_synthesis_answers_are_not_overly_short_when_multiple_facts_are_needed():
    service = GroundedChatService(
        StaticRetrievalService(
            [
                _search_result("remote", "remote-policy.txt", "Remote employees may work abroad for up to 30 days per year.", score=1.0),
                _search_result("security", "security-policy.txt", "Employees working abroad must use company-managed devices and VPN access.", score=0.9),
            ]
        )
    )

    reply = asyncio.run(
        service.generate_reply(
            session=SimpleNamespace(workspace_id=None),
            user_message=SimpleNamespace(content="What does the remote work policy allow, and what security requirements apply?"),
        )
    )

    assert "30 days per year" in reply.content
    assert "company-managed devices" in reply.content
    assert "VPN access" in reply.content
    assert len(reply.citations) == 2


def test_model_backed_answers_only_return_citations_for_used_evidence():
    generator = RecordingAnswerGenerator("40 hours.", used_evidence_indices=[0])
    service = GroundedChatService(
        StaticRetrievalService(
            [
                _search_result("policy", "vacation-policy.txt", "Vacation carryover is capped at 40 hours.", score=1.0),
                _search_result("background", "background.txt", "Carryover was discussed in the 2025 planning notes.", score=0.7),
            ]
        ),
        answer_generator=generator,
    )

    reply = asyncio.run(
        service.generate_reply(
            session=SimpleNamespace(workspace_id=None),
            user_message=SimpleNamespace(content="How many hours can employees carry over?"),
        )
    )

    assert reply.content == "40 hours."
    assert [citation.title for citation in reply.citations] == ["vacation-policy.txt"]
