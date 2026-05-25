import uuid

from pydantic import BaseModel, Field

from app.schemas.chat import CitationPayload


class SearchFilters(BaseModel):
    source_ids: list[uuid.UUID] = Field(default_factory=list)


class SearchRequest(BaseModel):
    query: str
    workspace_id: uuid.UUID | None = None
    filters: SearchFilters = Field(default_factory=SearchFilters)
    top_k: int = 10


class SearchResultPayload(BaseModel):
    chunk_id: str
    document_id: str
    document_title: str | None = None
    score: float
    snippet: str
    source_id: str | None = None
    citation: CitationPayload


class SearchResponseData(BaseModel):
    results: list[SearchResultPayload]


class SearchResponse(BaseModel):
    data: SearchResponseData
