"""Live TPS = tokens completed in a 10 s wall-clock window, summed over every call."""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

import alphaswarm.state as state_module
from alphaswarm.state import TPS_WINDOW_SECONDS, StateStore
from alphaswarm.types import SimulationPhase


class _Clock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def monotonic(self) -> float:
        return self.now


@pytest.fixture()
def clock(monkeypatch: pytest.MonkeyPatch) -> _Clock:
    fake = _Clock()
    monkeypatch.setattr(state_module, "time", SimpleNamespace(monotonic=fake.monotonic, time=time.time))
    return fake


def test_window_is_ten_seconds() -> None:
    assert TPS_WINDOW_SECONDS == 10.0


def test_tps_sums_parallel_calls_over_the_window(clock: _Clock) -> None:
    store = StateStore()
    for _ in range(4):  # four parallel streams each finish a 150-token reply
        store.record_tokens(150)
    assert store.snapshot().tps == pytest.approx(60.0)  # 600 tokens / 10 s


def test_tokens_leave_the_window_after_ten_seconds(clock: _Clock) -> None:
    store = StateStore()
    store.record_tokens(500)
    clock.now += 9.9
    assert store.snapshot().tps == pytest.approx(50.0)
    clock.now += 0.2
    assert store.snapshot().tps == 0.0


def test_explicit_now_is_honoured(clock: _Clock) -> None:
    store = StateStore()
    store.record_tokens(300, now=clock.now - 20.0)  # already outside the window
    store.record_tokens(100, now=clock.now)
    assert store.snapshot().tps == pytest.approx(10.0)


def test_zero_and_negative_counts_are_ignored(clock: _Clock) -> None:
    store = StateStore()
    store.record_tokens(0)
    store.record_tokens(-5)
    assert store.snapshot().tps == 0.0


async def test_seeding_starts_a_new_tps_window(clock: _Clock) -> None:
    store = StateStore()
    store.record_tokens(400)
    await store.set_phase(SimulationPhase.SEEDING)
    assert store.snapshot().tps == 0.0


def test_update_tps_is_gone() -> None:
    assert not hasattr(StateStore, "update_tps")
