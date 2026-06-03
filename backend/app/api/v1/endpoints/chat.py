import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.chat import ChatMessage, ChatSession
from app.schemas.chat import ChatRequest, ChatResponse, ChatResponsePayload, ChatTurnPayload
from app.services.interfaces import ChatService
from app.services.placeholders import get_chat_service

router = APIRouter()
_PLACEHOLDER_TITLES = {"new conversation", "new chat"}


@router.post("", response_model=ChatResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_chat_message(
    payload: ChatRequest,
    db: Session = Depends(get_db),
    chat_service: ChatService = Depends(get_chat_service),
) -> ChatResponse:
    session = db.get(ChatSession, payload.session_id) if payload.session_id else None
    if payload.session_id and session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    if session is None:
        session = ChatSession(workspace_id=payload.workspace_id, title="New chat")
        db.add(session)
        db.flush()

    next_sequence = _next_message_sequence(db, session.id)
    user_message = ChatMessage(
        session_id=session.id,
        role="user",
        content=payload.message,
        metadata_json={"sequence": next_sequence},
    )
    db.add(user_message)
    db.flush()

    reply = await chat_service.generate_reply(
        session=session,
        user_message=user_message,
        top_k=payload.options.top_k if payload.options else 3,
    )
    citation_payloads = _serialize_citations(reply.citations)
    assistant_message = ChatMessage(
        session_id=session.id,
        role="assistant",
        content=reply.content,
        metadata_json={"citations": citation_payloads, "sequence": next_sequence + 1},
    )
    db.add(assistant_message)
    session.updated_at = datetime.now(timezone.utc)
    if next_sequence == 1 and _should_replace_title(session.title):
        session.title = _message_title_excerpt(payload.message)
    db.commit()
    db.refresh(session)
    db.refresh(user_message)
    db.refresh(assistant_message)

    return ChatResponse(
        data=ChatResponsePayload(
            session_id=session.id,
            messages=[
                ChatTurnPayload(
                    message_id=user_message.id,
                    role=user_message.role,
                    content=user_message.content,
                    created_at=user_message.created_at,
                    citations=[],
                ),
                ChatTurnPayload(
                    message_id=assistant_message.id,
                    role=assistant_message.role,
                    content=assistant_message.content,
                    created_at=assistant_message.created_at,
                    citations=citation_payloads,
                ),
            ],
        )
    )


def _serialize_citations(citations) -> list[dict]:
    return [
        {
            "document_id": citation.document_id,
            "chunk_id": citation.chunk_id,
            "title": citation.title,
            "locator": citation.locator,
            "source_id": citation.source_id,
            "page_number": citation.page_number,
            "section_title": citation.section_title,
        }
        for citation in citations
    ]


def _next_message_sequence(db: Session, session_id: uuid.UUID) -> int:
    return db.query(ChatMessage).filter(ChatMessage.session_id == session_id).count() + 1


def _should_replace_title(title: str | None) -> bool:
    if title is None:
        return True

    normalized_title = title.strip()
    if not normalized_title:
        return True

    return normalized_title.lower() in _PLACEHOLDER_TITLES


def _message_title_excerpt(message: str) -> str:
    normalized_message = message.strip()
    if normalized_message:
        return normalized_message[:80]

    return message[:80]
