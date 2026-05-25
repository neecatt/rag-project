from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    app_name: str = Field(default="RAG Project Backend", alias="APP_NAME")
    app_env: str = Field(default="development", alias="APP_ENV")
    api_v1_prefix: str = Field(default="/api/v1", alias="APP_API_V1_PREFIX")
    cors_origins: list[str] = Field(
        default=["http://localhost:3000", "http://127.0.0.1:3000"],
        alias="APP_CORS_ORIGINS",
    )
    database_url: str = Field(
        default="sqlite+pysqlite:///./backend.db",
        validation_alias=AliasChoices("APP_DATABASE_URL", "DATABASE_URL"),
    )
    redis_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("APP_REDIS_URL", "REDIS_URL"),
    )
    auto_create_tables: bool = Field(default=True, alias="APP_AUTO_CREATE_TABLES")
    uploads_dir: Path = Field(
        default=Path(__file__).resolve().parents[2] / "uploads",
        alias="APP_UPLOADS_DIR",
    )
    ingestion_execution_mode: str = Field(default="inline", alias="APP_INGESTION_EXECUTION_MODE")
    ingestion_processing_timeout_seconds: int = Field(
        default=900,
        alias="APP_INGESTION_PROCESSING_TIMEOUT_SECONDS",
    )
    chat_answer_provider: str = Field(default="disabled", alias="APP_CHAT_ANSWER_PROVIDER")
    chat_answer_model: str | None = Field(default=None, alias="APP_CHAT_ANSWER_MODEL")
    chat_answer_api_key: str | None = Field(default=None, alias="APP_CHAT_ANSWER_API_KEY")
    chat_answer_base_url: str = Field(
        default="https://api.openai.com/v1/chat/completions",
        alias="APP_CHAT_ANSWER_BASE_URL",
    )
    chat_answer_timeout_seconds: int = Field(default=20, alias="APP_CHAT_ANSWER_TIMEOUT_SECONDS")
    embedding_provider: str = Field(default="local", alias="APP_EMBEDDING_PROVIDER")
    embedding_model: str = Field(default="local-hashing-v1", alias="APP_EMBEDDING_MODEL")
    embedding_api_key: str | None = Field(default=None, alias="APP_EMBEDDING_API_KEY")
    embedding_base_url: str = Field(
        default="https://api.openai.com/v1/embeddings",
        alias="APP_EMBEDDING_BASE_URL",
    )
    embedding_dimensions: int = Field(default=256, alias="APP_EMBEDDING_DIMENSIONS")
    embedding_timeout_seconds: int = Field(default=30, alias="APP_EMBEDDING_TIMEOUT_SECONDS")

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
