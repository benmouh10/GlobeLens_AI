"""
GlobeLens AI — Application Configuration
Reads all settings from environment variables (or .env file via pydantic-settings).
"""
from functools import lru_cache
from typing import Any, List, Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration store for all environment-driven settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ───────────────────────────────────────────────────────────
    APP_ENV: str = "development"
    SECRET_KEY: str = "CHANGE_ME_IN_PRODUCTION"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # ── PostgreSQL / pgvector ─────────────────────────────────────────────────
    # Async URL (asyncpg driver) — used by FastAPI runtime and SQLAlchemy engine
    DATABASE_URL: str = (
        "postgresql+asyncpg://globelens:globelens_secret@db:5432/globelens_db"
    )

    # ── Redis ─────────────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://:redis_secret@cache:6379/0"

    # ── Elasticsearch ─────────────────────────────────────────────────────────
    ELASTICSEARCH_URL: str = "http://search:9200"
    ELASTICSEARCH_INDEX_EVENTS: str = "globelens_events"

    # ── LLM Providers ─────────────────────────────────────────────────────────
    LLM_PROVIDER: str = "anthropic"          # "anthropic" | "openai" | "grok" | "gemini" | "nvidia" | "ollama"
    EMBEDDING_PROVIDER: str = "openai"       # "openai" | "gemini" | "grok" | "azure" | "ollama"
    ANTHROPIC_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    GROK_API_KEY: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None
    AZURE_EMBEDDING_API_KEY: Optional[str] = None
    AZURE_EMBEDDING_ENDPOINT: Optional[str] = None
    NVIDIA_API_KEY: Optional[str] = None
    NVIDIA_API_URL: str = "https://integrate.api.nvidia.com/v1"
    NVIDIA_LLM_MODEL: str = "nvidia/nemotron-3-super-120b-a12b"
    TAVILY_API_KEY: Optional[str] = None

    # ── Ollama (local inference, OpenAI-compatible API) ────────────────────────
    # Inside Docker the host is reachable via host.docker.internal, not localhost.
    OLLAMA_BASE_URL: str = "http://host.docker.internal:11434/v1"
    OLLAMA_LLM_MODEL: str = "qwen2.5-coder:14b"
    OLLAMA_EMBEDDING_MODEL: str = "bge-m3"

    # How much of an article body is fed to the embedding model. bge-m3 is a
    # document encoder: the lead carries the who/what/where, while the tail is
    # often boilerplate, related-links and newsletter furniture. Embedding the
    # whole body made syndicated roundups ("Latest news bulletin") collide with
    # each other on template structure rather than subject matter.
    EMBEDDING_MAX_CONTENT_CHARS: int = 1500


    # ── Embedding ─────────────────────────────────────────────────────────────
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    # Must match the pgvector column width in the embeddings table.
    # 1536 = text-embedding-3-small, 1024 = bge-m3, 768 = nomic-embed-text.
    EMBEDDING_DIMENSIONS: int = 1536

    # ── CORS ──────────────────────────────────────────────────────────────
    # Accepts a comma-separated string OR a JSON array string from the env:
    #   CORS_ORIGINS=http://localhost:3000          (bare string)
    #   CORS_ORIGINS=http://a:3000,http://b:3001   (comma-separated)
    #   CORS_ORIGINS=["http://localhost:3000"]      (JSON array)
    CORS_ORIGINS: Any = ["http://localhost:3000"]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: Any) -> List[str]:
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("["):          # JSON array
                import json
                return json.loads(v)
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    @property
    def SYNC_DATABASE_URL(self) -> str:
        """
        Synchronous database URL for Alembic migrations.

        Alembic's migration runner is synchronous (no event loop), so it
        cannot use asyncpg. We derive the sync URL from DATABASE_URL by
        replacing the driver segment, keeping credentials and host identical.

        postgresql+asyncpg://... → postgresql+psycopg2://...
        """
        return self.DATABASE_URL.replace(
            "postgresql+asyncpg://", "postgresql+psycopg2://"
        )


@lru_cache
def get_settings() -> Settings:
    """Cached singleton — instantiated once per process."""
    return Settings()


# Module-level convenience alias
settings = get_settings()
