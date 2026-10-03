"""
GlobeLens AI — Email Service

Thin async wrapper around aiosmtplib. It knows nothing about newsletters; it
takes a recipient, a subject and rendered bodies and hands them to SMTP.

In development the SMTP host is the Mailpit catcher (docker-compose service),
so mail is delivered and inspectable at http://localhost:8025 without any
external provider.
"""
import logging
from email.message import EmailMessage
from typing import Optional

import aiosmtplib

from app.core.config import settings

logger = logging.getLogger(__name__)


class EmailDeliveryError(RuntimeError):
    """Raised when the SMTP transport rejects or cannot reach the message."""


async def send_email(
    *,
    to: str,
    subject: str,
    html: str,
    text: Optional[str] = None,
) -> None:
    """Send a single multipart (text + HTML) email.

    Raises EmailDeliveryError on transport failure so callers can record the
    failure rather than assuming delivery. Nothing here swallows the error:
    a digest that silently failed to send is worse than a loud failure.
    """
    message = EmailMessage()
    message["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
    message["To"] = to
    message["Subject"] = subject

    # A plain-text part first so non-HTML clients have something readable.
    message.set_content(text or _html_to_text(html))
    message.add_alternative(html, subtype="html")

    try:
        await aiosmtplib.send(
            message,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USERNAME or None,
            password=settings.SMTP_PASSWORD or None,
            start_tls=settings.SMTP_STARTTLS,
            use_tls=settings.SMTP_SSL,
            timeout=settings.SMTP_TIMEOUT_SECONDS,
        )
    except Exception as exc:  # noqa: BLE001 - surface as a domain error
        raise EmailDeliveryError(f"SMTP send to {to} failed: {exc}") from exc

    logger.info("Sent email '%s' to %s", subject, to)


def _html_to_text(html: str) -> str:
    """Crude HTML→text fallback for the plain-text part."""
    import re

    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</(p|div|h[1-6]|li|tr)>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
