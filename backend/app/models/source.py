import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Source(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "sources"

    workspace_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(), ForeignKey("workspaces.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(255))
    type: Mapped[str] = mapped_column(String(50), default="upload")
    status: Mapped[str] = mapped_column(String(50), default="active")
    classification: Mapped[str] = mapped_column(String(50), default="internal")

    workspace = relationship("Workspace", back_populates="sources")
    documents = relationship("Document", back_populates="source")
    jobs = relationship("SourceSyncJob", back_populates="source", cascade="all, delete-orphan")


class SourceSyncJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "source_sync_jobs"

    source_id: Mapped[uuid.UUID] = mapped_column(Uuid(), ForeignKey("sources.id"), index=True)
    job_type: Mapped[str] = mapped_column(String(50), default="sync")
    status: Mapped[str] = mapped_column(String(50), default="queued")
    documents_total: Mapped[int] = mapped_column(Integer, default=0)
    documents_processed: Mapped[int] = mapped_column(Integer, default=0)
    documents_failed: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    source = relationship("Source", back_populates="jobs")
