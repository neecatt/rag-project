from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.search import SearchRequest, SearchResponse, SearchResponseData, SearchResultPayload
from app.services.retrieval_service import DatabaseRetrievalService

router = APIRouter()


@router.post("/search", response_model=SearchResponse)
def search_documents(payload: SearchRequest, db: Session = Depends(get_db)) -> SearchResponse:
    retrieval_service = DatabaseRetrievalService(db)
    results = retrieval_service.search(
        query=payload.query,
        top_k=payload.top_k,
        workspace_id=payload.workspace_id,
        source_ids=payload.filters.source_ids,
    )
    return SearchResponse(
        data=SearchResponseData(
            results=[
                SearchResultPayload(
                    chunk_id=result.chunk.chunk_id,
                    document_id=result.chunk.document_id,
                    document_title=result.chunk.document_title,
                    score=result.score,
                    snippet=result.chunk.text,
                    source_id=result.chunk.source_id,
                    citation={
                        "document_id": citation.document_id,
                        "chunk_id": citation.chunk_id,
                        "title": citation.title,
                        "locator": citation.locator,
                        "source_id": citation.source_id,
                        "page_number": citation.page_number,
                        "section_title": citation.section_title,
                    },
                )
                for result in results
                for citation in [result.chunk.to_citation()]
            ]
        )
    )
