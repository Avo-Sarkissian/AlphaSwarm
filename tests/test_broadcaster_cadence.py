"""Broadcaster cadence: idle skip, unchanged-state skip, 1 s keepalive, new clients."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, cast

import pytest

import alphaswarm.web.broadcaster as broadcaster_module
from alphaswarm.state import AgentState, JobStatus, ReplayStore, StateStore
from alphaswarm.types import SignalType
from alphaswarm.web.broadcaster import (
    KEEPALIVE_SECONDS,
    STATS_INTERVAL_SECONDS,
    TICK_SECONDS,
    BroadcastState,
    broadcast_tick,
    frame_key,
)
from alphaswarm.web.connection_manager import ConnectionManager

CYCLE_A = "00000000-0000-4000-8000-0000000000a1"


class _Connections:
    """The members of ConnectionManager the broadcaster uses."""

    def __init__(self, clients: int = 0) -> None:
        self.client_count = clients
        self.generation = clients
        self.sent: list[str] = []

    def connect(self) -> None:
        self.client_count += 1
        self.generation += 1

    def broadcast(self, message: str) -> None:
        self.sent.append(message)


@pytest.fixture(autouse=True)
def _host_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("alphaswarm.web.broadcaster.memory_used_percent", lambda: 50.0)


def _tick(store: StateStore, conns: _Connections, state: BroadcastState, now: float, replay: Any = None) -> bool:
    return broadcast_tick(store, cast(ConnectionManager, conns), replay, state, now=now)


def test_cadence_constants() -> None:
    assert (TICK_SECONDS, KEEPALIVE_SECONDS, STATS_INTERVAL_SECONDS) == (0.2, 1.0, 60.0)


def test_no_clients_means_no_serialization(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def counting_snapshot(*args: object, **kwargs: object) -> str:
        calls.append(1)
        return "{}"

    monkeypatch.setattr(broadcaster_module, "snapshot_to_json", counting_snapshot)
    store, conns, state = StateStore(), _Connections(), BroadcastState()
    assert not any(_tick(store, conns, state, i * TICK_SECONDS) for i in range(50))
    assert (calls, conns.sent, state.serializations, state.skipped_idle) == ([], [], 0, 50)


def test_first_tick_with_a_client_sends_a_frame() -> None:
    store, conns, state = StateStore(), _Connections(clients=1), BroadcastState()
    assert _tick(store, conns, state, 0.0)
    assert json.loads(conns.sent[0])["schema_version"] == 1


def test_unchanged_state_is_not_reserialized_within_a_second() -> None:
    store, conns, state = StateStore(), _Connections(clients=1), BroadcastState()
    assert [_tick(store, conns, state, t) for t in (0.0, 0.2, 0.4, 0.6, 0.8)] == [
        True,
        False,
        False,
        False,
        False,
    ]
    assert state.skipped_unchanged == 4


def test_unchanged_state_is_resent_once_per_second() -> None:
    store, conns, state = StateStore(), _Connections(clients=1), BroadcastState()
    times = [round(i * TICK_SECONDS, 1) for i in range(11)]  # 0.0 ... 2.0
    assert [t for t in times if _tick(store, conns, state, t)] == [0.0, 1.0, 2.0]


async def test_a_mutation_is_sent_on_the_next_tick() -> None:
    store, conns, state = StateStore(), _Connections(clients=1), BroadcastState()
    assert _tick(store, conns, state, 0.0)
    await store.set_round(2)
    assert _tick(store, conns, state, 0.2)
    assert json.loads(conns.sent[-1])["round_num"] == 2


def test_new_client_gets_a_frame_on_the_next_tick() -> None:
    store, conns, state = StateStore(), _Connections(clients=1), BroadcastState()
    assert _tick(store, conns, state, 0.0)
    assert not _tick(store, conns, state, 0.2)
    conns.connect()
    assert _tick(store, conns, state, 0.4)
    assert len(conns.sent) == 2


def test_replay_changes_and_live_job_changes_are_sent() -> None:
    live, conns, state = StateStore(), _Connections(clients=1), BroadcastState()
    replay = ReplayStore(
        CYCLE_A,
        {("quants_01", 1): AgentState(SignalType.BUY, 0.8), ("quants_01", 2): AgentState(SignalType.SELL, 0.6)},
        num_rounds=2,
    )
    replay.set_round(1)
    manager = SimpleNamespace(has_store=True, store=replay)
    assert _tick(live, conns, state, 0.0, manager)
    replay.set_round(2)
    assert _tick(live, conns, state, 0.2, manager)
    live.set_job_status("report", JobStatus("running", CYCLE_A))
    assert _tick(live, conns, state, 0.4, manager)
    frame = json.loads(conns.sent[-1])
    assert (frame["mode"], frame["round_num"], frame["jobs"]["report"]["state"]) == ("replay", 2, "running")


def test_frame_key_tracks_source_live_store_and_generation() -> None:
    live, replay = StateStore(), ReplayStore(CYCLE_A, {})
    assert frame_key(live, None, 3) == (live.version, live.version, 3)
    committed: Any = SimpleNamespace(has_store=True, store=replay)
    assert frame_key(live, committed, 3) == (replay.version, live.version, 3)
    starting: Any = SimpleNamespace(has_store=False)
    assert frame_key(live, starting, 0) == (live.version, live.version, 0)


def test_stats_are_taken_once_per_minute() -> None:
    store, conns, state = StateStore(), _Connections(), BroadcastState(window_started_at=0.0)
    for i in range(10):
        _tick(store, conns, state, i * TICK_SECONDS)
    assert state.take_stats(30.0) is None
    assert state.take_stats(60.0) == {
        "ticks": 10,
        "serializations": 0,
        "skipped_idle": 10,
        "skipped_unchanged": 0,
    }
    assert (state.take_stats(61.0), state.ticks) == (None, 0)
