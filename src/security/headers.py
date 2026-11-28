"""Browser-oriented security headers for the FastAPI surface.

Adds HSTS, X-Content-Type-Options, X-Frame-Options, a restrictive CSP and
Referrer-Policy to every response. HSTS is only emitted for TLS requests (or
when ``TLS_ENABLED=true``) so local HTTP development keeps working.
"""
from __future__ import annotations

import os
from typing import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

__all__ = ["SecurityHeadersMiddleware", "security_headers"]

CSP = (
    "default-src 'self'; base-uri 'self'; object-src 'none'; "
    "frame-ancestors 'none'; form-action 'self'"
)


def security_headers(*, tls: bool) -> dict[str, str]:
    """Return the header map applied by the middleware."""
    headers = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Content-Security-Policy": CSP,
        "Referrer-Policy": "no-referrer",
        "Cross-Origin-Resource-Policy": "same-origin",
        "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    }
    if tls:
        max_age = os.getenv("HSTS_MAX_AGE", "31536000")
        headers["Strict-Transport-Security"] = (
            f"max-age={max_age}; includeSubDomains"
        )
    return headers


def _is_tls(request: Request) -> bool:
    if os.getenv("TLS_ENABLED", "").lower() in {"1", "true", "yes"}:
        return True
    forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    return request.url.scheme == "https" or forwarded == "https"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Starlette middleware injecting security headers on every response."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        for name, value in security_headers(tls=_is_tls(request)).items():
            response.headers[name] = value
        return response
