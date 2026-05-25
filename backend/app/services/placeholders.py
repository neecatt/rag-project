from fastapi import Depends

from app.db.session import get_db
from app.services.chat_service import GroundedChatService
from app.services.ingestion import LocalDocumentIngestionService
from app.services.interfaces import ChatService, DocumentIngestionService
from app.services.retrieval_service import DatabaseRetrievalService


def get_document_ingestion_service() -> DocumentIngestionService:
    return LocalDocumentIngestionService()


def get_chat_service(db=Depends(get_db)) -> ChatService:
    return GroundedChatService(DatabaseRetrievalService(db))
