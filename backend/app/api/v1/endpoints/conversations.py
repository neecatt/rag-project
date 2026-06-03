import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.chat import ChatMessage, ChatSession
from app.schemas.chat import (
    ConversationCreateResponse,
    ConversationDetail,
    ConversationDetailResponse,
    ConversationListResponse,
    ConversationMessageCreateRequest,
    ConversationRecord,
    FrontendChatMessage,
    FrontendChatMessageResponse,
)
from app.services.interfaces import ChatService
from app.services.placeholders import get_chat_service

router = APIRouter()
_PLACEHOLDER_TITLES = {"new conversation", "new chat"}


@router.get("", response_model=ConversationListResponse)
def list_conversations(db: Session = Depends(get_db)) -> ConversationListResponse:
    sessions = db.scalars(
        select(ChatSession).order_by(ChatSession.updated_at.desc(), ChatSession.created_at.desc(), ChatSession.id.desc())
    ).all()
    return ConversationListResponse(
        data=[
            ConversationRecord(id=session.id, title=session.title, updated_at=session.updated_at)
            for session in sessions
        ]
    )


@router.post("", response_model=ConversationCreateResponse, status_code=status.HTTP_201_CREATED)
def create_conversation(db: Session = Depends(get_db)) -> ConversationCreateResponse:
    session = ChatSession(title="New conversation")
    db.add(session)
    db.commit()
    db.refresh(session)
    return ConversationCreateResponse(
        data=ConversationRecord(id=session.id, title=session.title, updated_at=session.updated_at)
    )


@router.get("/{conversation_id}", response_model=ConversationDetailResponse)
def get_conversation(conversation_id: uuid.UUID, db: Session = Depends(get_db)) -> ConversationDetailResponse:
    session = db.get(ChatSession, conversation_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    return ConversationDetailResponse(
        data=ConversationDetail(
            id=session.id,
            title=session.title,
            updated_at=session.updated_at,
            messages=[
                FrontendChatMessage(
                    id=message.id,
                    role=message.role,
                    content=message.content,
                    citations=(message.metadata_json or {}).get("citations", []),
                    created_at=message.created_at,
                )
                for message in _ordered_messages(session.messages)
            ],
        )
    )


@router.post("/{conversation_id}/messages", response_model=FrontendChatMessageResponse)
async def create_conversation_message(
    conversation_id: uuid.UUID,
    payload: ConversationMessageCreateRequest,
    db: Session = Depends(get_db),
    chat_service: ChatService = Depends(get_chat_service),
) -> FrontendChatMessageResponse:
    if payload.session_id is not None and payload.session_id != conversation_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="session_id must match conversation_id",
        )

    session = db.get(ChatSession, conversation_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

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
    db.refresh(assistant_message)

    return FrontendChatMessageResponse(
        data=FrontendChatMessage(
            id=assistant_message.id,
            role=assistant_message.role,
            content=assistant_message.content,
            citations=citation_payloads,
            created_at=assistant_message.created_at,
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


def _ordered_messages(messages: list[ChatMessage]) -> list[ChatMessage]:
    return sorted(
        messages,
        key=lambda message: (
            (message.metadata_json or {}).get("sequence", 0),
            message.created_at,
            str(message.id),
        ),
    )


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
