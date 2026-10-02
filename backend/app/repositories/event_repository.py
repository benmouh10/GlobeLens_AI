"""
GlobeLens AI — EventRepository
Async SQLAlchemy repository for Event entity — the core aggregation unit.
"""
import uuid
import math
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Union

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.entities.models import Event, Article, Embedding, EventContradiction
from app.schemas.intelligence import EventIntelligenceResponse


def _finite_coord(value: object, limit: float) -> Optional[float]:
    """
    Return a coordinate only when it is a finite number inside its valid range.

    The model can emit huge/garbage numbers (e.g. longitude 1e999 -> inf); such
    values are stored fine by Postgres but then blow up JSON serialization with
    "Out of range float values are not JSON compliant: inf", taking down the
    public /events list. Anything not finite or out of range is dropped.
    """
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or abs(value) > limit:
        return None
    return value



class EventRepository:
    """Data access layer for Event aggregation entities."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, event: Event) -> Event:
        self._session.add(event)
        await self._session.commit()
        await self._session.refresh(event)
        return event

    async def find_by_id(self, event_id: uuid.UUID) -> Optional[Event]:
        return await self._session.get(Event, event_id)

    async def find_trending(self, limit: int = 20) -> List[Event]:
        """Return events ordered by importance_score descending."""
        result = await self._session.execute(
            select(Event)
            .order_by(desc(Event.importance_score))
            .limit(limit)
        )
        return list(result.scalars().all())

    async def find_latest(self, limit: int = 20) -> List[Event]:
        """Return events ordered by creation date descending."""
        result = await self._session.execute(
            select(Event)
            .order_by(desc(Event.created_at))
            .limit(limit)
        )
        return list(result.scalars().all())

    async def find_by_country(self, country: str) -> List[Event]:
        result = await self._session.execute(
            select(Event).where(Event.country == country)
        )
        return list(result.scalars().all())

    async def find_by_topic(self, topic: str) -> List[Event]:
        result = await self._session.execute(
            select(Event).where(Event.topic == topic)
        )
        return list(result.scalars().all())

    async def find_map_events(self) -> List[Event]:
        """Return events that have valid lat/lon coordinates for map view."""
        result = await self._session.execute(
            select(Event).where(
                Event.latitude.isnot(None),
                Event.longitude.isnot(None),
            )
        )
        return list(result.scalars().all())

    async def find_recent_events(self, time_window_hours: int = 72) -> List[Event]:
        """Return all events created within the specified time window."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=time_window_hours)
        result = await self._session.execute(
            select(Event).where(Event.created_at >= cutoff)
        )
        return list(result.scalars().all())

    async def find_closest_event_by_vector(
        self, vector: List[float], threshold: float = 0.08, time_window_hours: int = 72
    ) -> Optional[uuid.UUID]:
        """
        Query the closest embedding using pgvector cosine distance operator.
        Returns the event_id of the closest article's event if within threshold and time window.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=time_window_hours)
        distance_expr = Embedding.vector.cosine_distance(vector)

        stmt = (
            select(Article.event_id, distance_expr.label("distance"))
            .join(Embedding, Article.id == Embedding.article_id)
            .join(Event, Article.event_id == Event.id)
            .where(Event.created_at >= cutoff)
            .where(distance_expr <= threshold)
            .order_by("distance")
            .limit(1)
        )
        result = await self._session.execute(stmt)
        row = result.first()
        if row:
            return row[0]
        return None

    async def get_unprocessed_events(self, limit: int = 20) -> List[Event]:
        """Retrieves events that do not have a summary generated yet or are in a draft status."""
        result = await self._session.execute(
            select(Event)
            .where(
                (Event.status == "DRAFT") |
                (Event.summary.is_(None)) |
                (Event.summary == "")
            )
            .limit(limit)
        )
        return list(result.scalars().all())

    async def replace_contradictions(
        self,
        event_id: uuid.UUID,
        rows: List[dict],
    ) -> int:
        """
        Replace the recorded contradictions for an event with ``rows``.

        Replaces rather than appends: rescanning an event whose articles have
        not changed should be a no-op, and appending would accumulate stale
        flags from earlier scans whose claims no longer exist.
        """
        async with self._session.begin_nested():
            # selectinload, not session.get: clearing the relationship would
            # lazy-load inside async context and raise MissingGreenlet.
            event = (
                await self._session.execute(
                    select(Event)
                    .where(Event.id == event_id)
                    .options(selectinload(Event.contradictions))
                )
            ).scalars().first()
            if not event:
                raise ValueError(f"Event with id {event_id} not found")

            event.contradictions.clear()
            await self._session.flush()

            for row in rows:
                event.contradictions.append(EventContradiction(**row))
            await self._session.flush()

        return len(rows)

    async def update_event_intelligence(self, event_id: uuid.UUID, intelligence_data: Union[dict, EventIntelligenceResponse]) -> None:
        """
        Saves the generated summary, topic, bias_lean, country, latitude, and longitude,
        and marks the event status as 'PROCESSED' inside an atomic transaction.
        Also marks all associated articles as 'PROCESSED'.
        """
        async with self._session.begin_nested():
            # Get event
            event = await self._session.get(Event, event_id)
            if not event:
                raise ValueError(f"Event with id {event_id} not found")
            
            # Map values
            if isinstance(intelligence_data, dict):
                summary = intelligence_data.get("summary")
                topic = intelligence_data.get("topic")
                bias_lean_val = intelligence_data.get("bias_lean")
                country = intelligence_data.get("location_country") or intelligence_data.get("country")
                latitude = intelligence_data.get("latitude")
                longitude = intelligence_data.get("longitude")
                importance_score = intelligence_data.get("importance_score")
            else:
                summary = intelligence_data.summary
                topic = intelligence_data.topic.value if hasattr(intelligence_data.topic, "value") else intelligence_data.topic
                bias_lean_val = intelligence_data.bias_lean.value if hasattr(intelligence_data.bias_lean, "value") else intelligence_data.bias_lean
                country = intelligence_data.location_country
                latitude = intelligence_data.latitude
                longitude = intelligence_data.longitude
                importance_score = intelligence_data.importance_score

            event.summary = summary
            event.topic = topic
            
            # Convert bias_lean string to Enum if provided
            if isinstance(bias_lean_val, str):
                from app.entities.models import BiasLean
                try:
                    event.bias_lean = BiasLean[bias_lean_val]
                except KeyError:
                    event.bias_lean = BiasLean(bias_lean_val)
            else:
                event.bias_lean = bias_lean_val
                
            event.country = country
            event.latitude = _finite_coord(latitude, 90.0)
            event.longitude = _finite_coord(longitude, 180.0)
            if importance_score is not None:
                event.importance_score = importance_score
                
            event.status = "PROCESSED"
            
            # Propagation: mark all articles of this event as PROCESSED
            from sqlalchemy import update
            from app.entities.models import Article, ProcessingStatus
            await self._session.execute(
                update(Article)
                .where(Article.event_id == event_id)
                .values(processing_status=ProcessingStatus.PROCESSED)
            )
            
        await self._session.commit()
