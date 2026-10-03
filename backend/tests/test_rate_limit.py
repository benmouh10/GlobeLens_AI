"""
Hermetic tests for the Redis-backed rate limiting middleware.

A tiny in-memory fake stands in for Redis so the limiter's window/bucket logic,
the strict auth tier, the exempt paths and the fail-open behaviour can be
verified without a live cache.
"""
import httpx
import pytest
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from app.core.config import settings
from app.middleware.rate_limit import RateLimitMiddleware, parse_rate
from app.services.cache_service import cache_service


class _FakePipeline:
    def __init__(self, store):
        self._store = store
        self._ops = []

    def incr(self, key, amount=1):
        self._ops.append(("incr", key, amount))
        return self

    def expire(self, key, ttl):
        self._ops.append(("expire", key, ttl))
        return self

    async def execute(self):
        results = []
        for op, key, arg in self._ops:
            if op == "incr":
                self._store[key] = self._store.get(key, 0) + arg
                results.append(self._store[key])
            else:
                results.append(True)
        return results


class _FakeRedis:
    def __init__(self):
        self.store = {}

    def pipeline(self):
        return _FakePipeline(self.store)


def _make_app() -> Starlette:
    async def ok(request):
        return PlainTextResponse("ok")

    app = Starlette(
        routes=[
            Route("/ping", ok),
            Route("/health", ok),
            Route("/api/v1/auth/login", ok, methods=["POST"]),
        ]
    )
    app.add_middleware(RateLimitMiddleware)
    return app


def _client(app: Starlette) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


@pytest.fixture
def fake_cache(monkeypatch):
    fake = _FakeRedis()

    async def _get_client():
        return fake

    monkeypatch.setattr(cache_service, "_get_client", _get_client)
    return fake


class TestParseRate:
    def test_minute_spec(self):
        assert parse_rate("10/minute") == (10, 60)

    def test_second_spec(self):
        assert parse_rate("5/second") == (5, 1)

    def test_hour_spec_and_plural(self):
        assert parse_rate("100/hours") == (100, 3600)

    def test_bare_number_defaults_to_minute(self):
        assert parse_rate("30") == (30, 60)

    @pytest.mark.parametrize("bad", ["", "abc", "0/minute", "-5/minute"])
    def test_invalid_falls_back_to_default(self, bad):
        assert parse_rate(bad) == (120, 60)


@pytest.mark.asyncio
async def test_blocks_after_limit(fake_cache, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_DEFAULT", "2/minute")
    app = _make_app()

    async with _client(app) as client:
        assert (await client.get("/ping")).status_code == 200
        assert (await client.get("/ping")).status_code == 200
        blocked = await client.get("/ping")
        assert blocked.status_code == 429
        assert "Retry-After" in blocked.headers
        assert blocked.headers["X-RateLimit-Remaining"] == "0"


@pytest.mark.asyncio
async def test_exempt_paths_are_never_limited(fake_cache, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_DEFAULT", "1/minute")
    app = _make_app()

    async with _client(app) as client:
        for _ in range(5):
            assert (await client.get("/health")).status_code == 200


@pytest.mark.asyncio
async def test_auth_tier_is_stricter_than_default(fake_cache, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_DEFAULT", "100/minute")
    monkeypatch.setattr(settings, "RATE_LIMIT_AUTH", "1/minute")
    app = _make_app()

    async with _client(app) as client:
        # General routes keep working on the generous default tier...
        assert (await client.get("/ping")).status_code == 200
        assert (await client.get("/ping")).status_code == 200
        # ...while the auth endpoint trips after a single request.
        assert (await client.post("/api/v1/auth/login")).status_code == 200
        assert (await client.post("/api/v1/auth/login")).status_code == 429


@pytest.mark.asyncio
async def test_fails_open_when_cache_unavailable(monkeypatch):
    async def _boom():
        raise RuntimeError("redis down")

    monkeypatch.setattr(cache_service, "_get_client", _boom)
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_DEFAULT", "1/minute")
    app = _make_app()

    async with _client(app) as client:
        for _ in range(3):
            assert (await client.get("/ping")).status_code == 200


@pytest.mark.asyncio
async def test_disabled_limiter_allows_everything(fake_cache, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)
    monkeypatch.setattr(settings, "RATE_LIMIT_DEFAULT", "1/minute")
    app = _make_app()

    async with _client(app) as client:
        for _ in range(4):
            assert (await client.get("/ping")).status_code == 200


@pytest.mark.asyncio
async def test_throttled_response_keeps_cors_headers(fake_cache, monkeypatch):
    # Mirrors main.py ordering: CORS is added after the limiter so browsers can
    # actually read the 429 instead of seeing an opaque CORS failure.
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_DEFAULT", "1/minute")
    app = _make_app()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://client.test"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    async with _client(app) as client:
        assert (await client.get("/ping")).status_code == 200
        blocked = await client.get("/ping", headers={"Origin": "http://client.test"})
        assert blocked.status_code == 429
        assert blocked.headers.get("access-control-allow-origin") == "http://client.test"
