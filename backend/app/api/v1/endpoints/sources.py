import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.source import Source
from app.schemas.source import (
    SourceCreateRequest,
    SourceCreateResponse,
    SourceListResponse,
    SourceRecord,
    SourceSyncAccepted,
    SourceSyncResponse,
)
from app.services.interfaces import DocumentIngestionService
from app.services.placeholders import get_document_ingestion_service

router = APIRouter()


@router.get("", response_model=SourceListResponse)
def list_sources(db: Session = Depends(get_db)) -> SourceListResponse:
    sources = db.scalars(select(Source).order_by(Source.created_at.desc())).all()
    payload = [
        SourceRecord(
            id=source.id,
            name=source.name,
            type=source.type,
            status=source.status,
            classification=source.classification,
            workspace_id=source.workspace_id,
            created_at=source.created_at,
        )
        for source in sources
    ]
    return SourceListResponse(data=payload)


@router.post("", response_model=SourceCreateResponse, status_code=status.HTTP_201_CREATED)
def create_source(payload: SourceCreateRequest, db: Session = Depends(get_db)) -> SourceCreateResponse:
    source = Source(
        workspace_id=payload.workspace_id,
        name=payload.name,
        type=payload.type,
        classification=payload.classification,
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return SourceCreateResponse(
        data=SourceRecord(
            id=source.id,
            name=source.name,
            type=source.type,
            status=source.status,
            classification=source.classification,
            workspace_id=source.workspace_id,
            created_at=source.created_at,
        )
    )


@router.post("/{source_id}/upload", status_code=status.HTTP_202_ACCEPTED)
async def upload_source_document(
    source_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    ingestion_service: DocumentIngestionService = Depends(get_document_ingestion_service),
) -> dict:
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")

    document = await ingestion_service.create_document_upload(
        db,
        upload=file,
        source=source,
    )
    ingestion_service.schedule_document_processing(
        document_id=str(document.id),
        background_tasks=background_tasks,
    )
    db.refresh(document)

    return {
        "data": {
            "document_id": document.id,
            "status": document.status,
            "error_message": document.processing_error,
        }
    }


@router.post("/{source_id}/sync", response_model=SourceSyncResponse, status_code=status.HTTP_202_ACCEPTED)
def sync_source(
    source_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    ingestion_service: DocumentIngestionService = Depends(get_document_ingestion_service),
) -> SourceSyncResponse:
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")

    job = ingestion_service.create_source_sync_job(db, source=source)
    ingestion_service.schedule_source_sync(job_id=str(job.id), background_tasks=background_tasks)

    return SourceSyncResponse(data=SourceSyncAccepted(job_id=job.id, status=job.status))
