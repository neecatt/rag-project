from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import uuid

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.models.document import Document, DocumentChunk, DocumentChunkEmbedding
from app.retrieval.keyword_search import _matches_filters
from app.services.document_models import SourceChunk
from app.services.embeddings import cosine_similarity


@dataclass(slots=True)
class PgVectorEmbeddingRecord:
    chunk_id: str
    document_id: str
    embedding_model: str
    embedding_dimension: int
    embedding: list[float]
    tenant_id: str | None = None


class PgVectorStore(ABC):
    @abstractmethod
    def upsert_chunks(self, chunks: list[SourceChunk]) -> None:
        raise NotImplementedError

    @abstractmethod
    def upsert_embeddings(self, records: list[PgVectorEmbeddingRecord]) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_indexed_chunk_ids(self, *, chunk_ids: list[str], embedding_model: str, embedding_dimension: int) -> set[str]:
        raise NotImplementedError

    @abstractmethod
    def delete_document_version(self, document_version_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def vector_search(
        self,
        embedding: list[float],
        *,
        top_k: int,
        filters: dict[str, object] | None = None,
        embedding_model: str | None = None,
        embedding_dimension: int | None = None,
    ) -> list[tuple[SourceChunk, float]]:
        raise NotImplementedError


class InMemoryPgVectorStore(PgVectorStore):
    def __init__(self) -> None:
        self._chunks: dict[str, SourceChunk] = {}
        self._records: dict[str, PgVectorEmbeddingRecord] = {}

    def upsert_chunks(self, chunks: list[SourceChunk]) -> None:
        for chunk in chunks:
            self._chunks[chunk.chunk_id] = chunk

    def upsert_embeddings(self, records: list[PgVectorEmbeddingRecord]) -> None:
        for record in records:
            self._records[record.chunk_id] = record

    def get_indexed_chunk_ids(self, *, chunk_ids: list[str], embedding_model: str, embedding_dimension: int) -> set[str]:
        return {
            chunk_id
            for chunk_id in chunk_ids
            if chunk_id in self._records and self._records[chunk_id].embedding_model == embedding_model
            and self._records[chunk_id].embedding_dimension == embedding_dimension
        }

    def delete_document_version(self, document_version_id: str) -> None:
        removable_chunk_ids = [
            chunk_id
            for chunk_id, chunk in self._chunks.items()
            if chunk.document_version_id == document_version_id
        ]
        for chunk_id in removable_chunk_ids:
            self._chunks.pop(chunk_id, None)
            self._records.pop(chunk_id, None)

    def vector_search(
        self,
        embedding: list[float],
        *,
        top_k: int,
        filters: dict[str, object] | None = None,
        embedding_model: str | None = None,
        embedding_dimension: int | None = None,
    ) -> list[tuple[SourceChunk, float]]:
        results: list[tuple[SourceChunk, float]] = []
        for chunk_id, record in self._records.items():
            chunk = self._chunks.get(chunk_id)
            if not chunk or not _matches_filters(chunk, filters or {}):
                continue
            if embedding_model and record.embedding_model != embedding_model:
                continue
            if embedding_dimension and record.embedding_dimension != embedding_dimension:
                continue
            results.append((chunk, cosine_similarity(embedding, record.embedding)))
        return sorted(results, key=lambda item: item[1], reverse=True)[:top_k]


class SqlPgVectorStore(PgVectorStore):
    def __init__(self, db: Session) -> None:
        self._db = db

    def upsert_chunks(self, chunks: list[SourceChunk]) -> None:
        return None

    def upsert_embeddings(self, records: list[PgVectorEmbeddingRecord]) -> None:
        if not records:
            return

        chunk_ids = [record.chunk_id for record in records]
        existing = {
            str(record.chunk_id): record
            for record in self._db.scalars(
                select(DocumentChunkEmbedding).where(DocumentChunkEmbedding.chunk_id.in_(_coerce_uuid_values(chunk_ids)))
            ).all()
        }
        for record in records:
            stored = existing.get(record.chunk_id)
            if stored is None:
                self._db.add(
                    DocumentChunkEmbedding(
                        chunk_id=_coerce_uuid(record.chunk_id),
                        document_id=_coerce_uuid(record.document_id),
                        embedding_model=record.embedding_model,
                        embedding_dimension=record.embedding_dimension,
                        embedding_json=record.embedding,
                    )
                )
                self._set_pgvector_embedding(record)
                continue
            stored.embedding_model = record.embedding_model
            stored.embedding_dimension = record.embedding_dimension
            stored.embedding_json = record.embedding
            stored.document_id = _coerce_uuid(record.document_id)
            self._set_pgvector_embedding(record)

    def get_indexed_chunk_ids(self, *, chunk_ids: list[str], embedding_model: str, embedding_dimension: int) -> set[str]:
        if not chunk_ids:
            return set()
        rows = self._db.execute(
            select(DocumentChunkEmbedding.chunk_id).where(
                DocumentChunkEmbedding.chunk_id.in_(_coerce_uuid_values(chunk_ids)),
                DocumentChunkEmbedding.embedding_model == embedding_model,
                DocumentChunkEmbedding.embedding_dimension == embedding_dimension,
            )
        ).all()
        return {str(chunk_id) for (chunk_id,) in rows}

    def delete_document_version(self, document_version_id: str) -> None:
        self._db.execute(
            delete(DocumentChunkEmbedding).where(DocumentChunkEmbedding.document_id == _coerce_uuid(document_version_id))
        )

    def vector_search(
        self,
        embedding: list[float],
        *,
        top_k: int,
        filters: dict[str, object] | None = None,
        embedding_model: str | None = None,
        embedding_dimension: int | None = None,
    ) -> list[tuple[SourceChunk, float]]:
        if self._db.bind is not None and self._db.bind.dialect.name == "postgresql":
            return self._pgvector_search(
                embedding,
                top_k=top_k,
                filters=filters or {},
                embedding_model=embedding_model,
                embedding_dimension=embedding_dimension,
            )

        stmt = (
            select(DocumentChunkEmbedding, DocumentChunk, Document)
            .join(DocumentChunk, DocumentChunkEmbedding.chunk_id == DocumentChunk.id)
            .join(Document, DocumentChunk.document_id == Document.id)
            .where(Document.status == "completed")
        )
        if embedding_model is not None:
            stmt = stmt.where(DocumentChunkEmbedding.embedding_model == embedding_model)
        if embedding_dimension is not None:
            stmt = stmt.where(DocumentChunkEmbedding.embedding_dimension == embedding_dimension)

        rows = self._db.execute(stmt).all()
        results: list[tuple[SourceChunk, float]] = []
        for stored_embedding, chunk, document in rows:
            metadata = chunk.metadata_json or {}
            source_chunk = SourceChunk(
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
            if not _matches_filters(source_chunk, filters or {}):
                continue
            results.append((source_chunk, cosine_similarity(embedding, stored_embedding.embedding_json)))

        return sorted(results, key=lambda item: item[1], reverse=True)[:top_k]

    def _set_pgvector_embedding(self, record: PgVectorEmbeddingRecord) -> None:
        if self._db.bind is None or self._db.bind.dialect.name != "postgresql":
            return
        self._db.execute(
            text(
                """
                UPDATE document_chunk_embeddings
                SET embedding_vector = CAST(:embedding AS vector)
                WHERE chunk_id = :chunk_id
                """
            ),
            {
                "embedding": _vector_literal(record.embedding),
                "chunk_id": str(record.chunk_id),
            },
        )

    def _pgvector_search(
        self,
        embedding: list[float],
        *,
        top_k: int,
        filters: dict[str, object],
        embedding_model: str | None,
        embedding_dimension: int | None,
    ) -> list[tuple[SourceChunk, float]]:
        conditions = [
            "d.status = 'completed'",
            "e.embedding_vector IS NOT NULL",
        ]
        params: dict[str, object] = {
            "embedding": _vector_literal(embedding),
            "top_k": top_k,
        }
        if embedding_model is not None:
            conditions.append("e.embedding_model = :embedding_model")
            params["embedding_model"] = embedding_model
        if embedding_dimension is not None:
            conditions.append("e.embedding_dimension = :embedding_dimension")
            params["embedding_dimension"] = embedding_dimension
        if "workspace_id" in filters:
            conditions.append("d.workspace_id = CAST(:workspace_id AS uuid)")
            params["workspace_id"] = str(filters["workspace_id"])
        if "source_id" in filters:
            source_ids = filters["source_id"]
            if isinstance(source_ids, (list, tuple, set)):
                source_ids = [str(source_id) for source_id in source_ids]
                if not source_ids:
                    return []
                conditions.append("d.source_id = ANY(CAST(:source_ids AS uuid[]))")
                params["source_ids"] = source_ids
            else:
                conditions.append("d.source_id = CAST(:source_id AS uuid)")
                params["source_id"] = str(source_ids)

        sql = text(
            f"""
            SELECT
                e.embedding_json,
                c.id AS chunk_id,
                c.document_id AS document_id,
                c.chunk_index AS chunk_index,
                c.content AS content,
                c.token_count AS token_count,
                c.metadata_json AS metadata_json,
                d.title AS document_title,
                d.source_id AS source_id,
                d.workspace_id AS workspace_id,
                1 - (e.embedding_vector <=> CAST(:embedding AS vector)) AS score
            FROM document_chunk_embeddings e
            JOIN document_chunks c ON e.chunk_id = c.id
            JOIN documents d ON c.document_id = d.id
            WHERE {" AND ".join(conditions)}
            ORDER BY e.embedding_vector <=> CAST(:embedding AS vector)
            LIMIT :top_k
            """
        )
        rows = self._db.execute(sql, params).mappings().all()
        results: list[tuple[SourceChunk, float]] = []
        for row in rows:
            metadata = row["metadata_json"] or {}
            source_chunk = SourceChunk(
                chunk_id=str(row["chunk_id"]),
                document_id=str(row["document_id"]),
                document_version_id=str(row["document_id"]),
                chunk_index=row["chunk_index"],
                text=row["content"],
                metadata=metadata,
                source_id=str(row["source_id"]) if row["source_id"] else None,
                workspace_id=str(row["workspace_id"]) if row["workspace_id"] else None,
                document_title=row["document_title"],
                section_title=metadata.get("section_title"),
                page_number=metadata.get("page_number"),
                token_count=row["token_count"],
                char_start=metadata.get("char_start"),
                char_end=metadata.get("char_end"),
            )
            results.append((source_chunk, float(row["score"] or 0.0)))
        return results


def _coerce_uuid(value: str | uuid.UUID) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


def _coerce_uuid_values(values: list[str | uuid.UUID]) -> list[uuid.UUID]:
    return [_coerce_uuid(value) for value in values]


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{value:.12g}" for value in values) + "]"
