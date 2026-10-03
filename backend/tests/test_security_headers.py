"""
Hermetic tests for the security response headers middleware.
"""
import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from app.core.config import settings
from app.middleware.security_headers import SecurityHeadersMiddleware

_BASE_EXPECTED = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Content-Security-Policy": "frame-ancestors 'none'",
}


def _make_app(hsts: bool) -> Starlette:
    async def ok(request):
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/ping", ok)])
    app.add_middleware(SecurityHeadersMiddleware, hsts=hsts)
    return app


def _client(app: Starlette) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


@pytest.mark.asyncio
async def test_base_headers_are_set(monkeypatch):
    monkeypatch.setattr(settings, "SECURITY_HEADERS_ENABLED", True)
    async with _client(_make_app(hsts=False)) as client:
        response = await client.get("/ping")
        assert response.status_code == 200
        for name, value in _BASE_EXPECTED.items():
            assert response.headers.get(name) == value
        assert "Strict-Transport-Security" not in response.headers


@pytest.mark.asyncio
async def test_hsts_only_when_enabled(monkeypatch):
    monkeypatch.setattr(settings, "SECURITY_HEADERS_ENABLED", True)
    async with _client(_make_app(hsts=True)) as client:
        response = await client.get("/ping")
        assert response.headers["Strict-Transport-Security"] == (
            "max-age=31536000; includeSubDomains"
        )


@pytest.mark.asyncio
async def test_disabled_toggle_skips_headers(monkeypatch):
    monkeypatch.setattr(settings, "SECURITY_HEADERS_ENABLED", False)
    async with _client(_make_app(hsts=True)) as client:
        response = await client.get("/ping")
        assert "X-Content-Type-Options" not in response.headers
        assert "Strict-Transport-Security" not in response.headers
