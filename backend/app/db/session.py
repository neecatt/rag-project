from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.db.base import Base


def _engine_kwargs(database_url: str) -> dict:
    kwargs: dict = {"future": True}
    if database_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if database_url.endswith(":memory:"):
            kwargs["poolclass"] = StaticPool
    return kwargs


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    settings = get_settings()
    return create_engine(settings.database_url, **_engine_kwargs(settings.database_url))


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = get_session_factory()()
    try:
        yield db
    finally:
        db.close()


def create_database_schema() -> None:
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    _ensure_pgvector_schema(engine)
    _ensure_compatible_columns(engine)


def healthcheck_database(db: Session) -> bool:
    db.execute(text("SELECT 1"))
    return True


def healthcheck_redis(redis_url: str | None) -> bool:
    if not redis_url:
        return False

    try:
        import redis

        client = redis.from_url(redis_url, socket_connect_timeout=1, socket_timeout=1)
        return bool(client.ping())
    except Exception:
        return False


def reset_database_state() -> None:
    get_session_factory.cache_clear()
    get_engine.cache_clear()


def _ensure_compatible_columns(engine: Engine) -> None:
    inspector = inspect(engine)
    compatibility_columns = {
        "chat_messages": {
            "metadata_json": {
                "postgresql": "ALTER TABLE chat_messages ADD COLUMN metadata_json JSON DEFAULT '{}'::json NOT NULL",
                "default": "ALTER TABLE chat_messages ADD COLUMN metadata_json JSON DEFAULT '{}' NOT NULL",
            },
        },
        "documents": {
            "storage_backend": {
                "postgresql": "ALTER TABLE documents ADD COLUMN storage_backend VARCHAR(50) DEFAULT 'local' NOT NULL",
                "default": "ALTER TABLE documents ADD COLUMN storage_backend VARCHAR(50) DEFAULT 'local' NOT NULL",
            },
            "storage_path": {
                "postgresql": "ALTER TABLE documents ADD COLUMN storage_path VARCHAR(1024)",
                "default": "ALTER TABLE documents ADD COLUMN storage_path VARCHAR(1024)",
            },
            "file_size_bytes": {
                "postgresql": "ALTER TABLE documents ADD COLUMN file_size_bytes INTEGER",
                "default": "ALTER TABLE documents ADD COLUMN file_size_bytes INTEGER",
            },
            "checksum_sha256": {
                "postgresql": "ALTER TABLE documents ADD COLUMN checksum_sha256 VARCHAR(64)",
                "default": "ALTER TABLE documents ADD COLUMN checksum_sha256 VARCHAR(64)",
            },
            "processing_attempts": {
                "postgresql": "ALTER TABLE documents ADD COLUMN processing_attempts INTEGER DEFAULT 0 NOT NULL",
                "default": "ALTER TABLE documents ADD COLUMN processing_attempts INTEGER DEFAULT 0 NOT NULL",
            },
            "last_error_at": {
                "postgresql": "ALTER TABLE documents ADD COLUMN last_error_at TIMESTAMP WITH TIME ZONE",
                "default": "ALTER TABLE documents ADD COLUMN last_error_at DATETIME",
            },
        },
        "source_sync_jobs": {
            "job_type": {
                "postgresql": "ALTER TABLE source_sync_jobs ADD COLUMN job_type VARCHAR(50) DEFAULT 'sync' NOT NULL",
                "default": "ALTER TABLE source_sync_jobs ADD COLUMN job_type VARCHAR(50) DEFAULT 'sync' NOT NULL",
            },
            "documents_total": {
                "postgresql": "ALTER TABLE source_sync_jobs ADD COLUMN documents_total INTEGER DEFAULT 0 NOT NULL",
                "default": "ALTER TABLE source_sync_jobs ADD COLUMN documents_total INTEGER DEFAULT 0 NOT NULL",
            },
            "documents_processed": {
                "postgresql": "ALTER TABLE source_sync_jobs ADD COLUMN documents_processed INTEGER DEFAULT 0 NOT NULL",
                "default": "ALTER TABLE source_sync_jobs ADD COLUMN documents_processed INTEGER DEFAULT 0 NOT NULL",
            },
            "documents_failed": {
                "postgresql": "ALTER TABLE source_sync_jobs ADD COLUMN documents_failed INTEGER DEFAULT 0 NOT NULL",
                "default": "ALTER TABLE source_sync_jobs ADD COLUMN documents_failed INTEGER DEFAULT 0 NOT NULL",
            },
            "error_message": {
                "postgresql": "ALTER TABLE source_sync_jobs ADD COLUMN error_message TEXT",
                "default": "ALTER TABLE source_sync_jobs ADD COLUMN error_message TEXT",
            },
            "started_at": {
                "postgresql": "ALTER TABLE source_sync_jobs ADD COLUMN started_at TIMESTAMP WITH TIME ZONE",
                "default": "ALTER TABLE source_sync_jobs ADD COLUMN started_at DATETIME",
            },
            "finished_at": {
                "postgresql": "ALTER TABLE source_sync_jobs ADD COLUMN finished_at TIMESTAMP WITH TIME ZONE",
                "default": "ALTER TABLE source_sync_jobs ADD COLUMN finished_at DATETIME",
            },
        },
        "document_chunk_embeddings": {
            "embedding_dimension": {
                "postgresql": "ALTER TABLE document_chunk_embeddings ADD COLUMN embedding_dimension INTEGER DEFAULT 0 NOT NULL",
                "default": "ALTER TABLE document_chunk_embeddings ADD COLUMN embedding_dimension INTEGER DEFAULT 0 NOT NULL",
            },
            "embedding_json": {
                "postgresql": "ALTER TABLE document_chunk_embeddings ADD COLUMN embedding_json JSON DEFAULT '[]'::json NOT NULL",
                "default": "ALTER TABLE document_chunk_embeddings ADD COLUMN embedding_json JSON DEFAULT '[]' NOT NULL",
            },
        },
    }

    with engine.begin() as connection:
        for table_name, column_specs in compatibility_columns.items():
            try:
                existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
            except Exception:
                continue

            for column_name, sql_by_dialect in column_specs.items():
                if column_name in existing_columns:
                    continue
                connection.execute(text(sql_by_dialect.get(engine.dialect.name, sql_by_dialect["default"])))


def _ensure_pgvector_schema(engine: Engine) -> None:
    if engine.dialect.name != "postgresql":
        return

    settings = get_settings()
    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        existing_columns = {
            column["name"]
            for column in inspect(engine).get_columns("document_chunk_embeddings")
        }
        if "embedding_vector" not in existing_columns:
            connection.execute(
                text(
                    f"ALTER TABLE document_chunk_embeddings "
                    f"ADD COLUMN embedding_vector vector({settings.embedding_dimensions})"
                )
            )
        connection.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_document_chunk_embeddings_vector
                ON document_chunk_embeddings
                USING ivfflat (embedding_vector vector_cosine_ops)
                """
            )
        )
