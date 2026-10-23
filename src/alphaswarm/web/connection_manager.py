"""ConnectionManager: per-client WebSocket queue registry."""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Final

import structlog

if TYPE_CHECKING:
    from fastapi import WebSocket

log = structlog.get_logger(component="web.connection_manager")

# Latest-wins: a client's queue holds only the newest frame. A full queue still
# drops its oldest frame (CLAUDE.md constraint 4) but never builds a stale
# backlog (docs/DECISIONS.md#adr-ws-broadcaster).
CLIENT_QUEUE_MAXSIZE: Final = 1


class ConnectionManager:
    """Manages WebSocket client lifecycle with per-client bounded queues.

    Each client gets an asyncio.Queue[str](maxsize=CLIENT_QUEUE_MAXSIZE) and a dedicated
    asyncio.Task that drains the queue and sends to the socket.
    broadcast() puts into all queues without awaiting sends (non-blocking).
    Latest-wins: a full one-frame queue drops its oldest frame. ``generation``
    counts connections so the broadcaster can greet a new client on the next tick.

    Created inside FastAPI lifespan. Phase 30 wires the broadcast ticker.
    """

    def __init__(self) -> None:
        self._clients: dict[WebSocket, asyncio.Queue[str]] = {}
        self._tasks: dict[WebSocket, asyncio.Task[None]] = {}
        self._generation = 0

    async def connect(self, ws: WebSocket) -> None:
        """Accept WebSocket and register client with a bounded queue + writer task."""
        await ws.accept()
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=CLIENT_QUEUE_MAXSIZE)
        self._clients[ws] = queue
        self._tasks[ws] = asyncio.create_task(self._writer(ws, queue))
        self._generation += 1
        log.info("client_connected", client_count=len(self._clients))

    async def disconnect(self, ws: WebSocket) -> None:
        """Remove client, cancel its writer task, and clean up."""
        task = self._tasks.pop(ws, None)
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._clients.pop(ws, None)
        log.info("client_disconnected", client_count=len(self._clients))

    async def _writer(self, ws: WebSocket, queue: asyncio.Queue[str]) -> None:
        """Dedicated per-client writer: drain queue and send to WebSocket.

        B7: finally block cleans up self._clients and self._tasks on ALL
        exit paths (normal return, CancelledError, or other Exception).
        Before the fix, a crashed client that never routed through
        disconnect() left stale entries behind, causing broadcast() to
        put messages into dead queues and leaking memory.

        disconnect() also pops these entries; dict.pop(key, None) is
        idempotent so the double-pop is safe.
        """
        try:
            while True:
                data = await queue.get()
                await ws.send_text(data)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Connection dropped — log then fall through to finally for cleanup.
            log.warning("websocket_writer_exited_with_exception")
        finally:
            # B7: remove our own registry entries so broadcast() no longer
            # puts into a dead queue. Safe to run after CancelledError too.
            self._clients.pop(ws, None)
            self._tasks.pop(ws, None)

    def broadcast(self, message: str) -> None:
        """Non-blocking put to all client queues. Drop-oldest on overflow.

        This is synchronous — does NOT await any sends. Each client's
        dedicated _writer task handles the actual send.
        """
        for queue in self._clients.values():
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()  # Drop oldest
                queue.put_nowait(message)

    @property
    def client_count(self) -> int:
        """Number of currently connected clients."""
        return len(self._clients)

    @property
    def generation(self) -> int:
        """Number of connections accepted so far; grows by one per connect()."""
        return self._generation
