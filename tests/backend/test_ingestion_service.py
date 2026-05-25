from datetime import datetime, timedelta, timezone
import uuid

from sqlalchemy import select

from app.db.session import get_session_factory
from app.models.document import Document, DocumentChunk
from app.models.source import SourceSyncJob
from app.services.ingestion import (
    DOCUMENT_STATUS_COMPLETED,
    DOCUMENT_STATUS_FAILED,
    DOCUMENT_STATUS_PROCESSING,
    LocalDocumentIngestionService,
)


def test_duplicate_processing_is_skipped_when_document_is_already_active(client):
    upload_response = client.post(
        "/api/v1/documents/upload",
        files={"file": ("policy.txt", b"PTO carryover policy allows forty hours.", "text/plain")},
    )
    document_id = upload_response.json()["data"]["document_id"]
    service = LocalDocumentIngestionService()

    with get_session_factory()() as db:
        document = db.get(Document, uuid.UUID(document_id))
        assert document is not None
        existing_chunk_ids = [str(chunk.id) for chunk in document.chunks]
        document.status = DOCUMENT_STATUS_PROCESSING
        document.updated_at = datetime.now(timezone.utc)
        db.commit()

    result = service.process_document(document_id, trigger="duplicate-check")

    assert result.outcome == "skipped_active"

    with get_session_factory()() as db:
        document = db.get(Document, uuid.UUID(document_id))
        assert document is not None
        assert document.status == DOCUMENT_STATUS_PROCESSING
        assert document.processing_attempts == 1
        chunks = db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == document.id)).all()
        assert [str(chunk.id) for chunk in chunks] == existing_chunk_ids


def test_failed_processing_can_retry_after_stale_run_and_clears_error_on_success(client):
    upload_response = client.post(
        "/api/v1/documents/upload",
        files={"file": ("retention.txt", b"Retention periods are documented here.", "text/plain")},
    )
    document_id = upload_response.json()["data"]["document_id"]
    service = LocalDocumentIngestionService()

    with get_session_factory()() as db:
        document = db.get(Document, uuid.UUID(document_id))
        assert document is not None
        stored_path = service._storage.resolve_path(document.storage_path)
        original_content = stored_path.read_text(encoding="utf-8")
        stored_path.unlink()
        document.status = DOCUMENT_STATUS_PROCESSING
        document.updated_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db.commit()

    failed_result = service.process_document(document_id, trigger="retry")

    assert failed_result.outcome == "failed"
    assert "FileNotFoundError: Stored upload is missing" in (failed_result.error_message or "")

    with get_session_factory()() as db:
        document = db.get(Document, uuid.UUID(document_id))
        assert document is not None
        assert document.status == DOCUMENT_STATUS_FAILED
        assert document.processing_attempts == 2
        assert "FileNotFoundError: Stored upload is missing" in (document.processing_error or "")
        assert document.metadata_json["processing"]["stale_recovery"] is True

    stored_path.write_text(original_content, encoding="utf-8")
    success_result = service.process_document(document_id, trigger="retry")

    assert success_result.outcome == "completed"

    with get_session_factory()() as db:
        document = db.get(Document, uuid.UUID(document_id))
        assert document is not None
        assert document.status == DOCUMENT_STATUS_COMPLETED
        assert document.processing_attempts == 3
        assert document.processing_error is None
        assert document.processed_at is not None
        assert document.metadata_json["processing"]["error_message"] is None


def test_source_sync_reruns_replace_chunks_without_duplication(client):
    source_response = client.post(
        "/api/v1/sources",
        json={"name": "Engineering Handbook", "type": "upload", "classification": "internal"},
    )
    source_id = source_response.json()["data"]["id"]

    original_text = "\n\n".join(
        [
            "Section A " + ("alpha " * 90),
            "Section B " + ("beta " * 90),
            "Section C " + ("gamma " * 90),
        ]
    )
    upload_response = client.post(
        f"/api/v1/sources/{source_id}/upload",
        files={"file": ("handbook.txt", original_text.encode('utf-8'), "text/plain")},
    )
    document_id = upload_response.json()["data"]["document_id"]
    service = LocalDocumentIngestionService()

    with get_session_factory()() as db:
        document = db.get(Document, uuid.UUID(document_id))
        assert document is not None
        initial_chunks = db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == document.id)).all()
        initial_chunk_ids = {str(chunk.id) for chunk in initial_chunks}
        assert len(initial_chunks) >= 2
        stored_path = service._storage.resolve_path(document.storage_path)
        stored_path.write_text("Updated policy text after sync.", encoding="utf-8")

    first_sync = client.post(f"/api/v1/sources/{source_id}/sync")
    assert first_sync.status_code == 202
    first_job_id = first_sync.json()["data"]["job_id"]

    with get_session_factory()() as db:
        job = db.get(SourceSyncJob, uuid.UUID(first_job_id))
        document = db.get(Document, uuid.UUID(document_id))
        assert job is not None
        assert document is not None
        assert job.status == "completed"
        assert document.processing_attempts == 2
        replacement_chunks = db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == document.id)).all()
        assert len(replacement_chunks) == 1
        assert replacement_chunks[0].content == "Updated policy text after sync."
        assert {str(chunk.id) for chunk in replacement_chunks}.isdisjoint(initial_chunk_ids)

    second_sync = client.post(f"/api/v1/sources/{source_id}/sync")
    assert second_sync.status_code == 202
    second_job_id = second_sync.json()["data"]["job_id"]

    with get_session_factory()() as db:
        job = db.get(SourceSyncJob, uuid.UUID(second_job_id))
        document = db.get(Document, uuid.UUID(document_id))
        assert job is not None
        assert document is not None
        assert job.status == "completed"
        assert document.processing_attempts == 3
        final_chunks = db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == document.id)).all()
        assert len(final_chunks) == 1
        assert final_chunks[0].content == "Updated policy text after sync."


def test_reprocess_updates_richer_chunk_metadata_for_structured_markdown(client):
    upload_response = client.post(
        "/api/v1/documents/upload",
        files={
            "file": (
                "outline.md",
                (
                    b"# Retention Policy\n\n"
                    b"## Timelines\n\n"
                    b"- Email logs are retained for 30 days\n"
                    b"- Audit snapshots are retained for 1 year\n"
                ),
                "text/markdown",
            )
        },
    )
    document_id = upload_response.json()["data"]["document_id"]
    service = LocalDocumentIngestionService()

    with get_session_factory()() as db:
        document = db.get(Document, uuid.UUID(document_id))
        assert document is not None
        assert document.metadata_json["structure_summary"]["section_titles"] == ["Retention Policy", "Timelines"]
        chunks = db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == document.id)).all()
        assert len(chunks) == 1
        assert chunks[0].metadata_json["section_path"] == ["Retention Policy", "Timelines"]
        assert chunks[0].metadata_json["segment_kinds"] == ["heading", "bullet"]
        stored_path = service._storage.resolve_path(document.storage_path)
        stored_path.write_text(
            "# Retention Policy\n\n## Exceptions\n\n- Legal hold data is retained until release\n",
            encoding="utf-8",
        )

    service.process_document(document_id, trigger="reprocess")

    with get_session_factory()() as db:
        document = db.get(Document, uuid.UUID(document_id))
        assert document is not None
        assert document.status == DOCUMENT_STATUS_COMPLETED
        assert document.processing_attempts == 2
        assert document.metadata_json["structure_summary"]["section_titles"] == ["Retention Policy", "Exceptions"]
        chunks = db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == document.id)).all()
        assert len(chunks) == 1
        assert chunks[0].metadata_json["section_title"] == "Exceptions"
        assert chunks[0].metadata_json["section_path"] == ["Retention Policy", "Exceptions"]
        assert "Timelines" not in chunks[0].content
