import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Document(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "documents"

    workspace_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(), ForeignKey("workspaces.id"), nullable=True)
    source_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(), ForeignKey("sources.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(512))
    filename: Mapped[str] = mapped_column(String(512))
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="queued", index=True)
    storage_backend: Mapped[str] = mapped_column(String(50), default="local")
    storage_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    processing_attempts: Mapped[int] = mapped_column(Integer, default=0)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    processing_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    workspace = relationship("Workspace", back_populates="documents")
    source = relationship("Source", back_populates="documents")
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")


class DocumentChunk(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_chunks"

    document_id: Mapped[uuid.UUID] = mapped_column(Uuid(), ForeignKey("documents.id"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)

    document = relationship("Document", back_populates="chunks")
    embedding = relationship(
        "DocumentChunkEmbedding",
        back_populates="chunk",
        cascade="all, delete-orphan",
        uselist=False,
    )


class DocumentChunkEmbedding(TimestampMixin, Base):
    __tablename__ = "document_chunk_embeddings"

    chunk_id: Mapped[uuid.UUID] = mapped_column(Uuid(), ForeignKey("document_chunks.id"), primary_key=True)
    document_id: Mapped[uuid.UUID] = mapped_column(Uuid(), ForeignKey("documents.id"), index=True)
    embedding_model: Mapped[str] = mapped_column(String(64), index=True)
    embedding_dimension: Mapped[int] = mapped_column(Integer, default=0, index=True)
    embedding_json: Mapped[list[float]] = mapped_column(JSON)

    chunk = relationship("DocumentChunk", back_populates="embedding")
    document = relationship("Document")
