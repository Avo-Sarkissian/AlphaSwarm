"""WebSocket route: /ws/state — real-time state stream endpoint.

Data flows server-to-client only. The broadcaster task calls
connection_manager.broadcast() which enqueues messages to each client's
writer task. The receive loop exists solely for disconnect detection.

Local-dev-only (D-10): no authentication. Because there is no authentication,
the handshake Origin is checked against an allow-list (F2) — otherwise any
page the operator visits while the server runs could open this socket
cross-origin and stream the entire live simulation state.
"""

from __future__ import annotations

import unicodedata

import structlog
from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect

from alphaswarm.config import DEFAULT_WS_ALLOWED_ORIGINS

log = structlog.get_logger(component="web.ws_state")
router = APIRouter()

# RFC 6455 close code 1008 = policy violation.
_POLICY_VIOLATION_CLOSE_CODE = 1008

# The Origin header is attacker-controlled free text (h11 accepts ~16 KB of it)
# and is not covered by the PII processor's free-text scrubbing, so it is bounded
# and neutralized before it is bound to a log event: with ALPHASWARM_DEBUG=true
# structlog's ConsoleRenderer writes str values verbatim, and whitespace inside
# such a value would forge additional key=value pairs in the rendered line.
_MAX_LOGGED_ORIGIN_CHARS = 64
_ORIGIN_TRUNCATION_MARKER = "...[truncated]"


def _normalize_origin(value: str) -> str:
    """Canonical form for exact-match comparison: trimmed, no trailing slash, lowercased.

    Deliberately no prefix/suffix matching — "http://localhost:5173.evil.example"
    and "http://localhost:8000@evil.example" must not match an allow-list entry.
    """
    return value.strip().rstrip("/").lower()


def _safe_origin_for_log(origin: str | None) -> str:
    """Bound and neutralize an untrusted Origin so it is safe to bind as a log field.

    Truncates to _MAX_LOGGED_ORIGIN_CHARS (a real origin is far shorter) and
    replaces whitespace plus Unicode control/format characters with "_", so the
    value can neither flood the log stream nor forge key=value pairs in a
    ConsoleRenderer line. Still readable enough to debug a refused origin.
    """
    if origin is None:
        return "<none>"
    cleaned = "".join(
        "_" if (c.isspace() or unicodedata.category(c) in ("Cc", "Cf")) else c
        for c in origin[:_MAX_LOGGED_ORIGIN_CHARS]
    )
    if len(origin) > _MAX_LOGGED_ORIGIN_CHARS:
        cleaned += _ORIGIN_TRUNCATION_MARKER
    return cleaned


def _server_origin(websocket: WebSocket) -> str | None:
    """This server's own origin, derived from the ASGI scope without URL parsing.

    scope["scheme"] is already "ws"/"wss", so the http(s) scheme needs no
    parsing. We deliberately do NOT read websocket.url.scheme: Starlette builds
    URL by concatenating the raw Host header, and .scheme lazily calls urlsplit,
    which raises ValueError ("Invalid IPv6 URL") on an unbalanced-bracket Host
    such as "]" or "[x]". h11/uvicorn accept such a Host, so an unauthenticated
    peer could otherwise turn every handshake into an unhandled 500. Here a
    malformed Host merely yields a string that matches nothing, and the
    connection takes the normal refusal path.
    """
    host = websocket.headers.get("host")
    if not host:
        return None
    scheme = "https" if websocket.scope.get("scheme") == "wss" else "http"
    return _normalize_origin(f"{scheme}://{host}")


def _configured_allowed_origins(websocket: WebSocket) -> tuple[str, ...]:
    """Allow-list from AppSettings.ws_allowed_origins, wired via app.state.app_state.

    Falls back to the same defaults the setting declares if app.state is only
    partially wired — never to "allow everything".
    """
    app_state = getattr(websocket.app.state, "app_state", None)
    configured = getattr(getattr(app_state, "settings", None), "ws_allowed_origins", None)
    if not isinstance(configured, (list, tuple)):
        return DEFAULT_WS_ALLOWED_ORIGINS
    return tuple(str(entry) for entry in configured)


def _is_origin_allowed(websocket: WebSocket) -> bool:
    """True when this handshake's Origin may open the state stream.

    - No Origin header → allowed. Browsers ALWAYS send Origin on a WebSocket
      handshake, so the cross-site threat this guards against always carries
      one; non-browser tooling (TestClient, wscat, scripts) sends none and
      keeps working.
    - Configured allow-list, or the server's own origin → allowed.
    - Anything else, including "null" (sandboxed iframe / opaque origin) → refused.
    """
    origin = websocket.headers.get("origin")
    if origin is None:
        return True
    candidate = _normalize_origin(origin)
    if not candidate:
        return False
    allowed = {_normalize_origin(entry) for entry in _configured_allowed_origins(websocket)}
    if candidate in allowed:
        return True
    server_origin = _server_origin(websocket)
    return server_origin is not None and candidate == server_origin


@router.websocket("/ws/state")
async def ws_state(websocket: WebSocket) -> None:
    """Accept WebSocket connection and enter receive loop for disconnect detection.

    Data flows server-to-client only: the broadcaster task calls
    connection_manager.broadcast() which enqueues messages to each client's
    writer task. This receive loop exists solely to detect client disconnects.

    Assumptions:
    - Data flows server-to-client only, so any inbound frame (text or binary)
      is discarded. We use receive() rather than receive_text() so a non-text
      frame does not raise a KeyError that escapes as an unhandled endpoint
      error and abruptly drops the connection (F-27).
    - F2: the Origin check runs BEFORE connection_manager.connect(), so a
      refused peer never reaches ws.accept(), never allocates a queue or a
      writer task, and never appears in client_count.
    """
    origin_for_log = _safe_origin_for_log(websocket.headers.get("origin"))
    if not _is_origin_allowed(websocket):
        log.warning(
            "ws_state_origin_refused",
            client=str(websocket.client),
            origin=origin_for_log,
        )
        await websocket.close(code=_POLICY_VIOLATION_CLOSE_CODE)
        return

    connection_manager = websocket.app.state.connection_manager
    log.info("ws_state_connected", client=str(websocket.client), origin=origin_for_log)
    await connection_manager.connect(websocket)
    try:
        while True:
            # Blocks; exists solely for disconnect detection. Inbound data
            # frames (text or binary) are ignored — this channel is one-way.
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
    except WebSocketDisconnect:
        pass
    finally:
        log.info("ws_state_disconnected", client=str(websocket.client))
        await connection_manager.disconnect(websocket)
