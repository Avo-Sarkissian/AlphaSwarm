"""Broadcaster: ~5 Hz StateFrame ticks that send only when something changed.

Every 200 ms tick decides whether to send. Nothing is serialized while no
client is connected. With clients, a ``StateFrame`` (``alphaswarm.web.wire``)
is built from the live StateStore, or from the active replay's store, and
handed to the ConnectionManager (latest-wins per client) when the state's
version changed, a client connected, or a second passed since the last frame:
that keepalive carries the live memory percent, elapsed time and TPS, which
move without a state mutation (docs/DECISIONS.md#adr-ws-broadcaster).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Final, Protocol

import structlog

from alphaswarm.memory_monitor import memory_used_percent
from alphaswarm.state import ReplayStore, StateStore
from alphaswarm.web.connection_manager import ConnectionManager
from alphaswarm.web.wire import build_frame

log = structlog.get_logger(component="web.broadcaster")

TICK_SECONDS: Final = 0.2
KEEPALIVE_SECONDS: Final = 1.0
STATS_INTERVAL_SECONDS: Final = 60.0

# (frame source version, live store version, connection generation)
FrameKey = tuple[int, int, int]


class ReplaySource(Protocol):
    """The replay view the broadcaster reads; ``ReplayManager`` satisfies it.

    A structural seam instead of an import of ``ReplayManager``, which itself
    imports ``snapshot_to_json`` from this module.
    """

    @property
    def has_store(self) -> bool: ...

    @property
    def store(self) -> ReplayStore: ...


def _host_memory_percent() -> float:
    """Live RAM %, read fresh every tick from the governor's memory signal.

    memory_monitor.memory_used_percent is the same source the governor uses
    (docs/DECISIONS.md#p3-d-12), so the overlay shows what the governor sees.
    """
    try:
        return memory_used_percent()
    except Exception:  # pragma: no cover -- the kernel read and psutil do not raise
        log.warning("memory_read_failed")
        return 0.0


def snapshot_to_json(
    state_store: StateStore,
    replay_manager: ReplaySource | None = None,
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


def frame_key(state_store: StateStore, replay_manager: ReplaySource | None, generation: int) -> FrameKey:
    """What a frame depends on besides the clock.

    The source store's version (the replay store once it is committed), the live
    store's version (job status always comes from it) and the connection
    generation (a new client needs a frame).
    """
    if replay_manager is not None and replay_manager.has_store:
        source_version = replay_manager.store.version
    else:
        source_version = state_store.version
    return (source_version, state_store.version, generation)


@dataclass
class BroadcastState:
    """Loop bookkeeping: the last frame sent and the counters of this minute."""

    last_key: FrameKey | None = None
    last_sent_at: float = float("-inf")
    window_started_at: float = 0.0
    ticks: int = 0
    serializations: int = 0
    skipped_idle: int = 0
    skipped_unchanged: int = 0

    def take_stats(self, now: float) -> dict[str, int] | None:
        """The counters once STATS_INTERVAL_SECONDS have passed (then reset), else None."""
        if now - self.window_started_at < STATS_INTERVAL_SECONDS:
            return None
        stats = {
            "ticks": self.ticks,
            "serializations": self.serializations,
            "skipped_idle": self.skipped_idle,
            "skipped_unchanged": self.skipped_unchanged,
        }
        self.window_started_at = now
        self.ticks = self.serializations = self.skipped_idle = self.skipped_unchanged = 0
        return stats


def broadcast_tick(
    state_store: StateStore,
    connection_manager: ConnectionManager,
    replay_manager: ReplaySource | None,
    state: BroadcastState,
    *,
    now: float,
) -> bool:
    """One tick; True when a frame was serialized and queued."""
    state.ticks += 1
    if connection_manager.client_count == 0:
        state.skipped_idle += 1
        return False
    key = frame_key(state_store, replay_manager, connection_manager.generation)
    if key == state.last_key and now - state.last_sent_at < KEEPALIVE_SECONDS:
        state.skipped_unchanged += 1
        return False
    connection_manager.broadcast(snapshot_to_json(state_store, replay_manager=replay_manager))
    state.serializations += 1
    state.last_key = key
    state.last_sent_at = now
    return True


def start_broadcaster(
    state_store: StateStore,
    connection_manager: ConnectionManager,
    replay_manager: ReplaySource | None = None,
) -> asyncio.Task[None]:
    """Create and return a broadcaster task running at ~5Hz.

    The returned task is cancellable -- CancelledError propagates through
    asyncio.sleep(TICK_SECONDS) without suppression (docs/DECISIONS.md#p30-d-07).
    """
    return asyncio.create_task(
        _broadcast_loop(state_store, connection_manager, replay_manager),
        name="broadcaster",
    )


async def _broadcast_loop(
    state_store: StateStore,
    connection_manager: ConnectionManager,
    replay_manager: ReplaySource | None = None,
) -> None:
    """Tick every TICK_SECONDS and log the counters once a minute.

    Errors are logged on the first failure and then every 10th consecutive
    failure. CancelledError is not caught, so cancellation stays clean.
    """
    state = BroadcastState(window_started_at=time.monotonic())
    consecutive_failures = 0
    while True:
        now = time.monotonic()
        try:
            broadcast_tick(state_store, connection_manager, replay_manager, state, now=now)
            if consecutive_failures > 0:
                log.info("broadcast_recovered", after_failures=consecutive_failures)
                consecutive_failures = 0
        except Exception:
            consecutive_failures += 1
            if consecutive_failures == 1 or consecutive_failures % 10 == 0:
                log.exception("broadcast_tick_error", consecutive=consecutive_failures)
        stats = state.take_stats(now)
        if stats is not None:
            log.info("broadcast_stats", clients=connection_manager.client_count, **stats)
        await asyncio.sleep(TICK_SECONDS)
