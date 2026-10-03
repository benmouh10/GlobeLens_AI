"""
GlobeLens AI — EventController
GET  /events | /events/{id} | /events/trending | /events/latest
GET  /events/country/{country} | /events/topic/{topic} | /events/map
POST /events/{id}/follow
"""
from fastapi import APIRouter, Path, Query, Depends, HTTPException, status
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.rbac import require_role
from app.entities.models import UserRole

router = APIRouter()


@router.get("", summary="List all events (paginated)")
async def list_events(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    topic: Optional[str] = Query(None, description="Filter by topic"),
    country: Optional[str] = Query(None, description="Filter by country"),
    bias_lean: Optional[str] = Query(None, description="Filter by bias lean (LEFT, RIGHT, etc)"),
    min_score: Optional[float] = Query(None, description="Minimum importance score"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    db: AsyncSession = Depends(get_db)
):
    from sqlalchemy import select, func
    from sqlalchemy.orm import selectinload
    from app.entities.models import Event, BiasLean
    
    offset = (page - 1) * limit
    
    base_query = select(Event).where(Event.status == "PROCESSED")
    
    if topic:
        base_query = base_query.where(Event.topic.ilike(topic))
    if country:
        base_query = base_query.where(Event.country.ilike(country))
    if min_score is not None:
        base_query = base_query.where(Event.importance_score >= min_score)
    if bias_lean:
        try:
            lean_enum = BiasLean[bias_lean.upper()]
            base_query = base_query.where(Event.bias_lean == lean_enum)
        except KeyError:
            pass
            
    from datetime import datetime
    if start_date:
        try:
            dt = datetime.fromisoformat(start_date)
            base_query = base_query.where(Event.created_at >= dt)
        except ValueError:
            pass
    if end_date:
        try:
            dt = datetime.fromisoformat(end_date)
            base_query = base_query.where(Event.created_at <= dt)
        except ValueError:
            pass
            
    # Total count
    total_query = select(func.count()).select_from(base_query.subquery())
    total_count = await db.scalar(total_query) or 0
    
    # Paginated PROCESSED events
    events_query = (
        base_query
        .options(selectinload(Event.articles))
        .order_by(Event.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(events_query)
    events = result.scalars().all()
    
    event_list = []
    for evt in events:
        event_list.append({
            "id": str(evt.id),
            "title": evt.title,
            "summary": evt.summary or "",
            "topic": evt.topic or "WORLD",
            "country": evt.country or "Unknown",
            "latitude": evt.latitude,
            "longitude": evt.longitude,
            "importance_score": evt.importance_score,
            "source_count": len(evt.articles),
            "bias_lean": evt.bias_lean.name if evt.bias_lean else "CENTER"
        })
        
    return {
        "events": event_list,
        "page": page,
        "limit": limit,
        "total": total_count
    }


def _serialize(evt) -> dict:
    """Common event shape used by every list endpoint.

    Kept in one place so /events, /latest, /trending, /country and /topic all
    return identical fields; they previously had four separate inline copies.
    """
    return {
        "id": str(evt.id),
        "title": evt.title,
        "summary": evt.summary or "",
        "topic": evt.topic or "WORLD",
        "country": evt.country or "Unknown",
        "latitude": evt.latitude,
        "longitude": evt.longitude,
        "importance_score": evt.importance_score,
        "source_count": len(evt.articles),
        "bias_lean": evt.bias_lean.name if evt.bias_lean else "CENTER",
        "created_at": evt.created_at.isoformat() if evt.created_at else None,
    }


@router.get("/trending", summary="Get trending events by importance score")
async def get_trending(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db)
):
    """
    Real ranking by importance score.

    Previously returned {"events": []} unconditionally, so the trending view
    looked like a working endpoint that had simply found nothing.
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from app.entities.models import Event

    result = await db.execute(
        select(Event)
        .where(Event.status == "PROCESSED")
        .options(selectinload(Event.articles))
        .order_by(Event.importance_score.desc().nullslast(), Event.created_at.desc())
        .limit(limit)
    )
    events = result.scalars().all()
    return {"events": [_serialize(e) for e in events], "limit": limit}


@router.get("/latest", summary="Get latest events ordered by creation date")
async def get_latest(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db)
):
    """Previously returned {"events": []} unconditionally."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from app.entities.models import Event

    result = await db.execute(
        select(Event)
        .where(Event.status == "PROCESSED")
        .options(selectinload(Event.articles))
        .order_by(Event.created_at.desc())
        .limit(limit)
    )
    events = result.scalars().all()
    return {"events": [_serialize(e) for e in events], "limit": limit}


@router.get("/map", summary="Get events with geolocation data for map view")
async def get_map_events(db: AsyncSession = Depends(get_db)):
    """Returns lat/lon + metadata for the map interface."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from app.entities.models import Event

    result = await db.execute(
        select(Event)
        .where(
            Event.status == "PROCESSED",
            Event.latitude.isnot(None),
            Event.longitude.isnot(None)
        )
        .options(selectinload(Event.articles))
    )
    events = result.scalars().all()

    event_list = [_serialize(evt) for evt in events]

    return {"events": event_list}


@router.get("/country/{country}", summary="Filter events by country")
async def get_events_by_country(
    country: str = Path(..., description="Country name"),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db)
):
    """
    Real country filter.

    Previously answered {"country": ..., "events": []} for every input, so
    /country/France reported zero French events while six existed in the DB.
    Matching is case-insensitive and anchored so "Iran" cannot match "Iranian".
    """
    from sqlalchemy import select, func
    from sqlalchemy.orm import selectinload
    from app.entities.models import Event

    needle = country.strip()
    if not needle:
        raise HTTPException(status_code=400, detail="Country must not be empty")

    result = await db.execute(
        select(Event)
        .where(Event.status == "PROCESSED", func.lower(Event.country) == needle.lower())
        .options(selectinload(Event.articles))
        .order_by(Event.importance_score.desc().nullslast(), Event.created_at.desc())
        .limit(limit)
    )
    events = result.scalars().all()
    return {"country": country, "events": [_serialize(e) for e in events], "total": len(events)}


@router.get("/topic/{topic}", summary="Filter events by topic")
async def get_events_by_topic(
    topic: str = Path(...),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db)
):
    """
    Real topic filter.

    Previously always empty. Topics are stored upper-case ("WORLD", "POLITICS"),
    so the comparison is case-insensitive to keep /topic/World working.
    """
    from sqlalchemy import select, func
    from sqlalchemy.orm import selectinload
    from app.entities.models import Event

    needle = topic.strip()
    if not needle:
        raise HTTPException(status_code=400, detail="Topic must not be empty")

    result = await db.execute(
        select(Event)
        .where(Event.status == "PROCESSED", func.lower(Event.topic) == needle.lower())
        .options(selectinload(Event.articles))
        .order_by(Event.importance_score.desc().nullslast(), Event.created_at.desc())
        .limit(limit)
    )
    events = result.scalars().all()
    return {"topic": topic, "events": [_serialize(e) for e in events], "total": len(events)}


@router.get("/{event_id}", summary="Get a single event by ID")
async def get_event(
    event_id: str = Path(..., description="Event UUID"),
    db: AsyncSession = Depends(get_db)
):
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from app.entities.models import Event, Article
    from fastapi import HTTPException
    import uuid
    
    try:
        event_uuid = uuid.UUID(event_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid event UUID format")
        
    query = (
        select(Event)
        .where(Event.id == event_uuid)
        .options(
            selectinload(Event.articles).selectinload(Article.source),
            selectinload(Event.contradictions),
        )
    )
    result = await db.execute(query)
    evt = result.scalars().first()
    
    if not evt:
        raise HTTPException(status_code=404, detail="Event not found")
        
    articles_list = []
    # Enrichment only sends articles that have a body, and the LLM cites by
    # position within that filtered list. Numbering here with the same filter
    # keeps [N] pointing at the right article; an article with no content was
    # never shown to the model, so it gets no number and cannot be cited.
    citation_index = 0
    for art in evt.articles:
        has_body = bool(art.content and art.content.strip())
        if has_body:
            citation_index += 1
        articles_list.append({
            "id": str(art.id),
            "citation_index": citation_index if has_body else None,
            "title": art.title,
            "content": art.content or "",
            "url": art.url,
            "published_at": art.published_at.isoformat() if art.published_at else None,
            "source": {
                "name": art.source.name if art.source else "Unknown",
                "credibility_score": art.source.credibility_score if art.source else 0.5,
                "bias_lean": art.source.bias_lean.name if art.source and art.source.bias_lean else "CENTER"
            }
        })
        
    # Candidate conflicts surfaced for review. Neither side is marked
    # correct: deciding which outlet is wrong is a judgement this system does
    # not make, so both claims are returned verbatim with the reason they
    # looked incompatible.
    contradictions = [
        {
            "nature": c.nature,
            "detail": c.detail,
            "claim_a": {"text": c.claim_a_text, "source": c.claim_a_source},
            "claim_b": {"text": c.claim_b_text, "source": c.claim_b_source},
        }
        for c in evt.contradictions
    ]

    return {
        "id": str(evt.id),
        "title": evt.title,
        "summary": evt.summary or "",
        "topic": evt.topic or "WORLD",
        "country": evt.country or "Unknown",
        "latitude": evt.latitude,
        "longitude": evt.longitude,
        "importance_score": evt.importance_score,
        "bias_lean": evt.bias_lean.name if evt.bias_lean else "CENTER",
        "status": evt.status,
        "created_at": evt.created_at.isoformat() if evt.created_at else None,
        "updated_at": evt.updated_at.isoformat() if evt.updated_at else None,
        "has_contradictions": len(contradictions) > 0,
        "contradictions": contradictions,
        "articles": articles_list
    }


@router.get("/{event_id}/related", summary="Get related events for timeline")
async def get_related_events(
    event_id: str = Path(..., description="Event UUID"),
    db: AsyncSession = Depends(get_db)
):
    from sqlalchemy import select
    from app.entities.models import Event
    import uuid
    
    try:
        event_uuid = uuid.UUID(event_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid event UUID format")
        
    evt = await db.get(Event, event_uuid)
    if not evt:
        raise HTTPException(status_code=404, detail="Event not found")
        
    query = (
        select(Event)
        .where(
            Event.id != event_uuid,
            Event.status == "PROCESSED",
            Event.topic == evt.topic
        )
        .order_by(Event.created_at.desc())
        .limit(5)
    )
    result = await db.execute(query)
    related = result.scalars().all()
    
    event_list = []
    for r in related:
        event_list.append({
            "id": str(r.id),
            "title": r.title,
            "topic": r.topic,
            "created_at": r.created_at.isoformat() if r.created_at else None
        })
        
    return {"events": event_list}


@router.get("/{event_id}/fact-check", summary="Run fact-check analysis on an event")
async def check_event_facts(
    event_id: str = Path(..., description="Event UUID"),
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_role(UserRole.AUTH_USER)),
):
    from app.entities.models import Event
    from app.services.llm_service import LLMService
    import uuid
    
    try:
        event_uuid = uuid.UUID(event_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid event UUID format")
        
    evt = await db.get(Event, event_uuid)
    if not evt:
        raise HTTPException(status_code=404, detail="Event not found")
    
    if not evt.summary:
        return {"error": "No summary available to fact check"}
        
    llm_service = LLMService()
    try:
        fact_check = await llm_service.analyze_claim_credibility(evt.summary)
        return fact_check.model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/{event_id}/follow",
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    summary="Follow / subscribe to an event"
)
async def follow_event(event_id: str = Path(...)):
    """
    Not implemented.

    Previously answered 201 "Following event <id>" for every caller, including
    unauthenticated ones, and stored nothing. Nothing in the frontend calls
    this endpoint, and there is no subscription table or notification service
    behind it, so the response was a false confirmation.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Event subscriptions are not implemented: there is no "
               "subscription store or notification service.",
    )
