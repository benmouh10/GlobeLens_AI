"""
GlobeLens AI — Redis-backed rate limiting middleware.

Limits are enforced with a shared Redis counter so they hold across all
gunicorn workers and containers, unlike an in-process limiter. Two tiers are
used: a strict one for the authentication surface (login/register/refresh,
which is the brute-force target) and a general one for everything else.

The limiter is deliberately fail-open: if Redis is unreachable the request is
allowed through, so a cache outage degrades rate limiting rather than taking
the API down.
"""
from __future__ import annotations

import time
from typing import Tuple

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import settings
from app.services.cache_service import cache_service

_PERIOD_SECONDS = {
    "second": 1, "sec": 1, "s": 1,
    "minute": 60, "min": 60, "m": 60,
    "hour": 3600, "h": 3600,
    "day": 86400, "d": 86400,
}

# Health probes and interactive docs must never be throttled, or Docker/load
# balancers and CI would start seeing spurious 429s.
_EXEMPT_PATHS = {"/", "/health", "/docs", "/redoc", "/openapi.json", "/favicon.ico"}

# Strict tier: credential-issuing endpoints.
_AUTH_PATHS = {
    "/api/v1/auth/login",
    "/api/v1/auth/register",
    "/api/v1/auth/refresh",
}


def parse_rate(spec: str, default: Tuple[int, int] = (120, 60)) -> Tuple[int, int]:
    """Parse ``"<count>/<period>"`` (e.g. ``"10/minute"``) into (limit, seconds)."""
    if not spec:
        return default
    text = str(spec).strip().lower()
    number, _, period = text.partition("/")
    try:
        limit = int(number)
    except ValueError:
        return default
    if limit <= 0:
        return default
    if not period:
        return limit, 60
    period = period.strip().rstrip("s")
    for name, seconds in _PERIOD_SECONDS.items():
        if period.startswith(name):
            return limit, seconds
    return limit, 60


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Fixed-window per-client rate limiter backed by Redis INCR/EXPIRE."""

    async def dispatch(self, request: Request, call_next):
        if not settings.RATE_LIMIT_ENABLED or request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path.rstrip("/") or "/"
        if path in _EXEMPT_PATHS:
            return await call_next(request)

        category = "auth" if path in _AUTH_PATHS else "default"
        spec = settings.RATE_LIMIT_AUTH if category == "auth" else settings.RATE_LIMIT_DEFAULT
        limit, window = parse_rate(spec)
        identifier = self._client_identifier(request)

        allowed, remaining, retry_after = await self._consume(
            category, identifier, limit, window
        )

        headers = {
            "X-RateLimit-Limit": str(limit),
            "X-RateLimit-Remaining": str(remaining),
        }
        if not allowed:
            headers["Retry-After"] = str(retry_after)
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please slow down and retry later."},
                headers=headers,
            )

        response = await call_next(request)
        for name, value in headers.items():
            response.headers.setdefault(name, value)
        return response

    @staticmethod
    def _client_identifier(request: Request) -> str:
        # Only trust X-Forwarded-For when explicitly configured; otherwise a
        # client could spoof the header to bypass the limit.
        if settings.RATE_LIMIT_TRUST_FORWARDED:
            forwarded = request.headers.get("x-forwarded-for")
            if forwarded:
                return forwarded.split(",")[0].strip() or "unknown"
        client = request.client
        return client.host if client and client.host else "unknown"

    @staticmethod
    async def _consume(
        category: str, identifier: str, limit: int, window: int
    ) -> Tuple[bool, int, int]:
        """Return (allowed, remaining, retry_after_seconds)."""
        now = int(time.time())
        bucket = now // window
        key = f"ratelimit:{category}:{identifier}:{bucket}"
        try:
            client = await cache_service._get_client()
            pipe = client.pipeline()
            pipe.incr(key, 1)
            pipe.expire(key, window + 1)
            results = await pipe.execute()
            current = int(results[0])
        except Exception:
            return True, limit, 0

        if current > limit:
            retry_after = window - (now % window)
            return False, 0, max(1, retry_after)
        return True, max(0, limit - current), 0
