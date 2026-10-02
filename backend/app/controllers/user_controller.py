"""
GlobeLens AI — UserController
GET /users/{id} | PUT /users/{id} | DELETE /users/{id}
"""
from fastapi import APIRouter, Path, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.controllers.auth_controller import get_current_user
from app.entities.models import User, Bookmark, Event, Article, Source

router = APIRouter()


class UpdateUserRequest(BaseModel):
    name: Optional[str] = None
    preferred_topics: Optional[List[str]] = None
    preferred_countries: Optional[List[str]] = None


def _parse_uuid(raw: str) -> uuid.UUID:
    """Path segments arrive as strings; a malformed id is a client error."""
    try:
        return uuid.UUID(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user UUID")


def _require_self_or_admin(current_user: User, target_id: uuid.UUID) -> None:
    """
    A user may only touch their own account unless they are an admin.

    Every route in this controller goes through here. The profile, update and
    delete endpoints previously had no authorisation whatsoever.
    """
    role = current_user.role.value if hasattr(current_user.role, "value") else current_user.role
    if role != "ADMIN" and current_user.id != target_id:
        raise HTTPException(status_code=403, detail="Access denied")


@router.get("/{user_id}", summary="Get user profile by ID")
async def get_user(
    user_id: str = Path(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Return the stored profile.

    This used to answer with a hardcoded {"name": "Placeholder User"} and no
    authorisation at all, so any caller could read any account by id and every
    response was fiction.
    """
    user_uuid = _parse_uuid(user_id)
    _require_self_or_admin(current_user, user_uuid)

    user = await db.get(User, user_uuid)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "id": str(user.id),
        "name": user.name,
        "email": user.email,
        "role": user.role.value if hasattr(user.role, "value") else user.role,
        "preferred_topics": list(user.preferred_topics or []),
        "preferred_countries": list(user.preferred_countries or []),
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


@router.put("/{user_id}", summary="Update user profile and preferences")
async def update_user(
    user_id: str = Path(...),
    payload: UpdateUserRequest = ...,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Persist the editable profile fields.

    Previously returned "User updated" without writing anything, so the API
    confirmed a save that had not happened.
    """
    user_uuid = _parse_uuid(user_id)
    _require_self_or_admin(current_user, user_uuid)

    user = await db.get(User, user_uuid)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if payload.name is not None:
        cleaned = payload.name.strip()
        if not cleaned:
            raise HTTPException(status_code=400, detail="Name cannot be empty")
        user.name = cleaned
    if payload.preferred_topics is not None:
        user.preferred_topics = payload.preferred_topics
    if payload.preferred_countries is not None:
        user.preferred_countries = payload.preferred_countries

    await db.commit()
    await db.refresh(user)

    return {
        "message": "User updated",
        "id": str(user.id),
        "name": user.name,
        "preferred_topics": list(user.preferred_topics or []),
        "preferred_countries": list(user.preferred_countries or []),
    }


@router.delete("/{user_id}", status_code=204, summary="Delete user account")
async def delete_user(
    user_id: str = Path(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Delete the account. Bookmarks, comments and fact-check requests cascade.

    This used to return 204 without deleting anything, reporting a successful
    account deletion while leaving every trace of the user in place.
    """
    user_uuid = _parse_uuid(user_id)
    _require_self_or_admin(current_user, user_uuid)

    user = await db.get(User, user_uuid)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    await db.delete(user)
    await db.commit()
    return None

class BookmarkRequest(BaseModel):
    event_id: str

@router.get("/{user_id}/bookmarks", summary="Get user bookmarks")
async def get_bookmarks(
    user_id: str = Path(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user UUID")
        
    if current_user.role != "ADMIN" and current_user.id != user_uuid:
        raise HTTPException(status_code=403, detail="Access denied")
        
    query = select(Bookmark).where(Bookmark.user_id == user_uuid)
    result = await db.execute(query)
    bookmarks = result.scalars().all()
    
    return {"bookmarks": [{"event_id": str(b.event_id), "created_at": b.created_at.isoformat()} for b in bookmarks]}


@router.post("/{user_id}/bookmarks", summary="Add a bookmark")
async def add_bookmark(
    payload: BookmarkRequest,
    user_id: str = Path(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        user_uuid = uuid.UUID(user_id)
        event_uuid = uuid.UUID(payload.event_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")
        
    if current_user.role != "ADMIN" and current_user.id != user_uuid:
        raise HTTPException(status_code=403, detail="Access denied")
        
    # Check if event exists
    event = await db.get(Event, event_uuid)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
        
    # Check if already bookmarked
    query = select(Bookmark).where(Bookmark.user_id == user_uuid, Bookmark.event_id == event_uuid)
    result = await db.execute(query)
    if result.scalars().first():
        return {"message": "Already bookmarked"}
        
    bookmark = Bookmark(user_id=user_uuid, event_id=event_uuid)
    db.add(bookmark)
    await db.commit()
    
    return {"message": "Bookmark added"}


@router.delete("/{user_id}/bookmarks/{event_id}", summary="Remove a bookmark")
async def remove_bookmark(
    user_id: str = Path(...),
    event_id: str = Path(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        user_uuid = uuid.UUID(user_id)
        event_uuid = uuid.UUID(event_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")
        
    if current_user.role != "ADMIN" and current_user.id != user_uuid:
        raise HTTPException(status_code=403, detail="Access denied")
        
    query = select(Bookmark).where(Bookmark.user_id == user_uuid, Bookmark.event_id == event_uuid)
    result = await db.execute(query)
    bookmark = result.scalars().first()
    
    if not bookmark:
        raise HTTPException(status_code=404, detail="Bookmark not found")
        
    await db.delete(bookmark)
    await db.commit()
    
    return {"message": "Bookmark removed"}


@router.get("/{user_id}/reading-stats", summary="Get user engagement stats")
async def get_reading_stats(
    user_id: str = Path(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Reading stats computed from real data.

    This previously returned invented numbers (142 events read, 1250 points,
    a fixed 40/45/15 bias split). Showing a user fabricated figures about their
    own reading history is the one thing this product must not do, so there is
    no fallback to canned values: with nothing recorded the counts are zero.
    """
    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user UUID")

    if current_user.role != "ADMIN" and current_user.id != user_uuid:
        raise HTTPException(status_code=403, detail="Access denied")

    # One row per (saved event, source lean). Selecting event_id, not
    # created_at: two events saved in the same transaction share a timestamp,
    # so counting distinct timestamps undercounts saved events.
    rows = (
        await db.execute(
            select(Bookmark.event_id, Source.bias_lean)
            .join(Event, Event.id == Bookmark.event_id)
            .join(Article, Article.event_id == Event.id)
            .join(Source, Source.id == Article.source_id)
            .where(Bookmark.user_id == user_uuid)
            .distinct(Bookmark.event_id, Source.bias_lean)
        )
    ).all()

    if not rows:
        return {
            "user_id": user_id,
            "total_events_saved": 0,
            "bias_distribution": {},
            "gamification_message": None,
        }

    total = len({r[0] for r in rows})

    # An event saved from several outlets contributes once to each lean it
    # draws on, so leans are counted as coverage of saved events, not as a
    # partition of them.
    leans_per_event: dict[object, set[str]] = {}
    for event_id, lean in rows:
        if lean is None:
            continue
        name = lean.name if hasattr(lean, "name") else str(lean)
        leans_per_event.setdefault(event_id, set()).add(name)

    distribution: dict[str, int] = {}
    for leans in leans_per_event.values():
        for name in leans:
            distribution[name] = distribution.get(name, 0) + 1
    message = None
    if total >= 5 and distribution:
        # Name the least-covered lean rather than asserting a conclusion about
        # the reader. A single saved article proves nothing about their habits.
        least = min(distribution.items(), key=lambda kv: kv[1])
        share = round((least[1] / total) * 100)
        if share < 20 and len(distribution) > 1:
            message = (
                f"{share}% of your saved events came from "
                f"{least[0].replace('_', ' ').lower()} sources. "
                f"Sources further from that lean are in the source list."
            )

    return {
        "user_id": user_id,
        "total_events_saved": total,
        "bias_distribution": distribution,
        "gamification_message": message,
    }

