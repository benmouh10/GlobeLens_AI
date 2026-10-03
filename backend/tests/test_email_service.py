"""
Hermetic tests for the SMTP transport: settings plumbing and error wrapping.

aiosmtplib.send is monkeypatched, so no network or credentials are required.
"""
import aiosmtplib
import pytest

from app.core.config import settings
from app.services import email_service
from app.services.email_service import EmailDeliveryError, send_email


def _pin(monkeypatch, **values):
    for name, value in values.items():
        monkeypatch.setattr(settings, name, value)


@pytest.mark.asyncio
async def test_send_email_passes_smtp_settings_through(monkeypatch):
    captured = {}

    async def fake_send(message, **kwargs):
        captured["message"] = message
        captured.update(kwargs)

    monkeypatch.setattr(email_service.aiosmtplib, "send", fake_send)
    _pin(
        monkeypatch,
        SMTP_HOST="smtp.gmail.com",
        SMTP_PORT=587,
        SMTP_USERNAME="bot@example.com",
        SMTP_PASSWORD="app-password",
        SMTP_STARTTLS=True,
        SMTP_SSL=False,
        SMTP_TIMEOUT_SECONDS=15,
    )

    await send_email(to="dest@example.com", subject="Hi", html="<p>Hi</p>")

    assert captured["hostname"] == "smtp.gmail.com"
    assert captured["port"] == 587
    assert captured["username"] == "bot@example.com"
    assert captured["password"] == "app-password"
    assert captured["start_tls"] is True
    assert captured["use_tls"] is False
    assert captured["timeout"] == 15
    assert captured["message"]["To"] == "dest@example.com"


@pytest.mark.asyncio
async def test_empty_credentials_are_passed_as_none(monkeypatch):
    captured = {}

    async def fake_send(message, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(email_service.aiosmtplib, "send", fake_send)
    _pin(monkeypatch, SMTP_USERNAME="", SMTP_PASSWORD="")

    await send_email(to="dest@example.com", subject="Hi", html="<p>Hi</p>")

    assert captured["username"] is None
    assert captured["password"] is None


@pytest.mark.asyncio
async def test_transport_errors_are_wrapped(monkeypatch):
    async def boom(message, **kwargs):
        raise aiosmtplib.SMTPException("535 Authentication Credentials Invalid")

    monkeypatch.setattr(email_service.aiosmtplib, "send", boom)

    with pytest.raises(EmailDeliveryError, match="535"):
        await send_email(to="dest@example.com", subject="Hi", html="<p>Hi</p>")
