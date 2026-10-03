"""
GlobeLens AI — NewsletterController

POST /newsletter/subscribe     register / update an email (double opt-in)
GET  /newsletter/confirm       confirm an address via emailed token
GET  /newsletter/unsubscribe   deactivate via emailed token
POST /newsletter/send-digest   (ADMIN) build and send a digest now
GET  /newsletter/subscribers   (ADMIN) list subscribers

Subscription is anonymous: the caller only needs an email, so the confirm and
unsubscribe endpoints authenticate by opaque token rather than a session. The
two dispatch/admin endpoints are guarded by require_admin — send-digest sends
real mail to the whole list, so it must never be callable anonymously.
"""
import logging
import secrets
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.controllers.admin_controller import require_admin
from app.core.database import get_db
from app.entities.models import NewsletterSubscriber, User
from app.services.email_service import EmailDeliveryError
from app.services.newsletter_service import send_confirmation_email, send_digest

logger = logging.getLogger(__name__)

router = APIRouter()

VALID_FREQUENCIES = {"daily", "weekly"}


# ── Schemas ────────────────────────────────────────────────────────────────────
class SubscribeRequest(BaseModel):
    email: EmailStr
    interests: List[str] = []
    frequency: str = "daily"  # daily or weekly

    @field_validator("frequency")
    @classmethod
    def _check_frequency(cls, v: str) -> str:
        v = (v or "daily").lower().strip()
        if v not in VALID_FREQUENCIES:
            raise ValueError("frequency must be 'daily' or 'weekly'")
        return v


class SubscribeResponse(BaseModel):
    email: str
    frequency: str
    confirmed: bool
    confirmation_email_sent: bool
    message: str


class DigestResponse(BaseModel):
    frequency: str
    matched: int
    sent: int
    failed: int
    skipped: int


class SubscriberOut(BaseModel):
    id: str
    email: str
    frequency: str
    interests: List[str] = []
    is_active: bool
    is_confirmed: bool
    created_at: Optional[datetime] = None
    confirmed_at: Optional[datetime] = None
    last_sent_at: Optional[datetime] = None


class SubscriberListResponse(BaseModel):
    total: int
    subscribers: List[SubscriberOut]


# ── Helpers ────────────────────────────────────────────────────────────────────
def _new_token() -> str:
    return secrets.token_urlsafe(32)


def _render_message_page(title: str, body: str, ok: bool = True) -> HTMLResponse:
    accent = "#5eead4" if ok else "#f43f5e"
    html = f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
  body{{margin:0;background:#051424;color:#e2e8f0;
       font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
       display:flex;min-height:100vh;align-items:center;justify-content:center}}
  .card{{max-width:480px;margin:24px;padding:36px;background:#122131;
        border:1px solid #45464d;border-radius:16px;text-align:center}}
  .dot{{width:12px;height:12px;border-radius:50%;background:{accent};
       display:inline-block;margin-bottom:16px}}
  h1{{font-size:20px;margin:0 0 12px}}
  p{{color:#94a3b8;font-size:14px;line-height:1.6;margin:0}}
  a{{color:#22d3ee}}
</style></head>
<body><div class="card"><span class="dot"></span><h1>{title}</h1><p>{body}</p></div>
</body></html>"""
    return HTMLResponse(content=html, status_code=200 if ok else 400)


# ── Public: subscribe (double opt-in) ──────────────────────────────────────────
@router.post(
    "/subscribe",
    response_model=SubscribeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Subscribe to the GlobeLens AI newsletter",
)
async def subscribe_newsletter(
    req: SubscribeRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create or update a subscription, then send a confirmation email.

    Re-subscribing an already-confirmed, active address is a no-op (200-style
    result surfaced in the body) rather than minting a second row, since email
    is unique.
    """
    email = req.email.strip().lower()
    subscriber = (
        await db.execute(
            select(NewsletterSubscriber).where(NewsletterSubscriber.email == email)
        )
    ).scalar_one_or_none()

    already_confirmed = bool(
        subscriber and subscriber.is_confirmed and subscriber.is_active
    )

    if subscriber is None:
        subscriber = NewsletterSubscriber(
            email=email,
            frequency=req.frequency,
            interests=req.interests,
            is_active=True,
            is_confirmed=False,
            confirm_token=_new_token(),
            unsubscribe_token=_new_token(),
        )
        db.add(subscriber)
    else:
        # Refresh preferences; a previously unsubscribed address is re-armed and
        # must confirm again (new token).
        subscriber.frequency = req.frequency
        subscriber.interests = req.interests
        if not already_confirmed:
            subscriber.is_active = True
            subscriber.is_confirmed = False
            subscriber.unsubscribed_at = None
            subscriber.confirm_token = _new_token()

    await db.flush()

    confirmation_email_sent = False
    if not already_confirmed:
        try:
            await send_confirmation_email(subscriber)
            confirmation_email_sent = True
        except EmailDeliveryError as exc:
            # The row is still valuable; the user can retry. Surface the mail
            # failure instead of pretending the email went out.
            logger.error("Confirmation email failed for %s: %s", email, exc)

    await db.commit()

    if already_confirmed:
        message = "This address is already subscribed and confirmed."
    elif confirmation_email_sent:
        message = "Check your inbox to confirm your subscription."
    else:
        message = (
            "Subscription recorded, but the confirmation email could not be sent. "
            "Please try again shortly."
        )

    return SubscribeResponse(
        email=email,
        frequency=subscriber.frequency,
        confirmed=subscriber.is_confirmed,
        confirmation_email_sent=confirmation_email_sent,
        message=message,
    )


# ── Public: confirm ────────────────────────────────────────────────────────────
@router.get("/confirm", response_class=HTMLResponse, summary="Confirm a subscription")
async def confirm_subscription(
    token: str = Query(..., description="Token from the confirmation email"),
    db: AsyncSession = Depends(get_db),
):
    subscriber = (
        await db.execute(
            select(NewsletterSubscriber).where(
                NewsletterSubscriber.confirm_token == token
            )
        )
    ).scalar_one_or_none()

    if subscriber is None:
        return _render_message_page(
            "Invalid or expired link",
            "This confirmation link is not valid. You can subscribe again from the site.",
            ok=False,
        )

    subscriber.is_confirmed = True
    subscriber.is_active = True
    subscriber.confirmed_at = datetime.now(timezone.utc)
    subscriber.confirm_token = None
    await db.commit()

    return _render_message_page(
        "Subscription confirmed",
        f"You will receive the GlobeLens {subscriber.frequency} brief. "
        "You can close this tab.",
    )


# ── Public: unsubscribe ────────────────────────────────────────────────────────
@router.get("/unsubscribe", response_class=HTMLResponse, summary="Unsubscribe")
async def unsubscribe(
    token: str = Query(..., description="Token from the email footer"),
    db: AsyncSession = Depends(get_db),
):
    subscriber = (
        await db.execute(
            select(NewsletterSubscriber).where(
                NewsletterSubscriber.unsubscribe_token == token
            )
        )
    ).scalar_one_or_none()

    if subscriber is None:
        return _render_message_page(
            "Invalid link",
            "This unsubscribe link is not valid.",
            ok=False,
        )

    subscriber.is_active = False
    subscriber.unsubscribed_at = datetime.now(timezone.utc)
    await db.commit()

    return _render_message_page(
        "You are unsubscribed",
        "You will no longer receive the GlobeLens newsletter. "
        "You can subscribe again at any time.",
    )


# ── Admin: trigger a digest now ────────────────────────────────────────────────
@router.post(
    "/send-digest",
    response_model=DigestResponse,
    summary="Admin: build and send the email digest now",
)
async def send_digest_now(
    frequency: str = Query("daily", description="daily or weekly"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Send the digest synchronously and report delivery counters."""
    frequency = (frequency or "daily").lower().strip()
    if frequency not in VALID_FREQUENCIES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="frequency must be 'daily' or 'weekly'",
        )
    result = await send_digest(db, frequency)
    return DigestResponse(**result)


# ── Admin: list subscribers ────────────────────────────────────────────────────
@router.get(
    "/subscribers",
    response_model=SubscriberListResponse,
    summary="Admin: list newsletter subscribers",
)
async def list_subscribers(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    rows = list(
        (
            await db.execute(
                select(NewsletterSubscriber).order_by(
                    NewsletterSubscriber.created_at.desc()
                )
            )
        ).scalars().all()
    )
    return SubscriberListResponse(
        total=len(rows),
        subscribers=[
            SubscriberOut(
                id=str(s.id),
                email=s.email,
                frequency=s.frequency,
                interests=s.interests or [],
                is_active=s.is_active,
                is_confirmed=s.is_confirmed,
                created_at=s.created_at,
                confirmed_at=s.confirmed_at,
                last_sent_at=s.last_sent_at,
            )
            for s in rows
        ],
    )
