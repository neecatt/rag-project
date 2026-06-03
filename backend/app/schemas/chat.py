import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class CitationPayload(BaseModel):
    document_id: str
    chunk_id: str
    title: str
    locator: str
    source_id: str | None = None
    page_number: int | None = None
    section_title: str | None = None


class ChatOptions(BaseModel):
    stream: bool = False
    top_k: int = Field(default=3, ge=1)


class ChatRequest(BaseModel):
    message: str
    session_id: uuid.UUID | None = None
    workspace_id: uuid.UUID | None = None
    options: ChatOptions | None = None


class ConversationMessageCreateRequest(ChatRequest):
    pass


class ChatTurnPayload(BaseModel):
    message_id: uuid.UUID
    role: str
    content: str
    created_at: datetime
    citations: list[CitationPayload] = Field(default_factory=list)


class ChatResponsePayload(BaseModel):
    session_id: uuid.UUID
    messages: list[ChatTurnPayload]


class ChatResponse(BaseModel):
    data: ChatResponsePayload


class ConversationRecord(BaseModel):
    id: uuid.UUID
    title: str | None = None
    updated_at: datetime


class ConversationListResponse(BaseModel):
    data: list[ConversationRecord]


class ConversationDetail(BaseModel):
    id: uuid.UUID
    title: str | None = None
    updated_at: datetime
    messages: list["FrontendChatMessage"]


class ConversationDetailResponse(BaseModel):
    data: ConversationDetail


class ConversationCreateResponse(BaseModel):
    data: ConversationRecord


class FrontendChatMessage(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    citations: list[CitationPayload] = Field(default_factory=list)
    created_at: datetime


class FrontendChatMessageResponse(BaseModel):
    data: FrontendChatMessage


ConversationDetail.model_rebuild()
