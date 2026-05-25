from __future__ import annotations

from dataclasses import dataclass
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.document import Document, DocumentChunk
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.interfaces import RetrievalQuery
from app.retrieval.keyword_search import InMemoryKeywordSearch
from app.retrieval.text import build_index_text
from app.retrieval.storage import PgVectorEmbeddingRecord, SqlPgVectorStore
from app.retrieval.vector_search import PgVectorSearch
from app.services.document_models import SearchResult, SourceChunk
from app.services.embeddings import EmbeddingProvider, get_embedding_provider


@dataclass(slots=True)
class ChunkRetrievalIndex:
    retriever: HybridRetriever

    def search(self, query: RetrievalQuery) -> list[SearchResult]:
        return self.retriever.search(query)


class PersistedChunkEmbeddingIndexer:
    def __init__(self, db: Session, embedding_provider: EmbeddingProvider | None = None) -> None:
        self._db = db
        self._embedding_provider = embedding_provider or get_embedding_provider()
        self._store = SqlPgVectorStore(db)

    def index_chunks(self, chunks: list[SourceChunk]) -> None:
        if not chunks:
            return
        indexed_texts = [build_index_text(chunk) for chunk in chunks]
        embeddings = self._embedding_provider.embed_texts(indexed_texts)
        self._store.upsert_embeddings(
            [
                PgVectorEmbeddingRecord(
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    embedding_model=self._embedding_provider.model_name,
                    embedding_dimension=self._embedding_provider.dimensions,
                    embedding=embedding,
                )
                for chunk, embedding in zip(chunks, embeddings)
            ]
        )

    def index_missing_chunks(self, chunks: list[SourceChunk]) -> None:
        indexed_chunk_ids = self._store.get_indexed_chunk_ids(
            chunk_ids=[chunk.chunk_id for chunk in chunks],
            embedding_model=self._embedding_provider.model_name,
            embedding_dimension=self._embedding_provider.dimensions,
        )
        missing_chunks = [chunk for chunk in chunks if chunk.chunk_id not in indexed_chunk_ids]
        self.index_chunks(missing_chunks)

    def delete_document_version(self, document_version_id: str) -> None:
        self._store.delete_document_version(document_version_id)


class DatabaseRetrievalService:
    def __init__(self, db: Session, embedding_provider: EmbeddingProvider | None = None) -> None:
        self._db = db
        self._embedding_provider = embedding_provider or get_embedding_provider()

    def search(
        self,
        *,
        query: str,
        top_k: int = 10,
        workspace_id: uuid.UUID | str | None = None,
        source_ids: list[uuid.UUID | str] | None = None,
    ) -> list[SearchResult]:
        chunks = self._load_chunks(workspace_id=workspace_id, source_ids=source_ids or [])
        if not chunks:
            return []

        PersistedChunkEmbeddingIndexer(self._db, self._embedding_provider).index_missing_chunks(chunks)
        retriever = self._build_index(chunks)
        filters: dict[str, object] = {}
        if workspace_id is not None:
            filters["workspace_id"] = str(workspace_id)
        if source_ids:
            filters["source_id"] = [str(source_id) for source_id in source_ids]
        return retriever.search(RetrievalQuery(text=query, top_k=top_k, filters=filters))

    def _load_chunks(self, *, workspace_id: str | None, source_ids: list[str]) -> list[SourceChunk]:
        stmt = (
            select(DocumentChunk, Document)
            .join(Document, DocumentChunk.document_id == Document.id)
            .where(Document.status == "completed")
            .order_by(Document.updated_at.desc(), DocumentChunk.chunk_index.asc(), DocumentChunk.id.asc())
        )
        if workspace_id is not None:
            stmt = stmt.where(Document.workspace_id == workspace_id)
        if source_ids:
            stmt = stmt.where(Document.source_id.in_(source_ids))

        rows = self._db.execute(stmt).all()
        results: list[SourceChunk] = []
        for chunk, document in rows:
            metadata = chunk.metadata_json or {}
            results.append(
                SourceChunk(
                    chunk_id=str(chunk.id),
                    document_id=str(document.id),
                    document_version_id=str(document.id),
                    chunk_index=chunk.chunk_index,
                    text=chunk.content,
                    metadata=metadata,
                    source_id=str(document.source_id) if document.source_id else None,
                    workspace_id=str(document.workspace_id) if document.workspace_id else None,
                    document_title=document.title,
                    section_title=metadata.get("section_title"),
                    page_number=metadata.get("page_number"),
                    token_count=chunk.token_count,
                    char_start=metadata.get("char_start"),
                    char_end=metadata.get("char_end"),
                )
            )
        return results

    def _build_index(self, chunks: list[SourceChunk]) -> ChunkRetrievalIndex:
        return ChunkRetrievalIndex(
            retriever=HybridRetriever(
                vector_backend=PgVectorSearch(SqlPgVectorStore(self._db), self._embedding_provider),
                keyword_backend=InMemoryKeywordSearch(chunks),
            )
        )
