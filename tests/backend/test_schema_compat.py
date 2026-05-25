from sqlalchemy import text

from app.db.session import create_database_schema, get_engine


def test_create_database_schema_adds_missing_legacy_columns(client):
    del client

    engine = get_engine()
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS chat_messages"))
        connection.execute(text("DROP TABLE IF EXISTS source_sync_jobs"))
        connection.execute(text("DROP TABLE IF EXISTS document_chunks"))
        connection.execute(text("DROP TABLE IF EXISTS documents"))
        connection.execute(text("DROP TABLE IF EXISTS sources"))

        connection.execute(
            text(
                """
                CREATE TABLE sources (
                    id CHAR(32) PRIMARY KEY,
                    workspace_id CHAR(32),
                    name VARCHAR(255) NOT NULL,
                    type VARCHAR(50) NOT NULL,
                    status VARCHAR(50) NOT NULL,
                    classification VARCHAR(50) NOT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE documents (
                    id CHAR(32) PRIMARY KEY,
                    workspace_id CHAR(32),
                    source_id CHAR(32),
                    title VARCHAR(512) NOT NULL,
                    filename VARCHAR(512) NOT NULL,
                    mime_type VARCHAR(255),
                    status VARCHAR(50) NOT NULL,
                    metadata_json JSON NOT NULL,
                    processing_error TEXT,
                    processed_at DATETIME,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE document_chunks (
                    id CHAR(32) PRIMARY KEY,
                    document_id CHAR(32) NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    token_count INTEGER,
                    metadata_json JSON NOT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE source_sync_jobs (
                    id CHAR(32) PRIMARY KEY,
                    source_id CHAR(32) NOT NULL,
                    status VARCHAR(50) NOT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE chat_messages (
                    id CHAR(32) PRIMARY KEY,
                    session_id CHAR(32) NOT NULL,
                    role VARCHAR(20) NOT NULL,
                    content TEXT NOT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            )
        )

    create_database_schema()

    inspector = engine.dialect.get_columns
    documents = {column["name"] for column in inspector(engine.connect(), "documents")}
    chat_messages = {column["name"] for column in inspector(engine.connect(), "chat_messages")}
    sync_jobs = {column["name"] for column in inspector(engine.connect(), "source_sync_jobs")}
    embeddings = {column["name"] for column in inspector(engine.connect(), "document_chunk_embeddings")}
    table_names = set(get_engine().dialect.get_table_names(engine.connect()))

    assert "storage_backend" in documents
    assert "storage_path" in documents
    assert "file_size_bytes" in documents
    assert "checksum_sha256" in documents
    assert "processing_attempts" in documents
    assert "last_error_at" in documents
    assert "metadata_json" in chat_messages
    assert "job_type" in sync_jobs
    assert "documents_total" in sync_jobs
    assert "documents_processed" in sync_jobs
    assert "documents_failed" in sync_jobs
    assert "error_message" in sync_jobs
    assert "started_at" in sync_jobs
    assert "finished_at" in sync_jobs
    assert "document_chunk_embeddings" in table_names
    assert "embedding_dimension" in embeddings
