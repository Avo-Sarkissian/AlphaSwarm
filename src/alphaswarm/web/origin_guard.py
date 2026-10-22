"""Origin/Referer allow-list guard for state-changing HTTP requests (CWE-352).

The API is an unauthenticated localhost operator console. Every mutating route
(POST /api/simulate/start, POST /api/simulate/stop, POST /api/advisory/{id},
POST /api/report/{id}/generate, POST /api/replay/*, PUT /api/settings, ...)
therefore executes with the operator's full authority for anyone who can make
the operator's browser issue the request. Body-less POSTs are the sharpest
edge: a plain cross-site HTML form POST is a CORS *simple* request, so it is
delivered without a preflight and the (absent) CORS response headers only hide
the response body from the attacker — the side effect has already happened.

This module installs ONE ASGI middleware in front of the whole app so the
guard cannot drift as routes are added.

Policy
------
* Safe methods (GET/HEAD/OPTIONS) are never guarded — they change no state.
* If an ``Origin`` header is present it MUST normalise to an allow-listed
  origin, otherwise the request is rejected with 403. A literal ``null``
  origin (sandboxed iframe, ``Referrer-Policy: no-referrer``) does not
  normalise and is therefore rejected.
* If ``Origin`` is absent, ``Referer`` is checked the same way (older browsers
  omitted ``Origin`` on same-origin form posts).
* If BOTH are absent the request is allowed. This is deliberate: browsers
  always attach ``Origin`` to cross-origin POST/PUT/DELETE (per Fetch, the
  header is set for every non-GET/HEAD request, including form submissions),
  so a header-less request is not browser-driven. Non-browser callers — curl,
  ``scripts/`` and the test suite's Starlette ``TestClient`` — send neither
  header and must keep working. Rejecting header-less requests would break
  those callers without closing any browser-reachable hole.
"""

from __future__ import annotations

from collections.abc import Sequence
from urllib.parse import urlsplit

import structlog
from fastapi import FastAPI
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

log = structlog.get_logger(component="web.origin_guard")

# Methods that cannot change server state, so they are not guarded.
SAFE_METHODS: frozenset[str] = frozenset({"GET", "HEAD", "OPTIONS"})

_DEFAULT_PORTS: dict[str, int] = {"http": 80, "https": 443}

# Attacker-controlled header value; truncated before it reaches the log.
_LOG_VALUE_LIMIT = 200


def normalize_origin(value: str) -> str | None:
    """Return ``scheme://host[:port]`` for *value*, or None if it has no origin.

    Accepts either a bare origin (``Origin`` header) or a full URL (``Referer``
    header). Case is folded and default ports are dropped so that equivalent
    spellings compare equal. Returns None for anything without both a scheme
    and a host — notably the literal ``null`` origin, which must never match
    an allow-list entry.
    """
    try:
        parts = urlsplit(value.strip())
        scheme = parts.scheme.lower()
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError:
        return None
    if not scheme or not host:
        return None
    if ":" in host:  # IPv6 literal — urlsplit strips the brackets
        host = f"[{host}]"
    if port is None or _DEFAULT_PORTS.get(scheme) == port:
        return f"{scheme}://{host}"
    return f"{scheme}://{host}:{port}"


class OriginGuardMiddleware:
    """Reject state-changing HTTP requests from non-allow-listed origins.

    Pure ASGI (not ``BaseHTTPMiddleware``) so it adds no task group around the
    request and leaves WebSocket and lifespan scopes completely untouched.
    """

    def __init__(self, app: ASGIApp, allowed_origins: Sequence[str]) -> None:
        self.app = app
        self.allowed_origins: frozenset[str] = frozenset(
            normalized
            for normalized in (normalize_origin(origin) for origin in allowed_origins)
            if normalized is not None
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method", "GET") in SAFE_METHODS:
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        source = "origin"
        raw = headers.get("origin")
        if raw is None:
            source = "referer"
            raw = headers.get("referer")
        if raw is None:
            # No browser-supplied origin information at all: curl, scripts or
            # TestClient. Allowed by
            # policy (see module docstring).
            await self.app(scope, receive, send)
            return

        if normalize_origin(raw) in self.allowed_origins:
            await self.app(scope, receive, send)
            return

        log.warning(
            "origin_rejected",
            method=scope.get("method"),
            path=scope.get("path"),
            source=source,
            value=raw[:_LOG_VALUE_LIMIT],
        )
        response = JSONResponse(
            status_code=403,
            content={
                "detail": {
                    "error": "origin_not_allowed",
                    "message": (
                        "Cross-origin state-changing requests are rejected. "
                        "Set ALPHASWARM_HTTP_ALLOWED_ORIGINS if the UI is "
                        "served from another origin."
                    ),
                }
            },
        )
        await response(scope, receive, send)


def install_origin_guard(app: FastAPI, allowed_origins: Sequence[str]) -> None:
    """Install :class:`OriginGuardMiddleware` on *app* for every route it serves."""
    app.add_middleware(OriginGuardMiddleware, allowed_origins=tuple(allowed_origins))
