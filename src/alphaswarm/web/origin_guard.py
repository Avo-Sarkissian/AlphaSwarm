"""One origin policy for the unauthenticated operator console (CWE-352).

The API and the /ws/state stream have no authentication; they bind to 127.0.0.1
and rely on three layers (docs/DECISIONS.md#adr-security-2026-08):

1. TrustedHostMiddleware (web/app.py) answers only the Host values in
   AppSettings.trusted_hosts (checked by normalized_trusted_hosts), which defeats
   DNS rebinding: a page that re-points its own name at 127.0.0.1 still sends its
   own name as Host.
2. OriginGuardMiddleware (this module) rejects state-changing HTTP requests whose
   Origin (or, without Origin, Referer) is not in AppSettings.allowed_origins.
3. web/routes/websocket.py applies the same is_allowed() check to the WebSocket
   handshake.

Policy (is_allowed)
-------------------
* An absent header is allowed: browsers always send Origin on cross-origin
  requests and on every WebSocket handshake, so a header-less request is not
  browser-driven (curl, scripts/, the test client).
* A present value must normalise to an allow-listed origin. A literal "null"
  origin (sandboxed iframe, Referrer-Policy: no-referrer), an empty value and
  anything without a scheme and host never match.
* Safe HTTP methods (GET/HEAD/OPTIONS) are not origin-checked: they change no
  state, and the Host check already stops rebinding reads.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Collection, Iterable, Sequence
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


def normalized_allowlist(origins: Iterable[str]) -> frozenset[str]:
    """Normalise every allow-list entry; raise ValueError for one that has no origin.

    Called when the app is built, so a typo such as "localhost:5173" (no scheme)
    or "*" fails at startup instead of silently matching nothing.
    """
    allowed: set[str] = set()
    for entry in origins:
        normalized = normalize_origin(entry)
        if normalized is None:
            raise ValueError(f"allowed_origins entry {entry!r} is not an origin of the form scheme://host[:port]")
        allowed.add(normalized)
    return frozenset(allowed)


def _trusted_host_problem(host: str) -> str | None:
    """Why *host* (already stripped and lower-cased) cannot be a trusted-host entry."""
    if not host:
        return "it is empty"
    if host == "*":
        return "'*' would turn the Host check off"
    if host.startswith("[") and host.endswith("]"):
        try:
            ipaddress.IPv6Address(host[1:-1])
        except ValueError:
            return "it is not a bracketed IPv6 address"
        return None
    if not host.isascii():
        return "use the ASCII (punycode) form of the name"
    if any(char in host for char in ":/@?# \t"):
        return "give the host only, without a scheme, port, path or user"
    if "*" in host and not (host.startswith("*.") and len(host) > 2 and "*" not in host[2:]):
        return "a wildcard is allowed only as a leading '*.', as in '*.example.com'"
    return None


def normalized_trusted_hosts(hosts: Iterable[str]) -> list[str]:
    """Lower-case every trusted-host entry; raise ValueError for a malformed one.

    TrustedHostMiddleware compares the Host header up to its first ":" with each
    entry exactly, so an entry with a port ("localhost:8000") or a scheme never
    matches and every request gets 400, and a misplaced wildcard trips Starlette's
    assertion on the first request. Called when the app is built, so those typos
    fail at startup instead (docs/DECISIONS.md#adr-security-2026-08).
    """
    normalized: list[str] = []
    for entry in hosts:
        host = entry.strip().lower()
        problem = _trusted_host_problem(host)
        if problem is not None:
            raise ValueError(f"trusted_hosts entry {entry!r} is not a host name: {problem}")
        normalized.append(host)
    return normalized


def is_allowed(origin: str | None, allowed: Collection[str]) -> bool:
    """The single origin policy for HTTP and WebSocket (see the module docstring).

    *origin* is the raw header value, or None when the header is absent;
    *allowed* may hold raw or normalised entries.
    """
    if origin is None:
        return True
    candidate = normalize_origin(origin)
    if candidate is None:
        return False
    return candidate in {normalize_origin(entry) for entry in allowed}


class OriginGuardMiddleware:
    """Reject state-changing HTTP requests from non-allow-listed origins.

    Pure ASGI (not ``BaseHTTPMiddleware``) so it adds no task group around the
    request and leaves WebSocket and lifespan scopes completely untouched.
    """

    def __init__(self, app: ASGIApp, allowed_origins: Sequence[str]) -> None:
        self.app = app
        self.allowed_origins: frozenset[str] = normalized_allowlist(allowed_origins)

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
        if is_allowed(raw, self.allowed_origins):
            await self.app(scope, receive, send)
            return

        log.warning(
            "origin_rejected",
            method=scope.get("method"),
            path=scope.get("path"),
            source=source,
            value=(raw or "")[:_LOG_VALUE_LIMIT],
        )
        response = JSONResponse(
            status_code=403,
            content={
                "detail": {
                    "error": "origin_not_allowed",
                    "message": (
                        "Cross-origin state-changing requests are rejected. "
                        "Set ALPHASWARM_ALLOWED_ORIGINS if the UI is served "
                        "from another origin."
                    ),
                }
            },
        )
        await response(scope, receive, send)


def install_origin_guard(app: FastAPI, allowed_origins: Sequence[str]) -> None:
    """Install OriginGuardMiddleware on *app*; an invalid entry raises ValueError now."""
    normalized_allowlist(allowed_origins)
    app.add_middleware(OriginGuardMiddleware, allowed_origins=tuple(allowed_origins))
