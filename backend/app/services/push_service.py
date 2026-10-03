"""
GlobeLens AI — Web Push Service

Sends notifications to a user's registered browser subscriptions using the
Web Push protocol (VAPID-signed, payload-encrypted). Delivery is best-effort:
a subscription that the push service reports as gone (404/410) is pruned
immediately so the table does not accumulate dead endpoints.

pywebpush is imported lazily: importing this module must not fail on a machine
where the dependency or VAPID keys are absent, since the controller reports
`enabled: false` in that case rather than crashing at startup.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.entities.models import PushPreference, PushSubscription

logger = logging.getLogger(__name__)

# Categories understood by the service and the preference table.
CATEGORIES = ("breaking_news", "followed_events", "daily_briefing")


class PushNotConfigured(RuntimeError):
    """Raised when VAPID keys are missing, so no push can be signed."""


def is_configured() -> bool:
    return bool(settings.VAPID_PUBLIC_KEY and settings.VAPID_PRIVATE_KEY)


async def get_or_create_preferences(db: AsyncSession, user_id) -> PushPreference:
    """Return the user's preferences, creating defaults on first access."""
    pref = (
        await db.execute(
            select(PushPreference).where(PushPreference.user_id == user_id)
        )
    ).scalar_one_or_none()
    if pref is None:
        pref = PushPreference(user_id=user_id)
        db.add(pref)
        await db.flush()
    return pref


async def send_to_subscription(subscription: PushSubscription, payload: dict) -> bool:
    """Deliver one payload. Returns False and marks the row for pruning on 404/410."""
    if not is_configured():
        raise PushNotConfigured(
            "VAPID keys are not set; cannot sign push messages."
        )

    from pywebpush import WebPushException, webpush

    subscription_info = {
        "endpoint": subscription.endpoint,
        "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
    }
    try:
        webpush(
            subscription_info=subscription_info,
            data=json.dumps(payload),
            vapid_private_key=settings.VAPID_PRIVATE_KEY,
            vapid_claims={"sub": settings.VAPID_SUBJECT},
            # A non-zero TTL is required: WNS returns 400 for ttl=0.
            ttl=settings.PUSH_TTL_SECONDS,
        )
    except WebPushException as exc:
        status = getattr(exc.response, "status_code", None)
        if status in (404, 410):
            logger.info("Push endpoint gone (%s), pruning: %s", status, subscription.endpoint[:60])
            return False
        # Transient or unexpected: log and keep the row for a later retry.
        logger.warning("Push delivery failed (%s): %s", status, exc)
        raise
    return True


async def notify_user(
    db: AsyncSession,
    user_id,
    payload: dict,
    category: str,
) -> dict:
    """Send a payload to every subscription of a user, honoring preferences.

    Returns counters so callers (and the /push/test endpoint) can report what
    actually happened. Prunes endpoints the push service rejected.
    """
    if category not in CATEGORIES:
        raise ValueError(f"unknown push category: {category}")

    pref = await get_or_create_preferences(db, user_id)
    if not bool(getattr(pref, category, False)):
        return {"sent": 0, "failed": 0, "pruned": 0, "skipped": 1}

    subscriptions: Iterable[PushSubscription] = (
        await db.execute(
            select(PushSubscription).where(PushSubscription.user_id == user_id)
        )
    ).scalars().all()

    sent = failed = pruned = 0
    now = datetime.now(timezone.utc)
    for sub in list(subscriptions):
        try:
            ok = await send_to_subscription(sub, payload)
            if ok:
                sub.last_used_at = now
                sent += 1
            else:
                await db.delete(sub)
                pruned += 1
        except PushNotConfigured:
            raise
        except Exception as exc:  # noqa: BLE001 - keep other subs going
            logger.warning("Push to %s failed: %s", sub.endpoint[:60], exc)
            failed += 1

    await db.commit()
    return {"sent": sent, "failed": failed, "pruned": pruned, "skipped": 0}


async def send_daily_briefings(db: AsyncSession) -> dict:
    """Send the top-story briefing to every user who opted in.

    Runs from Celery beat at PUSH_DAILY_BRIEFING_HOUR_UTC. Reuses the same
    event selection as the email digest so the two stay consistent.
    """
    from app.services.newsletter_service import top_events

    subscribers = list(
        (
            await db.execute(
                select(PushPreference).where(PushPreference.daily_briefing.is_(True))
            )
        ).scalars().all()
    )

    users_notified = 0
    pushes_sent = 0
    events = await top_events(db, None, 3)
    if not events:
        return {"users_notified": 0, "pushes_sent": 0}
    lead = events[0]
    payload = {
        "title": "GlobeLens Daily Briefing",
        "body": lead.title,
        "url": f"{settings.FRONTEND_URL}/events/{lead.id}",
        "tag": "globe-lens-daily",
        "data": {"eventId": str(lead.id)},
    }
    for pref in subscribers:
        result = await notify_user(db, pref.user_id, payload, "daily_briefing")
        pushes_sent += result["sent"]
        if result["sent"]:
            users_notified += 1

    return {"users_notified": users_notified, "pushes_sent": pushes_sent}
