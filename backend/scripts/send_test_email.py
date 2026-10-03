"""
Send a single test email through the configured SMTP settings.

Usage (inside the backend container, so it shares docker-compose env):

    docker compose exec backend python -m scripts.send_test_email you@example.com

or from a host shell with the backend environment loaded:

    python -m scripts.send_test_email you@example.com

Exits non-zero and prints an actionable hint when delivery fails, so it can be
used as a post-deploy smoke check for the SMTP configuration.
"""
from __future__ import annotations

import asyncio
import sys

from app.core.config import settings
from app.services.email_service import EmailDeliveryError, send_email

# Hints for the SMTP reply codes providers actually return on misconfiguration.
_HINTS = {
    "530": "Authentication required (530). Set SMTP_USERNAME and SMTP_PASSWORD.",
    "534": "Gmail rejected the login (534). Use a 16-char App Password, not the account password.",
    "535": "Bad credentials (535). For Gmail, enable 2FA and create an App Password.",
    "550": "Sender or recipient rejected (550). SMTP_FROM_EMAIL must match the authenticated address.",
    "553": "Invalid sender address (553). Check SMTP_FROM_EMAIL.",
    "554": "Message rejected (554). Check the provider's sending policy.",
}


async def _run(recipient: str) -> int:
    print(
        "SMTP "
        f"host={settings.SMTP_HOST} port={settings.SMTP_PORT} "
        f"starttls={settings.SMTP_STARTTLS} ssl={settings.SMTP_SSL} "
        f"user={'set' if settings.SMTP_USERNAME else 'unset'} "
        f"from={settings.SMTP_FROM_EMAIL}"
    )
    try:
        await send_email(
            to=recipient,
            subject="GlobeLens AI — SMTP test",
            html="<p>This is a test email from <strong>GlobeLens AI</strong>.</p>",
            text="This is a test email from GlobeLens AI.",
        )
    except EmailDeliveryError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        for code, hint in _HINTS.items():
            if code in str(exc):
                print(f"Hint: {hint}", file=sys.stderr)
                break
        return 1

    print(f"OK: test email accepted for {recipient}. Check the inbox (and spam).")
    return 0


def main() -> int:
    if len(sys.argv) != 2:
        print(
            "usage: python -m scripts.send_test_email <recipient@example.com>",
            file=sys.stderr,
        )
        return 2
    return asyncio.run(_run(sys.argv[1]))


if __name__ == "__main__":
    raise SystemExit(main())
