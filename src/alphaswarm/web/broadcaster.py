"""Broadcaster: ~5 Hz StateFrame serializer and broadcast loop.

Every tick builds one ``StateFrame`` (``alphaswarm.web.wire``) from the live
StateStore, or from the active replay's store, and hands the JSON to the
ConnectionManager, which applies drop-oldest backpressure per client
(docs/DECISIONS.md#adr-ws-broadcaster).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import psutil
import structlog

from alphaswarm.state import StateStore
from alphaswarm.web.connection_manager import ConnectionManager
from alphaswarm.web.wire import build_frame

if TYPE_CHECKING:
    from alphaswarm.web.replay_manager import ReplayManager

log = structlog.get_logger(component="web.broadcaster")


def _host_memory_percent() -> float:
    """Live host RAM %, read fresh every tick (psutil does not cache)."""
    try:
        return float(psutil.virtual_memory().percent)
    except Exception:  # pragma: no cover -- macOS host_statistics64 does not raise
        log.warning("psutil_read_failed")
        return 0.0


def snapshot_to_json(
    state_store: StateStore,
    replay_manager: ReplayManager | None = None,
) -> str:
    """Serialize the current StateFrame to JSON.

    The replay store's snapshot is used once a replay store is committed
    (``has_store``, not ``is_active``: during replay start-up there is no store
    yet, docs/DECISIONS.md#f-24). Job status always comes from the live store.
    """
    if replay_manager is not None and replay_manager.has_store:
        snapshot = replay_manager.store.snapshot()
    else:
        snapshot = state_store.snapshot()
    frame = build_frame(
        snapshot,
        jobs=state_store.job_statuses(),
        memory_percent=_host_memory_percent(),
    )
    return frame.model_dump_json()


def start_broadcaster(
    state_store: StateStore,
    connection_manager: ConnectionManager,
    replay_manager: ReplayManager | None = None,
) -> asyncio.Task[None]:
    """Create and return a broadcaster task running at ~5Hz.

    The returned task is cancellable -- CancelledError propagates through
    asyncio.sleep(0.2) without suppression (docs/DECISIONS.md#p30-d-07).
    """
    return asyncio.create_task(
        _broadcast_loop(state_store, connection_manager, replay_manager),
        name="broadcaster",
    )


async def _broadcast_loop(
    state_store: StateStore,
    connection_manager: ConnectionManager,
    replay_manager: ReplayManager | None = None,
) -> None:
    """Broadcast the StateFrame to all WebSocket clients at ~5Hz.

    Errors are logged on the first failure and then every 10th consecutive
    failure. CancelledError is not caught, so cancellation stays clean.
    """
    consecutive_failures = 0
    while True:
        try:
            message = snapshot_to_json(state_store, replay_manager=replay_manager)
            connection_manager.broadcast(message)
            if consecutive_failures > 0:
                log.info("broadcast_recovered", after_failures=consecutive_failures)
                consecutive_failures = 0
        except Exception:
            consecutive_failures += 1
            if consecutive_failures == 1 or consecutive_failures % 10 == 0:
                log.exception("broadcast_tick_error", consecutive=consecutive_failures)
        await asyncio.sleep(0.2)
