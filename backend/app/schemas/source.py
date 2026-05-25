import uuid
from datetime import datetime

from pydantic import BaseModel


class SourceRecord(BaseModel):
    id: uuid.UUID
    name: str
    type: str
    status: str
    classification: str
    workspace_id: uuid.UUID | None = None
    created_at: datetime


class SourceListResponse(BaseModel):
    data: list[SourceRecord]


class SourceCreateRequest(BaseModel):
    name: str
    type: str = "upload"
    workspace_id: uuid.UUID | None = None
    classification: str = "internal"
    config: dict | None = None


class SourceCreateResponse(BaseModel):
    data: SourceRecord


class SourceSyncAccepted(BaseModel):
    job_id: uuid.UUID
    status: str


class SourceSyncResponse(BaseModel):
    data: SourceSyncAccepted
