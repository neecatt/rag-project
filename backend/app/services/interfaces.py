from dataclasses import dataclass
from typing import Protocol

import uuid

from fastapi import BackgroundTasks, UploadFile
from sqlalchemy.orm import Session

from app.models.chat import ChatMessage, ChatSession
from app.models.document import Document
from app.models.source import Source, SourceSyncJob
from app.services.document_models import Citation


class DocumentIngestionService(Protocol):
    async def create_document_upload(
        self,
        db: Session,
        *,
        upload: UploadFile,
        source: Source | None = None,
        workspace_id: uuid.UUID | None = None,
    ) -> Document: ...

    def schedule_document_processing(
        self,
        *,
        document_id: str,
        background_tasks: BackgroundTasks | None = None,
    ) -> None: ...

    def create_source_sync_job(self, db: Session, *, source: Source) -> SourceSyncJob: ...

    def schedule_source_sync(
        self,
        *,
        job_id: str,
        background_tasks: BackgroundTasks | None = None,
    ) -> None: ...


@dataclass(slots=True)
class ChatReply:
    content: str
    citations: list[Citation]


class ChatService(Protocol):
    async def generate_reply(
        self,
        *,
        session: ChatSession,
        user_message: ChatMessage,
        top_k: int = 3,
    ) -> ChatReply: ...
