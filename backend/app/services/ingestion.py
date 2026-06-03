from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
import uuid

from fastapi import BackgroundTasks, UploadFile
from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.db.session import get_session_factory
from app.ingestion.chunking import ChunkingRequest, DocumentChunker
from app.models.document import Document, DocumentChunk
from app.models.source import Source, SourceSyncJob
from app.services.document_models import SourceChunk
from app.services.interfaces import DocumentIngestionService
from app.services.retrieval_service import PersistedChunkEmbeddingIndexer
from app.services.storage import LocalDocumentStorage
from app.services.text_extraction import DocumentTextExtractor

logger = logging.getLogger(__name__)

DOCUMENT_STATUS_QUEUED = "queued"
DOCUMENT_STATUS_PROCESSING = "processing"
DOCUMENT_STATUS_COMPLETED = "completed"
DOCUMENT_STATUS_FAILED = "failed"

JOB_STATUS_QUEUED = "queued"
JOB_STATUS_PROCESSING = "processing"
JOB_STATUS_COMPLETED = "completed"
JOB_STATUS_FAILED = "failed"

PROCESSING_OUTCOME_COMPLETED = "completed"
PROCESSING_OUTCOME_FAILED = "failed"
PROCESSING_OUTCOME_SKIPPED_ACTIVE = "skipped_active"
PROCESSING_OUTCOME_MISSING = "missing"


@dataclass(slots=True)
class DocumentProcessingClaim:
    document_id: str
    run_id: str
    trigger: str
    stale_recovery: bool


@dataclass(slots=True)
class DocumentProcessingResult:
    outcome: str
    document_id: str
    run_id: str | None = None
    error_message: str | None = None


class LocalDocumentIngestionService(DocumentIngestionService):
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        session_factory: sessionmaker[Session] | None = None,
        extractor: DocumentTextExtractor | None = None,
        chunker: DocumentChunker | None = None,
        storage: LocalDocumentStorage | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._session_factory = session_factory or get_session_factory()
        self._extractor = extractor or DocumentTextExtractor()
        self._chunker = chunker or DocumentChunker()
        self._storage = storage or LocalDocumentStorage(self._settings)

    async def create_document_upload(
        self,
        db: Session,
        *,
        upload: UploadFile,
        source: Source | None = None,
        workspace_id: uuid.UUID | None = None,
    ) -> Document:
        file_name = upload.filename or "untitled"
        content = await upload.read()
        document = Document(
            source_id=source.id if source else None,
            workspace_id=source.workspace_id if source else workspace_id,
            title=file_name if file_name else (source.name if source else "untitled"),
            filename=file_name,
            mime_type=upload.content_type,
            status=DOCUMENT_STATUS_QUEUED,
        )
        db.add(document)
        db.flush()

        stored_file = self._storage.save_upload(
            document_id=str(document.id),
            filename=file_name,
            content=content,
        )
        document.storage_backend = stored_file.backend
        document.storage_path = stored_file.relative_path
        document.file_size_bytes = stored_file.size_bytes
        document.checksum_sha256 = stored_file.checksum_sha256
        document.metadata_json = {
            **(document.metadata_json or {}),
            "filename": file_name,
            "content_type": upload.content_type,
            "storage": {
                "backend": stored_file.backend,
                "path": stored_file.relative_path,
                "size_bytes": stored_file.size_bytes,
                "checksum_sha256": stored_file.checksum_sha256,
            },
            "document_type": Path(file_name).suffix.lower().lstrip(".") or None,
            "processing": {
                "status": DOCUMENT_STATUS_QUEUED,
                "last_trigger": "upload",
                "active": False,
                "current_run_id": None,
                "error_message": None,
            },
        }
        db.commit()
        db.refresh(document)
        logger.info("document uploaded", extra={"document_id": str(document.id), "status": document.status})
        return document

    def schedule_document_processing(
        self,
        *,
        document_id: str,
        background_tasks: BackgroundTasks | None = None,
    ) -> None:
        if self._settings.ingestion_execution_mode == "background" and background_tasks is not None:
            background_tasks.add_task(self.process_document, document_id)
            return
        self.process_document(document_id)

    def create_source_sync_job(self, db: Session, *, source: Source) -> SourceSyncJob:
        job = SourceSyncJob(source_id=source.id, job_type="sync", status=JOB_STATUS_QUEUED)
        db.add(job)
        db.commit()
        db.refresh(job)
        return job

    def schedule_source_sync(
        self,
        *,
        job_id: str,
        background_tasks: BackgroundTasks | None = None,
    ) -> None:
        if self._settings.ingestion_execution_mode == "background" and background_tasks is not None:
            background_tasks.add_task(self.process_source_sync_job, job_id)
            return
        self.process_source_sync_job(job_id)

    def process_document(self, document_id: str, *, trigger: str = "manual") -> DocumentProcessingResult:
        claim = self._claim_document_for_processing(document_id, trigger=trigger)
        if claim is None:
            with self._session_factory() as db:
                document = db.get(Document, uuid.UUID(document_id))
                if document is None:
                    logger.warning("document missing during ingestion", extra={"document_id": document_id})
                    return DocumentProcessingResult(
                        outcome=PROCESSING_OUTCOME_MISSING,
                        document_id=document_id,
                        error_message="Document not found",
                    )

                logger.info(
                    "document processing skipped because another run is active",
                    extra={"document_id": document_id, "status": document.status},
                )
                return DocumentProcessingResult(
                    outcome=PROCESSING_OUTCOME_SKIPPED_ACTIVE,
                    document_id=document_id,
                )

        try:
            with self._session_factory() as db:
                document = db.get(Document, uuid.UUID(document_id))
                if document is None:
                    raise FileNotFoundError("Document not found")

                logger.info(
                    "document processing started",
                    extra={"document_id": document_id, "status": document.status, "run_id": claim.run_id},
                )

                if not document.storage_path:
                    raise FileNotFoundError("Document storage path is missing")

                storage_path = self._storage.resolve_path(document.storage_path)
                if not storage_path.exists():
                    raise FileNotFoundError(f"Stored upload is missing: {document.storage_path}")

                extraction = self._extractor.extract_file(storage_path)
                if not extraction.text.strip():
                    raise ValueError("Document extraction produced no text")

                chunks = self._chunker.chunk(
                    ChunkingRequest(
                        document_id=str(document.id),
                        document_version_id=str(document.id),
                        text=extraction.text,
                        metadata={
                            **(document.metadata_json or {}),
                            **extraction.metadata,
                        },
                        source_id=str(document.source_id) if document.source_id else None,
                        workspace_id=str(document.workspace_id) if document.workspace_id else None,
                        document_title=document.title,
                    )
                )
                if not chunks:
                    raise ValueError("Document chunking produced no chunks")

                PersistedChunkEmbeddingIndexer(db).delete_document_version(str(document.id))
                db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document.id))
                db.flush()
                persisted_chunks: list[SourceChunk] = []
                for chunk in chunks:
                    chunk_record = DocumentChunk(
                        document_id=document.id,
                        chunk_index=chunk.chunk_index,
                        content=chunk.text,
                        token_count=chunk.token_count,
                        metadata_json={
                            **chunk.metadata,
                            "section_title": chunk.section_title,
                            "page_number": chunk.page_number,
                            "char_start": chunk.char_start,
                            "char_end": chunk.char_end,
                        },
                    )
                    db.add(chunk_record)
                    db.flush()
                    persisted_chunks.append(
                        SourceChunk(
                            chunk_id=str(chunk_record.id),
                            document_id=str(document.id),
                            document_version_id=str(document.id),
                            chunk_index=chunk.chunk_index,
                            text=chunk.text,
                            metadata={
                                **chunk.metadata,
                                "section_title": chunk.section_title,
                                "page_number": chunk.page_number,
                                "char_start": chunk.char_start,
                                "char_end": chunk.char_end,
                            },
                            source_id=str(document.source_id) if document.source_id else None,
                            workspace_id=str(document.workspace_id) if document.workspace_id else None,
                            document_title=document.title,
                            section_title=chunk.section_title,
                            page_number=chunk.page_number,
                            token_count=chunk.token_count,
                            char_start=chunk.char_start,
                            char_end=chunk.char_end,
                        )
                    )

                PersistedChunkEmbeddingIndexer(db).index_chunks(persisted_chunks)

                document.mime_type = extraction.content_type or document.mime_type
                document.processing_error = None
                document.last_error_at = None
                document.processed_at = datetime.now(timezone.utc)
                document.status = DOCUMENT_STATUS_COMPLETED
                document.metadata_json = self._with_processing_metadata(
                    document.metadata_json,
                    status=DOCUMENT_STATUS_COMPLETED,
                    trigger=claim.trigger,
                    run_id=claim.run_id,
                    started_at=self._get_processing_started_at(document.metadata_json),
                    completed_at=document.processed_at,
                    stale_recovery=claim.stale_recovery,
                    extra={
                        "content_type": extraction.content_type,
                        "chunk_count": len(chunks),
                        "extraction": extraction.metadata,
                        "structure_summary": {
                            "section_titles": extraction.metadata.get("section_titles", []),
                            "page_count": extraction.metadata.get("page_count", len(extraction.metadata.get("pages", []))),
                            "presentation_like": bool(extraction.metadata.get("is_presentation_like")),
                        },
                        "last_processed_at": document.processed_at.isoformat(),
                    },
                )
                db.commit()
                logger.info(
                    "document processing completed",
                    extra={"document_id": document_id, "chunk_count": len(chunks), "run_id": claim.run_id},
                )
                return DocumentProcessingResult(
                    outcome=PROCESSING_OUTCOME_COMPLETED,
                    document_id=document_id,
                    run_id=claim.run_id,
                )
        except Exception as exc:
            self._mark_document_failed(document_id, exc, claim=claim)
            return DocumentProcessingResult(
                outcome=PROCESSING_OUTCOME_FAILED,
                document_id=document_id,
                run_id=claim.run_id,
                error_message=self._format_exception(exc),
            )

    def process_source_sync_job(self, job_id: str) -> None:
        job_uuid = uuid.UUID(job_id)
        try:
            with self._session_factory() as db:
                job = db.get(SourceSyncJob, job_uuid)
                if job is None:
                    logger.warning("source sync job missing", extra={"job_id": job_id})
                    return
                source = db.get(Source, job.source_id)
                if source is None:
                    raise ValueError("Source not found for sync job")

                job.status = JOB_STATUS_PROCESSING
                job.error_message = None
                job.started_at = datetime.now(timezone.utc)
                document_ids = [
                    str(document_id)
                    for document_id in db.scalars(
                        select(Document.id).where(Document.source_id == source.id).order_by(Document.updated_at.desc())
                    ).all()
                ]
                job.documents_total = len(document_ids)
                job.documents_processed = 0
                job.documents_failed = 0
                db.commit()

            failures = 0
            processed = 0
            skipped_active = 0
            for document_id in document_ids:
                result = self.process_document(document_id, trigger="source_sync")
                processed += 1
                if result.outcome == PROCESSING_OUTCOME_FAILED:
                    failures += 1
                elif result.outcome == PROCESSING_OUTCOME_SKIPPED_ACTIVE:
                    skipped_active += 1

                with self._session_factory() as db:
                    job = db.get(SourceSyncJob, job_uuid)
                    if job is None:
                        return
                    job.documents_processed = processed
                    job.documents_failed = failures
                    db.commit()

            with self._session_factory() as db:
                job = db.get(SourceSyncJob, job_uuid)
                if job is None:
                    return
                job.finished_at = datetime.now(timezone.utc)
                job.status = JOB_STATUS_FAILED if failures else JOB_STATUS_COMPLETED
                if failures:
                    job.error_message = f"{failures} document(s) failed during sync"
                elif skipped_active:
                    job.error_message = f"{skipped_active} document(s) skipped because processing was already in progress"
                db.commit()
        except Exception as exc:
            with self._session_factory() as db:
                job = db.get(SourceSyncJob, job_uuid)
                if job is None:
                    return
                job.status = JOB_STATUS_FAILED
                job.error_message = self._format_exception(exc)
                job.finished_at = datetime.now(timezone.utc)
                if job.started_at is None:
                    job.started_at = job.finished_at
                db.commit()
            logger.exception("source sync failed", extra={"job_id": job_id})

    def _claim_document_for_processing(self, document_id: str, *, trigger: str) -> DocumentProcessingClaim | None:
        document_uuid = uuid.UUID(document_id)
        now = datetime.now(timezone.utc)
        stale_before = now - timedelta(seconds=self._settings.ingestion_processing_timeout_seconds)
        run_id = str(uuid.uuid4())

        with self._session_factory() as db:
            existing = db.get(Document, document_uuid)
            if existing is None:
                return None

            stale_recovery = existing.status == DOCUMENT_STATUS_PROCESSING and self._is_processing_stale(existing, now=now)
            claimed = db.execute(
                update(Document)
                .where(Document.id == document_uuid)
                .where(
                    or_(
                        Document.status != DOCUMENT_STATUS_PROCESSING,
                        Document.updated_at < stale_before,
                    )
                )
                .values(
                    status=DOCUMENT_STATUS_PROCESSING,
                    processing_error=None,
                    last_error_at=None,
                    processed_at=None,
                    processing_attempts=Document.processing_attempts + 1,
                    updated_at=now,
                )
                .execution_options(synchronize_session=False)
            )
            if claimed.rowcount != 1:
                db.rollback()
                return None

            document = db.get(Document, document_uuid)
            if document is None:
                db.rollback()
                return None

            document.metadata_json = self._with_processing_metadata(
                document.metadata_json,
                status=DOCUMENT_STATUS_PROCESSING,
                trigger=trigger,
                run_id=run_id,
                started_at=now,
                stale_recovery=stale_recovery,
            )
            db.commit()
            return DocumentProcessingClaim(
                document_id=document_id,
                run_id=run_id,
                trigger=trigger,
                stale_recovery=stale_recovery,
            )

    def _mark_document_failed(
        self,
        document_id: str,
        exc: Exception,
        *,
        claim: DocumentProcessingClaim | None,
    ) -> None:
        failure_time = datetime.now(timezone.utc)
        error_message = self._format_exception(exc)
        with self._session_factory() as db:
            document = db.get(Document, uuid.UUID(document_id))
            if document is None:
                return
            document.status = DOCUMENT_STATUS_FAILED
            document.processing_error = error_message
            document.last_error_at = failure_time
            document.processed_at = None
            document.metadata_json = self._with_processing_metadata(
                document.metadata_json,
                status=DOCUMENT_STATUS_FAILED,
                trigger=claim.trigger if claim else "unknown",
                run_id=claim.run_id if claim else None,
                started_at=self._get_processing_started_at(document.metadata_json),
                failed_at=failure_time,
                stale_recovery=claim.stale_recovery if claim else False,
                error_message=error_message,
                extra={
                    "last_failure": {
                        "message": error_message,
                        "at": failure_time.isoformat(),
                    }
                },
            )
            db.commit()
        logger.exception("document processing failed", extra={"document_id": document_id})

    def _is_processing_stale(self, document: Document, *, now: datetime) -> bool:
        if document.status != DOCUMENT_STATUS_PROCESSING:
            return False
        if document.updated_at is None:
            return True
        updated_at = self._coerce_utc(document.updated_at)
        return updated_at <= now - timedelta(seconds=self._settings.ingestion_processing_timeout_seconds)

    def _with_processing_metadata(
        self,
        metadata: dict | None,
        *,
        status: str,
        trigger: str,
        run_id: str | None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        failed_at: datetime | None = None,
        stale_recovery: bool = False,
        error_message: str | None = None,
        extra: dict | None = None,
    ) -> dict:
        payload = dict(metadata or {})
        processing = dict(payload.get("processing") or {})
        processing.update(
            {
                "status": status,
                "last_trigger": trigger,
                "current_run_id": run_id,
                "last_started_at": started_at.isoformat() if started_at else processing.get("last_started_at"),
                "last_completed_at": completed_at.isoformat() if completed_at else processing.get("last_completed_at"),
                "last_failed_at": failed_at.isoformat() if failed_at else processing.get("last_failed_at"),
                "stale_recovery": stale_recovery,
            }
        )
        if status == DOCUMENT_STATUS_COMPLETED:
            processing["last_successful_run_id"] = run_id
            processing["active"] = False
            processing["error_message"] = None
        elif status == DOCUMENT_STATUS_FAILED:
            processing["active"] = False
            processing["error_message"] = error_message
        else:
            processing["active"] = True
            processing["error_message"] = None
        payload["processing"] = processing
        if extra:
            payload.update(extra)
        return payload

    def _get_processing_started_at(self, metadata: dict | None) -> datetime | None:
        processing = (metadata or {}).get("processing")
        if not isinstance(processing, dict):
            return None
        started_at = processing.get("last_started_at")
        if not started_at:
            return None
        try:
            return datetime.fromisoformat(started_at)
        except ValueError:
            return None

    def _format_exception(self, exc: Exception) -> str:
        return f"{exc.__class__.__name__}: {exc}"

    def _coerce_utc(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
