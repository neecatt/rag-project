import uuid
from datetime import datetime

from pydantic import BaseModel


class DocumentUploadAccepted(BaseModel):
    document_id: uuid.UUID
    filename: str
    status: str
    error_message: str | None = None


class DocumentUploadResponse(BaseModel):
    data: DocumentUploadAccepted


class DocumentStatusPayload(BaseModel):
    document_id: uuid.UUID
    title: str
    filename: str
    status: str
    error_message: str | None = None
    processing_attempts: int = 0
    processed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class DocumentStatusResponse(BaseModel):
    data: DocumentStatusPayload


class DocumentRecord(BaseModel):
    id: uuid.UUID
    title: str
    source_id: uuid.UUID | None = None
    source_name: str | None = None
    document_type: str | None = None
    mime_type: str | None = None
    status: str
    updated_at: datetime


class DocumentListResponse(BaseModel):
    data: list[DocumentRecord]
