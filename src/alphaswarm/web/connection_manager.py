"""ConnectionManager: per-client WebSocket queue registry."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from fastapi import WebSocket

log = structlog.get_logger(component="web.connection_manager")


class ConnectionManager:
    """Manages WebSocket client lifecycle with per-client bounded queues.

    Each client gets an asyncio.Queue[str](maxsize=100) and a dedicated
    asyncio.Task that drains the queue and sends to the socket.
    broadcast() puts into all queues without awaiting sends (non-blocking).
    Drop-oldest policy on overflow.

    Created inside FastAPI lifespan. Phase 30 wires the broadcast ticker.
    """

    def __init__(self) -> None:
        self._clients: dict[WebSocket, asyncio.Queue[str]] = {}
        self._tasks: dict[WebSocket, asyncio.Task[None]] = {}

    async def connect(self, ws: WebSocket) -> None:
        """Accept WebSocket and register client with a bounded queue + writer task."""
        await ws.accept()
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=100)
        self._clients[ws] = queue
        self._tasks[ws] = asyncio.create_task(self._writer(ws, queue))
        log.info("client_connected", client_count=len(self._clients))

    async def disconnect(self, ws: WebSocket) -> None:
        """Remove client, cancel its writer task, and clean up."""
        task = self._tasks.pop(ws, None)
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._clients.pop(ws, None)
        log.info("client_disconnected", client_count=len(self._clients))

    async def _writer(self, ws: WebSocket, queue: asyncio.Queue[str]) -> None:
        """Dedicated per-client writer: drain queue and send to WebSocket."""
        try:
            while True:
                data = await queue.get()
                await ws.send_text(data)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Connection dropped — task exits naturally
            pass

    def broadcast(self, message: str) -> None:
        """Non-blocking put to all client queues. Drop-oldest on overflow.

        This is synchronous — does NOT await any sends. Each client's
        dedicated _writer task handles the actual send.
        """
        for queue in self._clients.values():
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()  # Drop oldest
                except asyncio.QueueEmpty:
                    pass
                queue.put_nowait(message)

    @property
    def client_count(self) -> int:
        """Number of currently connected clients."""
        return len(self._clients)
