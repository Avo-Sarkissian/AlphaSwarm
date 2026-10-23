"""WebSocket route: /ws/state — real-time state stream endpoint.

Data flows server-to-client only. The broadcaster task calls
connection_manager.broadcast() which enqueues messages to each client's
writer task. The receive loop exists solely for disconnect detection.

Local-dev-only (docs/DECISIONS.md#p30-d-10): no authentication. A handshake
must pass the Host check (TrustedHostMiddleware) and then the single origin
policy shared with the HTTP CSRF guard (web/origin_guard.is_allowed, docs/DECISIONS.md#adr-security-2026-08).
The allowed origin is never derived from the request's own Host header: a
DNS-rebinding page controls that header.
"""

from __future__ import annotations

import unicodedata

import structlog
from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect

from alphaswarm.settings import DEFAULT_ALLOWED_ORIGINS
from alphaswarm.web.origin_guard import is_allowed

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


def _configured_allowed_origins(websocket: WebSocket) -> tuple[str, ...]:
    """AppSettings.allowed_origins, from app.state.settings (create_app) or
    app.state.app_state.settings (test apps); the defaults otherwise — never
    "allow everything"."""
    state = websocket.app.state
    app_state = getattr(state, "app_state", None)
    for settings in (getattr(state, "settings", None), getattr(app_state, "settings", None)):
        configured = getattr(settings, "allowed_origins", None)
        if isinstance(configured, (list, tuple)):
            return tuple(str(entry) for entry in configured)
    return DEFAULT_ALLOWED_ORIGINS


def _is_origin_allowed(websocket: WebSocket) -> bool:
    """True when this handshake's Origin may open the state stream."""
    return is_allowed(websocket.headers.get("origin"), _configured_allowed_origins(websocket))


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
      error and abruptly drops the connection (docs/DECISIONS.md#f-27).
    - The Origin check runs BEFORE connection_manager.connect(), so a
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
