"""
GlobeLens AI — InsightsController

Aggregated, non-personal analytics that answer "what is the world paying
attention to right now":

    GET /insights/trends   Topics gaining coverage over a rolling window

Deliberately separate from /admin/stats, which reports pipeline health and
whole-database distributions to operators. These figures are derived from
published events only, and every response states the exact window it compared
so a client cannot present a stale comparison as current.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.controllers.auth_controller import get_current_user
from app.core.database import get_db
from app.entities.models import Event, User
from app.services.insights_service import build_topic_trends

router = APIRouter()


@router.get("/trends", summary="Topics gaining coverage")
async def get_topic_trends(
    window_days: int = Query(7, ge=1, le=90, description="Length of each comparison window in days"),
    limit: int = Query(6, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Compare how much coverage each topic received in the most recent window
    against the window immediately before it.

    A topic with no events in the previous window is reported as new rather
    than as an infinite percentage increase. Counts cover PROCESSED events
    only, so a half-ingested draft cannot be read as breaking coverage.
    """
    now = datetime.now(timezone.utc)
    current_start = now - timedelta(days=window_days)
    previous_start = current_start - timedelta(days=window_days)

    async def topic_counts(start: datetime, end: datetime) -> dict[str, int]:
        query = (
            select(Event.topic, func.count(Event.id))
            .where(
                Event.status == "PROCESSED",
                Event.topic.isnot(None),
                Event.created_at >= start,
                Event.created_at < end,
            )
            .group_by(Event.topic)
        )
        return {topic: int(count) for topic, count in (await db.execute(query)).all()}

    current = await topic_counts(current_start, now)
    previous = await topic_counts(previous_start, current_start)

    topics = build_topic_trends(current, previous, limit)

    return {
        "window_days": window_days,
        "current_start": current_start.isoformat(),
        "current_end": now.isoformat(),
        "previous_start": previous_start.isoformat(),
        "previous_end": current_start.isoformat(),
        "topics": topics,
    }
