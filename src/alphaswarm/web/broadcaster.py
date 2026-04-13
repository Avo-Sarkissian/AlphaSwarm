"""Broadcaster: 5Hz state snapshot serializer and broadcast loop.

Serializes StateSnapshot to JSON every 200ms, merging drain_rationales()
into the wire format (since snapshot().rationale_entries is always empty).
Broadcasts to all connected WebSocket clients via ConnectionManager.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json

import structlog

from alphaswarm.state import StateStore
from alphaswarm.web.connection_manager import ConnectionManager


def snapshot_to_json(state_store: StateStore) -> str:
    """Serialize current state to JSON, merging drained rationale entries.

    Two-step merge pattern (D-04, D-05, D-06):
    1. snapshot() returns a frozen StateSnapshot with rationale_entries=()
    2. drain_rationales(5) pops up to 5 entries from the rationale queue
    3. asdict(snap) is overridden so rationale_entries contains real data

    Without the explicit override, rationale_entries is always [] in the
    wire format because the frozen snapshot never contains queue entries.
    """
    snap = state_store.snapshot()
    rationales = state_store.drain_rationales(5)
    d = dataclasses.asdict(snap)
    # EXPLICIT OVERRIDE: snap.rationale_entries is always an empty tuple from snapshot().
    # drain_rationales() pops from the rationale queue. We must override the dict entry
    # produced by asdict(snap) or rationale data is silently dropped from the wire format.
    d["rationale_entries"] = [dataclasses.asdict(r) for r in rationales]
    return json.dumps(d)


def start_broadcaster(
    state_store: StateStore,
    connection_manager: ConnectionManager,
) -> asyncio.Task[None]:
    """Create and return a broadcaster task running at ~5Hz.

    The returned task is cancellable -- CancelledError propagates through
    asyncio.sleep(0.2) without suppression (D-07).
    """
    return asyncio.create_task(
        _broadcast_loop(state_store, connection_manager),
        name="broadcaster",
    )


async def _broadcast_loop(
    state_store: StateStore,
    connection_manager: ConnectionManager,
) -> None:
    """Broadcast state snapshot to all WebSocket clients at ~5Hz.

    Log throttling: errors are logged on first occurrence and then every
    10th consecutive failure to avoid 5Hz spam (review concern #6).
    CancelledError is NOT caught (except Exception, not BaseException)
    so task cancellation propagates cleanly through asyncio.sleep(0.2).
    """
    log = structlog.get_logger(component="web.broadcaster")
    consecutive_failures = 0
    while True:
        try:
            message = snapshot_to_json(state_store)
            connection_manager.broadcast(message)
            if consecutive_failures > 0:
                log.info("broadcast_recovered", after_failures=consecutive_failures)
                consecutive_failures = 0
        except Exception:
            consecutive_failures += 1
            # Log once per 10 consecutive failures to avoid 5Hz spam
            if consecutive_failures == 1 or consecutive_failures % 10 == 0:
                log.exception("broadcast_tick_error", consecutive=consecutive_failures)
        await asyncio.sleep(0.2)
