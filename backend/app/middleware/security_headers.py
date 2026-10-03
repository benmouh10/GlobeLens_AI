"""
GlobeLens AI — Security response headers middleware.

Adds the browser-hardening headers that a JSON API should always send.
``Strict-Transport-Security`` is only emitted for production, because sending
it over plain-HTTP localhost would pin the browser to HTTPS for the origin and
break local development.
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.config import settings

_BASE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-XSS-Protection": "0",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-site",
    # Only the framing directive: it hardens against clickjacking without
    # breaking the Swagger UI inline scripts served on /docs in development.
    "Content-Security-Policy": "frame-ancestors 'none'",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach security headers to every response."""

    def __init__(self, app, hsts: bool | None = None) -> None:
        super().__init__(app)
        if hsts is None:
            hsts = settings.APP_ENV.strip().lower() in {"production", "prod"}
        self._headers = dict(_BASE_HEADERS)
        if hsts:
            self._headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

    async def dispatch(self, request: Request, call_next):
        if not settings.SECURITY_HEADERS_ENABLED:
            return await call_next(request)
        response = await call_next(request)
        for name, value in self._headers.items():
            response.headers.setdefault(name, value)
        return response
