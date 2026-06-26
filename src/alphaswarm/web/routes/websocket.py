"""WebSocket route: /ws/state — real-time state stream endpoint.

Data flows server-to-client only. The broadcaster task calls
connection_manager.broadcast() which enqueues messages to each client's
writer task. The receive loop exists solely for disconnect detection.

Local-dev-only (D-10): no authentication, no origin checking.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect

log = structlog.get_logger(component="web.ws_state")
router = APIRouter()


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
    """
    connection_manager = websocket.app.state.connection_manager
    log.info("ws_state_connected", client=str(websocket.client))
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
