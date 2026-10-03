"""
GlobeLens AI — Application Configuration
Reads all settings from environment variables (or .env file via pydantic-settings).
"""
from functools import lru_cache
from typing import Any, List, Optional

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.redaction import redact_mapping


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

    # ── Rate limiting (Redis-backed; see app/middleware/rate_limit.py) ────────
    # Specs use the form "<count>/<period>" with period second|minute|hour|day.
    # AUTH guards the credential endpoints (brute-force surface); DEFAULT covers
    # every other route. TRUST_FORWARDED must stay False unless the app sits
    # behind a proxy that sets X-Forwarded-For, otherwise the header is spoofable.
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_DEFAULT: str = "120/minute"
    RATE_LIMIT_AUTH: str = "10/minute"
    RATE_LIMIT_TRUST_FORWARDED: bool = False

    # ── Security response headers (see app/middleware/security_headers.py) ────
    # HSTS is emitted automatically only when APP_ENV=production.
    SECURITY_HEADERS_ENABLED: bool = True

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

    # ── Email / Newsletter (SMTP) ─────────────────────────────────────────────
    # The development default targets the Mailpit catcher service defined in
    # docker-compose (SMTP on 1025, no auth, no TLS), so a fresh checkout can
    # send and inspect real mail without external credentials. Production
    # overrides these via SMTP_* environment variables.
    SMTP_HOST: str = "mailpit"
    SMTP_PORT: int = 1025
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = "newsletter@globelens.ai"
    SMTP_FROM_NAME: str = "GlobeLens AI"
    SMTP_STARTTLS: bool = False
    SMTP_SSL: bool = False
    SMTP_TIMEOUT_SECONDS: int = 15

    # Public base URLs embedded in outbound email links (confirm / unsubscribe
    # / open an event). Kept separate because the API and the web client are
    # distinct origins.
    FRONTEND_URL: str = "http://localhost:3000"
    API_PUBLIC_URL: str = "http://localhost:8000"

    # ── Newsletter scheduling ─────────────────────────────────────────────────
    NEWSLETTER_DAILY_TOP_N: int = 5
    NEWSLETTER_WEEKLY_TOP_N: int = 8
    NEWSLETTER_DAILY_HOUR_UTC: int = 7
    NEWSLETTER_WEEKLY_DAY: str = "monday"
    NEWSLETTER_WEEKLY_HOUR_UTC: int = 8

    # ── Celery (background jobs) ──────────────────────────────────────────────
    # Falls back to REDIS_URL when unset, so enabling the worker needs no extra
    # configuration in development.
    CELERY_BROKER_URL: str = ""
    CELERY_RESULT_BACKEND: str = ""

    # ── Web Push (VAPID) ──────────────────────────────────────────────────────
    # Generate a keypair with the cryptography package (P-256), url-safe base64
    # without padding. The private key signs every request; the public key is
    # handed to the browser. /push/vapid-public-key reports `enabled: false`
    # until both are set. PUSH_DAILY_BRIEFING_HOUR_UTC drives the beat task.
    VAPID_PUBLIC_KEY: str = ""
    VAPID_PRIVATE_KEY: str = ""
    VAPID_SUBJECT: str = "mailto:ops@globelens.ai"
    PUSH_DAILY_BRIEFING_HOUR_UTC: int = 8
    # Seconds the push service should retain an undelivered message. Must be
    # non-zero: Windows Push Notification Service answers ttl=0 with 400.
    PUSH_TTL_SECONDS: int = 3600

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

    @model_validator(mode="after")
    def _enforce_production_secrets(self) -> "Settings":
        """Refuse to start in production with a weak or default SECRET_KEY."""
        if self.APP_ENV.strip().lower() in {"production", "prod"}:
            key = (self.SECRET_KEY or "").strip()
            if key in {"", "CHANGE_ME_IN_PRODUCTION"} or len(key) < 32:
                raise ValueError(
                    "SECRET_KEY must be a random value of at least 32 characters "
                    "when APP_ENV=production. Generate one with: "
                    'python -c "import secrets; print(secrets.token_urlsafe(48))"'
                )
        return self

    def redacted(self) -> dict:
        """Settings as a mapping with secrets and URL credentials masked."""
        return redact_mapping(self.model_dump())

    def __repr__(self) -> str:
        return f"Settings({self.redacted()!r})"

    __str__ = __repr__

    @property
    def celery_broker(self) -> str:
        return self.CELERY_BROKER_URL or self.REDIS_URL

    @property
    def celery_backend(self) -> str:
        return self.CELERY_RESULT_BACKEND or self.REDIS_URL

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
