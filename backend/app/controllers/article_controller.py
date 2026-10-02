"""
GlobeLens AI — ArticleController
GET  /articles/{id} | /events/{id}/articles | /articles/{id}/audio
POST /articles | PUT /articles/{id} | DELETE /articles/{id}
POST /articles/sync
"""
import uuid
from typing import Optional
from fastapi import APIRouter, Path, status, Depends, BackgroundTasks, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.controllers.auth_controller import get_current_user
from app.core.database import get_db
from app.entities.models import User, UserRole
from app.services.scraper_service import ScraperService

router = APIRouter()


class CreateArticleRequest(BaseModel):
    title: str
    content: str
    url: str
    source_id: Optional[str] = None


def _parse_uuid(raw: str, label: str = "article") -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid {label} UUID")


def _serialize(article) -> dict:
    """Shape one article row for the API, including its source when present."""
    source = getattr(article, "source", None)
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


@router.get("/{article_id}", summary="Get article by ID")
async def get_article(
    article_id: str = Path(...),
    db: AsyncSession = Depends(get_db)
):
    """
    Return the stored article.

    This previously answered 200 with {"title": "Placeholder Article"} for
    *any* id, including ids that do not exist. A client could not tell a real
    article from an invented one, and a deleted article still resolved.
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from app.entities.models import Article

    article_uuid = _parse_uuid(article_id)
    # selectinload, not a bare db.get: touching article.source below is a lazy
    # load, and under async SQLAlchemy a lazy load outside the query context
    # raises MissingGreenlet and 500s.
    result = await db.execute(
        select(Article).where(Article.id == article_uuid).options(selectinload(Article.source))
    )
    article = result.scalar_one_or_none()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    return _serialize(article)


@router.post("", status_code=status.HTTP_501_NOT_IMPLEMENTED, summary="Submit a new article (Journalist)")
async def create_article(payload: CreateArticleRequest):
    """
    Not implemented.

    Previously returned 201 "Article submitted" without inserting anything.
    Articles enter the system through the ingestion pipeline, which assigns
    source and event; hand-inserting one here would produce a row that the
    clustering stage never sees and that no citation can resolve.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Direct article submission is not implemented: articles are "
               "created by the ingestion pipeline.",
    )


@router.put("/{article_id}", summary="Update article content (Journalist/Admin)")
async def update_article(
    article_id: str = Path(...),
    payload: CreateArticleRequest = ...,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Persist the edited fields.

    Previously answered "Article updated" without writing or even checking who
    was asking, so any caller could believe they had edited an article.
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from app.entities.models import Article

    _require_editor(current_user)

    article_uuid = _parse_uuid(article_id)
    # selectinload, not a bare db.get: _serialize touches article.source. A
    # db.refresh() would expire that relationship and the next access would
    # lazy-load it outside the greenlet context, raising MissingGreenlet (500)
    # *after* the commit had already persisted the edit.
    result = await db.execute(
        select(Article).where(Article.id == article_uuid).options(selectinload(Article.source))
    )
    article = result.scalar_one_or_none()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")

    if payload.title is not None:
        title = payload.title.strip()
        if not title:
            raise HTTPException(status_code=400, detail="Title cannot be empty")
        article.title = title
    if payload.content is not None:
        article.content = payload.content
    if payload.url is not None:
        if not payload.url.startswith(("http://", "https://")):
            raise HTTPException(status_code=400, detail="url must be http(s)")
        article.url = payload.url

    await db.commit()
    return {"message": "Article updated", **_serialize(article)}


@router.delete("/{article_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete article")
async def delete_article(
    article_id: str = Path(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Actually delete, restricted to editors. Previously 204 without deleting."""
    from app.entities.models import Article

    _require_editor(current_user)

    article_uuid = _parse_uuid(article_id)
    article = await db.get(Article, article_uuid)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")

    await db.delete(article)
    await db.commit()
    return None


@router.get("/{article_id}/audio", summary="Get TTS audio stream for article")
async def get_article_audio(
    article_id: str = Path(...),
    db: AsyncSession = Depends(get_db)
):
    """
    Not implemented.

    Previously answered 200 "Audio generation placeholder". A 200 for a
    non-existent audio file is worse than a clear failure: players treat it as
    a valid stream and report silence rather than an error.
    """
    from app.entities.models import Article

    article_uuid = _parse_uuid(article_id)
    if not await db.get(Article, article_uuid):
        raise HTTPException(status_code=404, detail="Article not found")

    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Text-to-speech is not implemented: no audio pipeline is configured.",
    )


def _require_editor(current_user: User) -> None:
    """Article edits are limited to the roles the docstring names."""
    role = current_user.role.value if hasattr(current_user.role, "value") else current_user.role
    if role not in (UserRole.ADMIN.value, UserRole.JOURNALIST.value):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Journalist or admin role required to modify articles",
        )


@router.post("/sync", status_code=status.HTTP_202_ACCEPTED, summary="Trigger RSS & Playwright scraping sync pipeline (Admin/Journalist)")
async def sync_articles(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user)
):
    """
    Trigger the asynchronous data ingestion pipeline.
    Authorized for Admin and Journalist roles only.
    """
    if current_user.role not in (UserRole.ADMIN, UserRole.JOURNALIST):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only journalists and administrators can sync articles"
        )
        
    scraper_service = ScraperService()
    background_tasks.add_task(scraper_service.run_pipeline)
    return {"status": "sync_initiated"}
