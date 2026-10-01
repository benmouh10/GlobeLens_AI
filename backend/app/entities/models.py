"""GlobeLens AI — Domain Entities (SQLAlchemy ORM Models)"""
import enum
import uuid
from datetime import datetime
from typing import List, Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean, DateTime, Enum, Float, ForeignKey,
    String, Text, func
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.core.config import settings


# ── Base ──────────────────────────────────────────────────────────────────────
class Base(DeclarativeBase):
    pass


# ── Enumerations (matching blueprint spec) ────────────────────────────────────
class ProcessingStatus(str, enum.Enum):
    SCRAPED   = "SCRAPED"
    EMBEDDED  = "EMBEDDED"
    CLUSTERED = "CLUSTERED"
    PROCESSED = "PROCESSED"


class UserRole(str, enum.Enum):
    GUEST      = "GUEST"
    AUTH_USER  = "AUTH_USER"
    JOURNALIST = "JOURNALIST"
    ADMIN      = "ADMIN"


class FactCheckResult(str, enum.Enum):
    TRUE      = "TRUE"
    FALSE     = "FALSE"
    UNCERTAIN = "UNCERTAIN"


class BiasLean(str, enum.Enum):
    LEFT         = "LEFT"
    CENTER_LEFT  = "CENTER_LEFT"
    CENTER       = "CENTER"
    CENTER_RIGHT = "CENTER_RIGHT"
    RIGHT        = "RIGHT"


# ── Source ────────────────────────────────────────────────────────────────────
class Source(Base):
    """Models media publishers (BBC, CNN, Al Jazeera, etc.)."""
    __tablename__ = "sources"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str]               = mapped_column(String(255), nullable=False, unique=True)
    url: Mapped[str]                = mapped_column(String(500), nullable=False)
    country: Mapped[Optional[str]]  = mapped_column(String(100))
    credibility_score: Mapped[float] = mapped_column(Float, default=0.5)
    bias_lean: Mapped[BiasLean]     = mapped_column(Enum(BiasLean), default=BiasLean.CENTER)
    created_at: Mapped[datetime]    = mapped_column(DateTime(timezone=True), server_default=func.now())

    articles: Mapped[List["Article"]] = relationship("Article", back_populates="source")


# ── User ──────────────────────────────────────────────────────────────────────
class User(Base):
    """Authentication identity and user preferences."""
    __tablename__ = "users"

    id: Mapped[uuid.UUID]             = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str]                 = mapped_column(String(255), nullable=False)
    email: Mapped[str]                = mapped_column(String(320), nullable=False, unique=True, index=True)
    password_hash: Mapped[str]        = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole]            = mapped_column(Enum(UserRole), default=UserRole.AUTH_USER)
    is_blocked: Mapped[bool]          = mapped_column(Boolean, default=False)
    preferred_topics: Mapped[Optional[List[str]]]    = mapped_column(ARRAY(String), default=list)
    preferred_countries: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), default=list)
    created_at: Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now())

    comments: Mapped[List["Comment"]]           = relationship("Comment", back_populates="user")
    fact_check_requests: Mapped[List["FactCheckRequest"]] = relationship("FactCheckRequest", back_populates="user")


# ── Event ─────────────────────────────────────────────────────────────────────
class Event(Base):
    """High-level news event aggregating multiple articles."""
    __tablename__ = "events"

    id: Mapped[uuid.UUID]            = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str]               = mapped_column(String(500), nullable=False)
    summary: Mapped[Optional[str]]   = mapped_column(Text)
    topic: Mapped[Optional[str]]     = mapped_column(String(255), index=True)
    country: Mapped[Optional[str]]   = mapped_column(String(100), index=True)
    latitude: Mapped[Optional[float]]  = mapped_column(Float)
    longitude: Mapped[Optional[float]] = mapped_column(Float)
    importance_score: Mapped[float]  = mapped_column(Float, default=0.0)
    is_promoted: Mapped[bool]        = mapped_column(Boolean, default=False)
    bias_lean: Mapped[Optional[BiasLean]] = mapped_column(Enum(BiasLean), nullable=True)
    status: Mapped[str]              = mapped_column(String(50), default="DRAFT", index=True)
    created_at: Mapped[datetime]     = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime]     = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    articles: Mapped[List["Article"]] = relationship("Article", back_populates="event")
    comments: Mapped[List["Comment"]] = relationship("Comment", back_populates="event")


# ── Article ───────────────────────────────────────────────────────────────────
class Article(Base):
    """Foundational content unit — scraped from media publishers."""
    __tablename__ = "articles"

    id: Mapped[uuid.UUID]             = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str]                = mapped_column(String(500), nullable=False)
    content: Mapped[Optional[str]]    = mapped_column(Text)
    url: Mapped[str]                  = mapped_column(String(2000), nullable=False, unique=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now())
    processing_status: Mapped[ProcessingStatus] = mapped_column(
        Enum(ProcessingStatus), default=ProcessingStatus.SCRAPED, index=True
    )
    is_hidden: Mapped[bool]           = mapped_column(Boolean, default=False)
    source_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("sources.id"), index=True)
    event_id: Mapped[Optional[uuid.UUID]]  = mapped_column(UUID(as_uuid=True), ForeignKey("events.id"), index=True)

    source: Mapped[Optional["Source"]]  = relationship("Source", back_populates="articles")
    event: Mapped[Optional["Event"]]    = relationship("Event", back_populates="articles")
    embedding: Mapped[Optional["Embedding"]] = relationship("Embedding", back_populates="article", uselist=False)


# ── Embedding ─────────────────────────────────────────────────────────────────
class Embedding(Base):
    """Vector embedding storage — decoupled from Article for perf."""
    __tablename__ = "embeddings"

    id: Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # 1536 dimensions for text-embedding-3-small
    # Width tracks settings.EMBEDDING_DIMENSIONS so the ORM stays aligned with the
    # pgvector column after a provider switch (1536 OpenAI, 1024 bge-m3, 768 nomic).
    vector: Mapped[list]       = mapped_column(Vector(settings.EMBEDDING_DIMENSIONS))
    model: Mapped[str]         = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    article_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("articles.id"), unique=True, index=True)

    article: Mapped["Article"] = relationship("Article", back_populates="embedding")


# ── Comment ───────────────────────────────────────────────────────────────────
class Comment(Base):
    """User community comments on Events."""
    __tablename__ = "comments"

    id: Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    content: Mapped[str]       = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("events.id"), index=True)

    user:  Mapped["User"]  = relationship("User",  back_populates="comments")
    event: Mapped["Event"] = relationship("Event", back_populates="comments")


# ── FactCheckRequest ──────────────────────────────────────────────────────────
class FactCheckRequest(Base):
    """User-submitted external verification requests."""
    __tablename__ = "fact_check_requests"

    id: Mapped[uuid.UUID]          = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    input_text_url: Mapped[str]    = mapped_column(Text, nullable=False)
    result: Mapped[Optional[FactCheckResult]] = mapped_column(Enum(FactCheckResult))
    explanation: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime]   = mapped_column(DateTime(timezone=True), server_default=func.now())
    user_id: Mapped[uuid.UUID]     = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)

    user: Mapped["User"] = relationship("User", back_populates="fact_check_requests")
