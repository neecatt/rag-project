import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.document import Document
from app.schemas.document import (
    DocumentListResponse,
    DocumentRecord,
    DocumentStatusPayload,
    DocumentStatusResponse,
    DocumentUploadAccepted,
    DocumentUploadResponse,
)
from app.services.interfaces import DocumentIngestionService
from app.services.placeholders import get_document_ingestion_service

router = APIRouter()


@router.get("", response_model=DocumentListResponse)
def list_documents(db: Session = Depends(get_db)) -> DocumentListResponse:
    documents = db.scalars(select(Document).order_by(Document.updated_at.desc())).all()
    payload = [
        DocumentRecord(
            id=document.id,
            title=document.title,
            source_id=document.source_id,
            source_name=document.source.name if document.source else None,
            document_type=document.metadata_json.get("document_type") if document.metadata_json else None,
            mime_type=document.mime_type,
            status=document.status,
            updated_at=document.updated_at,
        )
        for document in documents
    ]
    return DocumentListResponse(data=payload)


@router.post("/upload", response_model=DocumentUploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    workspace_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    ingestion_service: DocumentIngestionService = Depends(get_document_ingestion_service),
) -> DocumentUploadResponse:
    document = await ingestion_service.create_document_upload(
        db,
        upload=file,
        workspace_id=workspace_id,
    )
    ingestion_service.schedule_document_processing(
        document_id=str(document.id),
        background_tasks=background_tasks,
    )
    db.refresh(document)

    return DocumentUploadResponse(
        data=DocumentUploadAccepted(
            document_id=document.id,
            filename=document.filename,
            status=document.status,
            error_message=document.processing_error,
        )
    )


@router.get("/{document_id}/status", response_model=DocumentStatusResponse)
def get_document_status(document_id: uuid.UUID, db: Session = Depends(get_db)) -> DocumentStatusResponse:
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    return DocumentStatusResponse(
        data=DocumentStatusPayload(
            document_id=document.id,
            title=document.title,
            filename=document.filename,
            status=document.status,
            error_message=document.processing_error,
            processing_attempts=document.processing_attempts,
            processed_at=document.processed_at,
            created_at=document.created_at,
            updated_at=document.updated_at,
        )
    )
