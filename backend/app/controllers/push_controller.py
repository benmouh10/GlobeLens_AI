"""
GlobeLens AI — PushController

GET    /push/vapid-public-key   public key for the browser subscription
POST   /push/subscribe          register this browser's push endpoint (auth)
DELETE /push/unsubscribe        remove a push endpoint (auth)
GET    /push/preferences        read notification opt-ins (auth)
PUT    /push/preferences        update notification opt-ins (auth)
POST   /push/test               send a test notification to the caller (auth)

All mutating routes are per-user and require authentication. A subscription is
keyed by its globally unique endpoint, so re-subscribing the same browser while
logged in as a different user reassigns it rather than duplicating.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.controllers.auth_controller import get_current_user
from app.core.database import get_db
from app.entities.models import PushSubscription, User
from app.services import push_service

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Schemas ────────────────────────────────────────────────────────────────────
class PushKeys(BaseModel):
    p256dh: str = Field(..., min_length=1)
    auth: str = Field(..., min_length=1)


class SubscribeBody(BaseModel):
    endpoint: str = Field(..., min_length=1)
    keys: PushKeys


class UnsubscribeBody(BaseModel):
    endpoint: str = Field(..., min_length=1)


class PreferenceOut(BaseModel):
    breaking_news: bool
    followed_events: bool
    daily_briefing: bool
    briefing_hour_utc: int
    timezone: str


class PreferenceUpdate(BaseModel):
    breaking_news: Optional[bool] = None
    followed_events: Optional[bool] = None
    daily_briefing: Optional[bool] = None
    briefing_hour_utc: Optional[int] = Field(None, ge=0, le=23)
    timezone: Optional[str] = Field(None, max_length=64)


class StatusResponse(BaseModel):
    subscribed: bool
    endpoint: str


class DeliveryResponse(BaseModel):
    sent: int
    failed: int
    pruned: int
    skipped: int


# ── Public: VAPID key ──────────────────────────────────────────────────────────
@router.get("/vapid-public-key", summary="Get the VAPID public key for push")
async def vapid_public_key():
    """Expose the application server key the browser needs to subscribe.

    `enabled` is false until keys are configured, so the client can hide or
    disable the notification controls rather than fail at subscribe time.
    """
    return {
        "public_key": push_service.settings.VAPID_PUBLIC_KEY,
        "enabled": push_service.is_configured(),
    }


# ── Auth: subscribe / unsubscribe ──────────────────────────────────────────────
@router.post(
    "/subscribe",
    response_model=StatusResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a browser push subscription",
)
async def subscribe(
    body: SubscribeBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    existing = (
        await db.execute(
            select(PushSubscription).where(PushSubscription.endpoint == body.endpoint)
        )
    ).scalar_one_or_none()

    if existing is None:
        existing = PushSubscription(
            user_id=current_user.id,
            endpoint=body.endpoint,
            p256dh=body.keys.p256dh,
            auth=body.keys.auth,
        )
        db.add(existing)
    else:
        # Same endpoint re-subscribed (key rotation or account switch).
        existing.user_id = current_user.id
        existing.p256dh = body.keys.p256dh
        existing.auth = body.keys.auth
    await db.commit()
    return StatusResponse(subscribed=True, endpoint=body.endpoint)


@router.delete(
    "/unsubscribe",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a browser push subscription",
)
async def unsubscribe(
    body: UnsubscribeBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    sub = (
        await db.execute(
            select(PushSubscription).where(
                PushSubscription.endpoint == body.endpoint,
                PushSubscription.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if sub is not None:
        await db.delete(sub)
        await db.commit()
    return None


# ── Auth: preferences ──────────────────────────────────────────────────────────
@router.get("/preferences", response_model=PreferenceOut, summary="Get push preferences")
async def get_preferences(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    pref = await push_service.get_or_create_preferences(db, current_user.id)
    await db.commit()
    return PreferenceOut(
        breaking_news=pref.breaking_news,
        followed_events=pref.followed_events,
        daily_briefing=pref.daily_briefing,
        briefing_hour_utc=pref.briefing_hour_utc,
        timezone=pref.timezone,
    )


@router.put("/preferences", response_model=PreferenceOut, summary="Update push preferences")
async def update_preferences(
    body: PreferenceUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    pref = await push_service.get_or_create_preferences(db, current_user.id)
    for field, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(pref, field, value)
    await db.commit()
    return PreferenceOut(
        breaking_news=pref.breaking_news,
        followed_events=pref.followed_events,
        daily_briefing=pref.daily_briefing,
        briefing_hour_utc=pref.briefing_hour_utc,
        timezone=pref.timezone,
    )


# ── Auth: test delivery ────────────────────────────────────────────────────────
@router.post(
    "/test",
    response_model=DeliveryResponse,
    summary="Send a test push to the caller's devices",
)
async def send_test(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not push_service.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Web Push is not configured (missing VAPID keys).",
        )
    payload = {
        "title": "GlobeLens test alert",
        "body": "Push notifications are working on this device.",
        "url": f"{push_service.settings.FRONTEND_URL}/",
        "tag": "globe-lens-test",
        "data": {},
    }
    # Bypass the category opt-in for an explicit test the user requested.
    pref = await push_service.get_or_create_preferences(db, current_user.id)
    had = pref.breaking_news
    pref.breaking_news = True
    try:
        result = await push_service.notify_user(
            db, current_user.id, payload, "breaking_news"
        )
    finally:
        if not had:
            pref.breaking_news = False
            await db.commit()
    return DeliveryResponse(**result)
