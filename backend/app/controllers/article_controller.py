"""
GlobeLens AI — ArticleController
GET  /articles/{id} | /articles/{id}/audio | /articles/mine | /articles/authored
POST /articles | /articles/{id}/publish | /articles/{id}/unpublish | /articles/sync
PUT  /articles/{id} | DELETE /articles/{id}

Two kinds of rows share this table:

* PIPELINE — collected by the scraper, published on arrival, editable by any
  journalist or admin.
* AUTHORED — written in the newsroom by a journalist. They start as DRAFT and
  are only publicly readable once published; only their author (or an admin)
  may edit, publish or delete them.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Path, Query, status, Depends, BackgroundTasks, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.controllers.auth_controller import get_current_user, get_current_user_optional
from app.core.database import get_db
from app.entities.models import (
    Article,
    ArticleOrigin,
    ProcessingStatus,
    PublicationStatus,
    User,
    UserRole,
)
from app.services.scraper_service import ScraperService

router = APIRouter()


class CreateArticleRequest(BaseModel):
    title: str
    content: str
    url: Optional[str] = None
    source_id: Optional[str] = None


class UpdateArticleRequest(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    url: Optional[str] = None


def _parse_uuid(raw: str, label: str = "article") -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid {label} UUID")


def _role_of(user: User) -> str:
    return user.role.value if hasattr(user.role, "value") else user.role


def _require_editor(current_user: User) -> None:
    """Content edits are open to journalists and admins."""
    if _role_of(current_user) not in (UserRole.ADMIN.value, UserRole.JOURNALIST.value):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Journalist or admin role required to modify articles",
        )


def _require_owner_or_admin(article: Article, current_user: User) -> None:
    """Authored articles belong to their writer; nobody else may change them.

    Pipeline rows are shared wire copy, so the editor check already done by the
    caller is sufficient for them.
    """
    if article.origin != ArticleOrigin.AUTHORED:
        return
    if _role_of(current_user) == UserRole.ADMIN.value:
        return
    if article.author_id == current_user.id:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Only the author or an admin can modify this article",
    )


def _serialize(article: Article) -> dict:
    """Shape one article row for the API, including source and author."""
    source = getattr(article, "source", None)
    author = getattr(article, "author", None)
    origin = article.origin.value if hasattr(article.origin, "value") else article.origin
    publication_status = (
        article.publication_status.value
        if hasattr(article.publication_status, "value")
        else article.publication_status
    )
    return {
        "id": str(article.id),
        "title": article.title,
        "content": article.content,
        "url": article.url,
        "published_at": article.published_at.isoformat() if article.published_at else None,
        "created_at": article.created_at.isoformat() if article.created_at else None,
        "event_id": str(article.event_id) if article.event_id else None,
        "is_hidden": article.is_hidden,
        "processing_status": (
            article.processing_status.value
            if hasattr(article.processing_status, "value")
            else article.processing_status
        ),
        "origin": origin,
        "publication_status": publication_status,
        "author": {"id": str(author.id), "name": author.name} if author else None,
        "source": (
            {
                "id": str(source.id),
                "name": source.name,
                "url": source.url,
                "country": source.country,
                "credibility_score": source.credibility_score,
            }
            if source
            else None
        ),
    }


def _validate_url(url: Optional[str]) -> Optional[str]:
    if url is None:
        return None
    cleaned = url.strip()
    if not cleaned:
        return None
    if not cleaned.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="url must be http(s)")
    return cleaned


async def _load_article(db: AsyncSession, article_uuid: uuid.UUID) -> Optional[Article]:
    """Load one article with the relationships _serialize touches.

    A bare db.get() leaves source/author as lazy loads, which raise
    MissingGreenlet under async SQLAlchemy the moment _serialize reads them.
    """
    result = await db.execute(
        select(Article)
        .where(Article.id == article_uuid)
        .options(selectinload(Article.source), selectinload(Article.author))
    )
    return result.scalar_one_or_none()


# ── Static paths first: /mine and /authored must not be captured by /{id} ──────
@router.get("/mine", summary="List the articles authored by the caller")
async def list_my_articles(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Drafts and published pieces written by the signed-in journalist/admin."""
    _require_editor(current_user)
    result = await db.execute(
        select(Article)
        .where(Article.author_id == current_user.id, Article.origin == ArticleOrigin.AUTHORED)
        .options(selectinload(Article.author))
        .order_by(Article.created_at.desc())
    )
    return {"articles": [_serialize(a) for a in result.scalars().all()]}


@router.get("/authored", summary="List published newsroom articles (public)")
async def list_authored_articles(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Public feed of published, non-hidden pieces written in the newsroom."""
    offset = (page - 1) * limit
    base = select(Article).where(
        Article.origin == ArticleOrigin.AUTHORED,
        Article.publication_status == PublicationStatus.PUBLISHED,
        Article.is_hidden.is_(False),
    )
    result = await db.execute(
        base.options(selectinload(Article.author))
        .order_by(Article.published_at.desc().nullslast(), Article.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    total = await db.scalar(
        select(func.count())
        .select_from(Article)
        .where(
            Article.origin == ArticleOrigin.AUTHORED,
            Article.publication_status == PublicationStatus.PUBLISHED,
            Article.is_hidden.is_(False),
        )
    ) or 0
    return {
        "articles": [_serialize(a) for a in result.scalars().all()],
        "page": page,
        "limit": limit,
        "total": total,
    }


@router.get("/{article_id}", summary="Get article by ID")
async def get_article(
    article_id: str = Path(...),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """Return the stored article.

    Authored drafts are only visible to their author or an admin; everyone else
    gets a 404 so an unpublished piece cannot be probed for existence.
    """
    article_uuid = _parse_uuid(article_id)
    article = await _load_article(db, article_uuid)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")

    if (
        article.origin == ArticleOrigin.AUTHORED
        and article.publication_status == PublicationStatus.DRAFT
    ):
        is_owner = current_user is not None and article.author_id == current_user.id
        is_admin = current_user is not None and _role_of(current_user) == UserRole.ADMIN.value
        if not (is_owner or is_admin):
            raise HTTPException(status_code=404, detail="Article not found")

    return _serialize(article)


@router.post("", status_code=status.HTTP_201_CREATED, summary="Write a new article (Journalist)")
async def create_article(
    payload: CreateArticleRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create an authored draft. Only journalists and admins may write."""
    _require_editor(current_user)

    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title cannot be empty")
    content = payload.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Content cannot be empty")

    article = Article(
        title=title,
        content=content,
        url=_validate_url(payload.url),
        origin=ArticleOrigin.AUTHORED,
        publication_status=PublicationStatus.DRAFT,
        # Authored pieces never enter the scraping/embedding pipeline, so they
        # are considered fully processed and carry no event until linked.
        processing_status=ProcessingStatus.PROCESSED,
        author_id=current_user.id,
    )
    db.add(article)
    await db.commit()
    return _serialize(await _load_article(db, article.id))


@router.put("/{article_id}", summary="Update article content (Journalist/Admin)")
async def update_article(
    payload: UpdateArticleRequest,
    article_id: str = Path(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Persist the edited fields, respecting authored-article ownership."""
    _require_editor(current_user)

    article_uuid = _parse_uuid(article_id)
    article = await _load_article(db, article_uuid)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")

    _require_owner_or_admin(article, current_user)

    if payload.title is not None:
        title = payload.title.strip()
        if not title:
            raise HTTPException(status_code=400, detail="Title cannot be empty")
        article.title = title
    if payload.content is not None:
        article.content = payload.content
    if payload.url is not None:
        article.url = _validate_url(payload.url)

    await db.commit()
    return {"message": "Article updated", **_serialize(await _load_article(db, article_uuid))}


@router.delete("/{article_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete article")
async def delete_article(
    article_id: str = Path(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete, restricted to editors (and, for authored rows, the author)."""
    _require_editor(current_user)

    article_uuid = _parse_uuid(article_id)
    article = await db.get(Article, article_uuid)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")

    _require_owner_or_admin(article, current_user)

    await db.delete(article)
    await db.commit()
    return None


@router.post("/{article_id}/publish", summary="Publish an authored article")
async def publish_article(
    article_id: str = Path(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Move an authored draft into the public feed."""
    return await _set_publication_status(article_id, True, db, current_user)


@router.post("/{article_id}/unpublish", summary="Return an authored article to draft")
async def unpublish_article(
    article_id: str = Path(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Hide an authored article again without deleting it."""
    return await _set_publication_status(article_id, False, db, current_user)


async def _set_publication_status(
    article_id: str, publish: bool, db: AsyncSession, current_user: User
) -> dict:
    _require_editor(current_user)

    article_uuid = _parse_uuid(article_id)
    article = await _load_article(db, article_uuid)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    if article.origin != ArticleOrigin.AUTHORED:
        raise HTTPException(
            status_code=400,
            detail="Only newsroom-authored articles can be published",
        )
    _require_owner_or_admin(article, current_user)

    if publish:
        article.publication_status = PublicationStatus.PUBLISHED
        if article.published_at is None:
            article.published_at = datetime.now(timezone.utc)
    else:
        article.publication_status = PublicationStatus.DRAFT

    await db.commit()
    return {
        "message": "Article published" if publish else "Article unpublished",
        **_serialize(await _load_article(db, article_uuid)),
    }


@router.get("/{article_id}/audio", status_code=status.HTTP_501_NOT_IMPLEMENTED, summary="Get audio narration for an article")
async def get_article_audio(
    article_id: str = Path(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Not implemented.

    Previously answered 200 "Audio generation placeholder". A 200 for a
    non-existent audio file is worse than a clear failure: players treat it as
    a valid stream and report silence rather than an error.
    """
    article_uuid = _parse_uuid(article_id)
    if not await db.get(Article, article_uuid):
        raise HTTPException(status_code=404, detail="Article not found")

    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Text-to-speech is not implemented: no audio pipeline is configured.",
    )


@router.post("/sync", status_code=status.HTTP_202_ACCEPTED, summary="Trigger RSS & Playwright scraping sync pipeline (Admin)")
async def sync_articles(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
):
    """Trigger the asynchronous ingestion pipeline. Admin only.

    Ingestion is an infrastructure action, not an editorial one: journalists
    write articles, they do not control what the platform collects.
    """
    if _role_of(current_user) != UserRole.ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can sync articles",
        )

    scraper_service = ScraperService()
    background_tasks.add_task(scraper_service.run_pipeline)
    return {"status": "sync_initiated"}
