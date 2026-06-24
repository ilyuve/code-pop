"""Environment-driven configuration for the CodePop backend."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8080
    api_version: str = "0.2.0"

    # Database
    database_url: str = "postgresql://postgres:codepop123@localhost:5432/codepop"

    # Repositories storage
    repos_dir: Path = Path("./repos").resolve()

    # Embedding model (HuggingFace model name or local path).
    # Note: all-MiniLM-L6-v2 produces 384-d vectors.
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dim: int = 384
    embedding_batch_size: int = 32

    # Indexing
    index_chunk_max_lines: int = 200
    index_max_file_size: int = 1024 * 1024  # 1 MB
    index_batch_size: int = 100

    # Search
    search_default_limit: int = 20
    search_max_limit: int = 100

    # GitHub webhook
    github_webhook_secret: str = ""

    # Logging
    log_level: str = "INFO"


settings = Settings()
