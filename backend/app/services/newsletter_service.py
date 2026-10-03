"""
GlobeLens AI — Newsletter Service

Selects the stories for a digest, renders the email, and dispatches it to the
subscribers of a given cadence. Personalisation is interest-based: a subscriber
with preferred topics/countries gets events matching those; a subscriber with
no stated interests gets the highest-importance events overall.

The service is transport-agnostic via email_service, and callable both from the
admin endpoint (synchronous send) and from a Celery task (scheduled send).
"""
import logging
from datetime import datetime, timezone
from typing import List, Optional, Sequence, Tuple

from jinja2 import Template
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.entities.models import Event, NewsletterSubscriber
from app.services.email_service import EmailDeliveryError, send_email

logger = logging.getLogger(__name__)


# ── Story selection ────────────────────────────────────────────────────────────
async def top_events(
    db: AsyncSession, interests: Optional[Sequence[str]], limit: int
) -> List[Event]:
    """Highest-importance processed events, filtered by interest when given."""
    stmt = select(Event).where(Event.status == "PROCESSED")

    cleaned = [i.strip().lower() for i in (interests or []) if i and i.strip()]
    if cleaned:
        # Substring match so a coarse interest ("climate") still matches a
        # specific topic ("CLIMATE_CHANGE") or a country ("United States" vs
        # "US" is not covered, but partial names are).
        clauses = []
        for interest in cleaned:
            pattern = f"%{interest}%"
            clauses.append(func.lower(Event.topic).like(pattern))
            clauses.append(func.lower(Event.country).like(pattern))
        stmt = stmt.where(or_(*clauses))

    stmt = stmt.order_by(
        Event.importance_score.desc().nullslast(), Event.created_at.desc()
    ).limit(limit)
    return list((await db.execute(stmt)).scalars().all())


# ── Rendering ──────────────────────────────────────────────────────────────────
_BASE_STYLE = """
  body{margin:0;padding:0;background:#eef1f7;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}
  .wrap{max-width:640px;margin:0 auto;padding:24px 12px}
  .card{background:#ffffff;border:1px solid #d8deea;border-radius:14px;overflow:hidden}
  .masthead{background:#0b1220;padding:22px 26px;color:#e8edf7}
  .masthead .brand{font-size:20px;font-weight:800;letter-spacing:.02em}
  .masthead .kicker{font-size:10px;letter-spacing:.22em;text-transform:uppercase;color:#5eead4;margin-top:6px}
  .body{padding:8px 26px 26px}
  .item{padding:18px 0;border-bottom:1px solid #eceff5}
  .item:last-child{border-bottom:0}
  .tag{display:inline-block;font-size:10px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:#4f46e5;margin-bottom:6px}
  .item h2{margin:0 0 6px;font-size:17px;line-height:1.35;color:#111827}
  .item p{margin:0 0 10px;font-size:13px;line-height:1.6;color:#4b5563}
  .cta{display:inline-block;font-size:12px;font-weight:700;color:#0b1220;text-decoration:none;border:1px solid #0b1220;border-radius:8px;padding:7px 12px}
  .foot{padding:18px 26px;background:#f6f8fc;border-top:1px solid #e3e8f1;color:#8a93a6;font-size:11px;line-height:1.6}
  .foot a{color:#4f46e5;text-decoration:none}
  .btn{display:inline-block;background:#4f46e5;color:#fff;text-decoration:none;font-weight:700;font-size:13px;padding:11px 18px;border-radius:9px}
"""

_DIGEST_TEMPLATE = Template(
    """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>{{ style }}</style></head>
<body><div class="wrap"><div class="card">
  <div class="masthead">
    <div class="brand">GlobeLens AI</div>
    <div class="kicker">{{ kicker }}</div>
  </div>
  <div class="body">
    {% if items %}
      {% for it in items %}
      <div class="item">
        <div class="tag">{{ it.topic }} &middot; {{ it.country }}</div>
        <h2>{{ it.title }}</h2>
        {% if it.summary %}<p>{{ it.summary }}</p>{% endif %}
        <a class="cta" href="{{ it.link }}">Open dossier &rarr;</a>
      </div>
      {% endfor %}
    {% else %}
      <p>No matching stories today. Update your interests to widen the brief.</p>
    {% endif %}
  </div>
  <div class="foot">
    You are receiving this because you subscribed to the GlobeLens {{ frequency }} brief.
    <br><a href="{{ unsubscribe_url }}">Unsubscribe</a> &middot;
    <a href="{{ preferences_url }}">Manage interests</a>
  </div>
</div></div></body></html>"""
)

_CONFIRM_TEMPLATE = Template(
    """<!doctype html><html><head><meta charset="utf-8"><style>{{ style }}</style></head>
<body><div class="wrap"><div class="card">
  <div class="masthead"><div class="brand">GlobeLens AI</div>
  <div class="kicker">Confirm subscription</div></div>
  <div class="body" style="padding:26px">
    <p style="font-size:14px;color:#374151;line-height:1.6">
      One click confirms your email and starts the <strong>{{ frequency }}</strong> brief.
    </p>
    <p style="margin:22px 0"><a class="btn" href="{{ confirm_url }}">Confirm subscription</a></p>
    <p style="font-size:12px;color:#8a93a6">If you did not request this, ignore this email.</p>
  </div>
</div></div></body></html>"""
)


def _summarize(event: Event, max_chars: int = 220) -> Optional[str]:
    if not event.summary:
        return None
    flat = " ".join(event.summary.split())
    return flat if len(flat) <= max_chars else flat[: max_chars - 1].rstrip() + "…"


def render_digest(
    subscriber: NewsletterSubscriber, events: Sequence[Event], frequency: str
) -> Tuple[str, str]:
    """Return (subject, html) for a subscriber's digest."""
    today = datetime.now(timezone.utc)
    if frequency == "weekly":
        subject = f"GlobeLens Weekly Deep Dive — {today:%d %b %Y}"
        kicker = "Weekly Deep Dive"
    else:
        subject = f"GlobeLens Daily Brief — {today:%d %b %Y}"
        kicker = "Daily Brief"

    items = [
        {
            "title": e.title,
            "topic": (e.topic or "WORLD").replace("_", " "),
            "country": e.country or "Global",
            "summary": _summarize(e),
            "link": f"{settings.FRONTEND_URL}/events/{e.id}",
        }
        for e in events
    ]

    html = _DIGEST_TEMPLATE.render(
        style=_BASE_STYLE,
        kicker=kicker,
        frequency=frequency,
        items=items,
        unsubscribe_url=f"{settings.API_PUBLIC_URL}/api/v1/newsletter/unsubscribe?token={subscriber.unsubscribe_token}",
        preferences_url=f"{settings.FRONTEND_URL}/newsletter",
    )
    return subject, html


async def send_confirmation_email(subscriber: NewsletterSubscriber) -> None:
    """Send the double opt-in confirmation. Raises EmailDeliveryError on failure."""
    confirm_url = (
        f"{settings.API_PUBLIC_URL}/api/v1/newsletter/confirm"
        f"?token={subscriber.confirm_token}"
    )
    html = _CONFIRM_TEMPLATE.render(
        style=_BASE_STYLE, confirm_url=confirm_url, frequency=subscriber.frequency
    )
    await send_email(
        to=subscriber.email,
        subject="Confirm your GlobeLens newsletter subscription",
        html=html,
    )


async def send_digest(db: AsyncSession, frequency: str) -> dict:
    """Build and send the digest to every active, confirmed subscriber.

    Returns counters so the admin trigger reports what actually happened rather
    than a bare "queued".
    """
    if frequency not in ("daily", "weekly"):
        raise ValueError("frequency must be 'daily' or 'weekly'")

    limit = (
        settings.NEWSLETTER_WEEKLY_TOP_N
        if frequency == "weekly"
        else settings.NEWSLETTER_DAILY_TOP_N
    )

    subscribers = list(
        (
            await db.execute(
                select(NewsletterSubscriber).where(
                    NewsletterSubscriber.frequency == frequency,
                    NewsletterSubscriber.is_active.is_(True),
                    NewsletterSubscriber.is_confirmed.is_(True),
                )
            )
        ).scalars().all()
    )

    sent = failed = skipped = 0
    now = datetime.now(timezone.utc)
    for subscriber in subscribers:
        events = await top_events(db, subscriber.interests, limit)
        if not events:
            skipped += 1
            continue
        subject, html = render_digest(subscriber, events, frequency)
        try:
            await send_email(to=subscriber.email, subject=subject, html=html)
            subscriber.last_sent_at = now
            sent += 1
        except EmailDeliveryError as exc:
            logger.warning("Digest delivery failed for %s: %s", subscriber.email, exc)
            failed += 1

    await db.commit()
    return {
        "frequency": frequency,
        "matched": len(subscribers),
        "sent": sent,
        "failed": failed,
        "skipped": skipped,
    }
