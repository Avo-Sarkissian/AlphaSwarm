"""ConnectionManager behaviour through its public API.

Drop-oldest per-client backpressure and isolation between clients follow
docs/DECISIONS.md#adr-ws-broadcaster; nothing here touches private state.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

from alphaswarm.web.connection_manager import CLIENT_QUEUE_MAXSIZE, ConnectionManager
from tests.support.aio import eventually

if TYPE_CHECKING:
    from fastapi import WebSocket


class _FakeWebSocket:
    """Stand-in for the two WebSocket methods ConnectionManager calls."""

    def __init__(self, *, gate: asyncio.Event | None = None, fail_on_send: bool = False) -> None:
        self.accepted = False
        self.sent: list[str] = []
        self.send_started = asyncio.Event()
        self._gate = gate
        self._fail_on_send = fail_on_send

    async def accept(self) -> None:
        self.accepted = True

    async def send_text(self, data: str) -> None:
        self.send_started.set()
        if self._fail_on_send:
            raise RuntimeError("socket closed by the browser")
        if self._gate is not None:
            await self._gate.wait()
        self.sent.append(data)


def _ws(fake: _FakeWebSocket) -> WebSocket:
    return cast("WebSocket", fake)


async def test_slow_client_keeps_only_the_newest_frames() -> None:
    manager = ConnectionManager()
    gate = asyncio.Event()
    slow = _FakeWebSocket(gate=gate)
    await manager.connect(_ws(slow))
    assert slow.accepted
    manager.broadcast("warmup")
    await slow.send_started.wait()  # the writer holds "warmup" and is stuck in send_text
    flood = CLIENT_QUEUE_MAXSIZE + 50
    for i in range(flood):
        manager.broadcast(f"m{i}")  # synchronous: never awaits the slow socket
    assert slow.sent == []
    gate.set()
    expected = ["warmup"] + [f"m{i}" for i in range(flood - CLIENT_QUEUE_MAXSIZE, flood)]
    await eventually(lambda: len(slow.sent) == len(expected), what="slow client to drain")
    assert slow.sent == expected
    await manager.disconnect(_ws(slow))
    assert manager.client_count == 0


async def test_slow_client_does_not_delay_other_clients() -> None:
    manager = ConnectionManager()
    gate = asyncio.Event()
    slow = _FakeWebSocket(gate=gate)
    fast = _FakeWebSocket()
    await manager.connect(_ws(slow))
    await manager.connect(_ws(fast))
    manager.broadcast("warmup")
    await slow.send_started.wait()
    flood = CLIENT_QUEUE_MAXSIZE + 50
    for i in range(flood):
        manager.broadcast(f"m{i}")
    newest = f"m{flood - 1}"
    await eventually(lambda: fast.sent[-1:] == [newest], what="fast client to get the newest frame")
    assert slow.sent == []  # still blocked, and it held nobody else up
    gate.set()
    await eventually(lambda: slow.sent[-1:] == [newest], what="slow client to catch up")
    await manager.disconnect(_ws(slow))
    await manager.disconnect(_ws(fast))


async def test_disconnect_cancels_a_writer_blocked_in_send() -> None:
    manager = ConnectionManager()
    slow = _FakeWebSocket(gate=asyncio.Event())
    await manager.connect(_ws(slow))
    manager.broadcast("stuck")
    await slow.send_started.wait()
    await manager.disconnect(_ws(slow))
    assert manager.client_count == 0
    manager.broadcast("after")  # no queue left for this client; must not raise
    assert slow.sent == []


async def test_client_that_errors_mid_send_is_dropped_and_others_continue() -> None:
    manager = ConnectionManager()
    broken = _FakeWebSocket(fail_on_send=True)
    healthy = _FakeWebSocket()
    await manager.connect(_ws(broken))
    await manager.connect(_ws(healthy))
    manager.broadcast("one")
    await eventually(lambda: manager.client_count == 1, what="broken client to be dropped")
    manager.broadcast("two")
    await eventually(lambda: healthy.sent == ["one", "two"], what="healthy client to keep going")
    await manager.disconnect(_ws(healthy))


def test_queue_is_latest_wins() -> None:
    assert CLIENT_QUEUE_MAXSIZE == 1


async def test_stuck_client_gets_only_the_newest_frame_when_it_frees_up() -> None:
    manager = ConnectionManager()
    gate = asyncio.Event()
    slow = _FakeWebSocket(gate=gate)
    await manager.connect(_ws(slow))
    manager.broadcast("held")
    await slow.send_started.wait()  # the writer is stuck sending "held"
    for i in range(20):
        manager.broadcast(f"m{i}")
    gate.set()
    await eventually(lambda: slow.sent == ["held", "m19"], what="only the newest frame after the held one")
    await manager.disconnect(_ws(slow))


async def test_generation_counts_connections() -> None:
    manager = ConnectionManager()
    assert manager.generation == 0
    first, second = _FakeWebSocket(), _FakeWebSocket()
    await manager.connect(_ws(first))
    await manager.connect(_ws(second))
    await manager.disconnect(_ws(first))
    assert (manager.generation, manager.client_count) == (2, 1)
    await manager.disconnect(_ws(second))
