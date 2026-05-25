from fastapi import APIRouter

from app.api.v1.endpoints import chat, conversations, documents, health, search, sources

router = APIRouter()
router.include_router(health.router, tags=["health"])
router.include_router(sources.router, prefix="/sources", tags=["sources"])
router.include_router(documents.router, prefix="/documents", tags=["documents"])
router.include_router(search.router, tags=["search"])
router.include_router(conversations.router, prefix="/conversations", tags=["conversations"])
router.include_router(chat.router, prefix="/chat", tags=["chat"])
