"""
GlobeLens AI — CommentController
POST /events/{id}/comments | GET /events/{id}/comments
PUT  /comments/{id}         | DELETE /comments/{id}

Every handler here used to report success without touching the database:
POST answered 201 "Comment posted" while storing nothing, GET always returned
an empty list, and PUT/DELETE claimed edits and deletions that never happened.
The Comment table already existed and the admin router already supported
deleting a comment, so the feature was half-built rather than unimplemented.
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Path, status, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.controllers.auth_controller import get_current_user, get_current_user_optional
from app.core.database import get_db
from app.entities.models import (
    Article,
    ArticleOrigin,
    Comment,
    Event,
    PublicationStatus,
    User,
    UserRole,
)

router = APIRouter()

MAX_COMMENT_LENGTH = 4000


class CreateCommentRequest(BaseModel):
    content: str

    @field_validator("content")
    @classmethod
    def content_not_blank(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Comment content must not be empty")
        if len(trimmed) > MAX_COMMENT_LENGTH:
            raise ValueError(f"Comment must be at most {MAX_COMMENT_LENGTH} characters")
        return trimmed


def _parse_uuid(raw: str, label: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid {label} UUID")


def _serialize(comment: Comment) -> dict:
    return {
        "id": str(comment.id),
        "content": comment.content,
        "created_at": comment.created_at.isoformat() if comment.created_at else None,
        "event_id": str(comment.event_id) if comment.event_id else None,
        "article_id": str(comment.article_id) if comment.article_id else None,
        "user_id": str(comment.user_id),
        "author": comment.user.name if comment.user else "Deleted user",
    }


def _is_admin(user: Optional[User]) -> bool:
    if user is None:
        return False
    role = user.role.value if hasattr(user.role, "value") else user.role
    return role == UserRole.ADMIN.value


async def _load_commentable_article(
    db: AsyncSession, article_uuid: uuid.UUID, current_user: Optional[User]
) -> Article:
    """Return the article if its discussion is open, else raise 404.

    Draft newsroom pieces stay invisible to everyone but their author and
    admins, exactly as they are on the article endpoint itself.
    """
    article = await db.get(Article, article_uuid)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")

    is_draft = (
        article.origin == ArticleOrigin.AUTHORED
        and article.publication_status == PublicationStatus.DRAFT
    )
    if is_draft:
        is_owner = current_user is not None and article.author_id == current_user.id
        if not (is_owner or _is_admin(current_user)):
            raise HTTPException(status_code=404, detail="Article not found")
    return article


@router.post(
    "/events/{event_id}/comments",
    status_code=status.HTTP_201_CREATED,
    summary="Post a comment on an event"
)
async def create_comment(
    event_id: str = Path(...),
    payload: CreateCommentRequest = ...,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    event_uuid = _parse_uuid(event_id, "event")
    if not await db.get(Event, event_uuid):
        raise HTTPException(status_code=404, detail="Event not found")

    comment = Comment(content=payload.content, event_id=event_uuid, user_id=current_user.id)
    db.add(comment)
    await db.commit()
    await db.refresh(comment)
    return {**_serialize(comment), "author": current_user.name}


@router.get("/events/{event_id}/comments", summary="Get all comments for an event")
async def get_event_comments(
    event_id: str = Path(...),
    db: AsyncSession = Depends(get_db)
):
    event_uuid = _parse_uuid(event_id, "event")
    if not await db.get(Event, event_uuid):
        raise HTTPException(status_code=404, detail="Event not found")

    result = await db.execute(
        select(Comment)
        .where(Comment.event_id == event_uuid)
        .options(selectinload(Comment.user))
        .order_by(Comment.created_at.asc())
    )
    comments = result.scalars().all()
    return {"event_id": event_id, "comments": [_serialize(c) for c in comments], "total": len(comments)}


@router.post(
    "/articles/{article_id}/comments",
    status_code=status.HTTP_201_CREATED,
    summary="Post a comment on a newsroom article"
)
async def create_article_comment(
    article_id: str = Path(...),
    payload: CreateCommentRequest = ...,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    article_uuid = _parse_uuid(article_id, "article")
    await _load_commentable_article(db, article_uuid, current_user)

    comment = Comment(content=payload.content, article_id=article_uuid, user_id=current_user.id)
    db.add(comment)
    await db.commit()
    await db.refresh(comment)
    return {**_serialize(comment), "author": current_user.name}


@router.get("/articles/{article_id}/comments", summary="Get all comments for a newsroom article")
async def get_article_comments(
    article_id: str = Path(...),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    article_uuid = _parse_uuid(article_id, "article")
    await _load_commentable_article(db, article_uuid, current_user)

    result = await db.execute(
        select(Comment)
        .where(Comment.article_id == article_uuid)
        .options(selectinload(Comment.user))
        .order_by(Comment.created_at.asc())
    )
    comments = result.scalars().all()
    return {"article_id": article_id, "comments": [_serialize(c) for c in comments], "total": len(comments)}


@router.put("/comments/{comment_id}", summary="Edit a comment (author only)")
async def update_comment(
    comment_id: str = Path(...),
    payload: CreateCommentRequest = ...,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    comment_uuid = _parse_uuid(comment_id, "comment")
    comment = await db.get(Comment, comment_uuid)
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    if comment.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only edit your own comments")

    comment.content = payload.content
    await db.commit()
    await db.refresh(comment)
    return _serialize(comment)


@router.delete("/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a comment")
async def delete_comment(
    comment_id: str = Path(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    comment_uuid = _parse_uuid(comment_id, "comment")
    comment = await db.get(Comment, comment_uuid)
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    role = current_user.role.value if hasattr(current_user.role, "value") else current_user.role
    if comment.user_id != current_user.id and role != UserRole.ADMIN.value:
        raise HTTPException(status_code=403, detail="You can only delete your own comments")

    await db.delete(comment)
    await db.commit()
    return None
