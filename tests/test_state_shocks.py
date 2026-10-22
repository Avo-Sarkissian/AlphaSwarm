"""Shock state and the per-phase shock window in the StateStore."""

from __future__ import annotations

import dataclasses
import json

import pytest

from alphaswarm.state import AppliedShock, ReplayStore, StateStore
from alphaswarm.types import SimulationPhase as P


@pytest.mark.parametrize(
    ("num_rounds", "phase", "expected"),
    [
        (3, P.IDLE, False),
        (3, P.SEEDING, True),
        (3, P.ROUND_1, True),
        (3, P.ROUND_2, True),
        (3, P.ROUND_3, False),
        (3, P.FINALIZING, False),
        (3, P.COMPLETE, False),
        (3, P.REPLAY, False),
        (2, P.SEEDING, True),
        (2, P.ROUND_1, True),
        (2, P.ROUND_2, False),
        (2, P.FINALIZING, False),
    ],
)
async def test_shock_window_by_phase(num_rounds: int, phase: P, expected: bool) -> None:
    store = StateStore()
    store.set_num_rounds(num_rounds)
    await store.set_phase(phase)
    assert store.shock_window_open() is expected
    assert store.snapshot().shock_window_open is expected


def test_pending_and_applied_shocks_appear_in_the_snapshot() -> None:
    store = StateStore()
    store.set_pending_shock("Fed cuts 50bp at emergency session")
    assert store.snapshot().pending_shock == "Fed cuts 50bp at emergency session"
    store.set_pending_shock(None)
    store.record_applied_shock("DOJ files formal antitrust complaint", 2)
    store.record_applied_shock("CEO denies acquisition talks publicly", 3)
    snap = store.snapshot()
    assert snap.pending_shock is None
    assert snap.applied_shocks == (
        AppliedShock("DOJ files formal antitrust complaint", 2),
        AppliedShock("CEO denies acquisition talks publicly", 3),
    )


async def test_a_new_run_clears_applied_shocks() -> None:
    store = StateStore()
    store.record_applied_shock("DOJ files formal antitrust complaint", 2)
    await store.set_phase(P.SEEDING)
    assert store.snapshot().applied_shocks == ()


def test_snapshot_with_shocks_is_json_serialisable() -> None:
    store = StateStore()
    store.record_applied_shock("Treasury yields spike 40bp on inflation print", 2)
    wire = json.loads(json.dumps(dataclasses.asdict(store.snapshot())))
    assert wire["applied_shocks"] == [
        {"text": "Treasury yields spike 40bp on inflation print", "round_num": 2},
    ]
    assert wire["pending_shock"] is None
    assert wire["shock_window_open"] is False


def test_replay_snapshot_has_no_shock_window() -> None:
    snap = ReplayStore("00000000-0000-4000-8000-0000000000a1", {}).snapshot()
    assert snap.shock_window_open is False
    assert snap.applied_shocks == ()
