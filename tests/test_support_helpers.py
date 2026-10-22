"""Self-tests for the shared test helpers in tests/support/."""

from __future__ import annotations

import pytest

from alphaswarm.inference.concurrency import ConcurrencyController
from tests.support.aio import eventually
from tests.support.controllers import ImmediateController


async def test_eventually_returns_once_predicate_holds() -> None:
    state = {"turns": 0}

    def _ready() -> bool:
        state["turns"] += 1
        return state["turns"] >= 3

    await eventually(_ready, what="third turn")
    assert state["turns"] == 3


async def test_eventually_names_the_condition_on_timeout() -> None:
    with pytest.raises(AssertionError, match="flag set did not become true within 3"):
        await eventually(lambda: False, max_yields=3, what="flag set")


async def test_immediate_controller_counts_and_satisfies_protocol() -> None:
    ctrl = ImmediateController()
    assert isinstance(ctrl, ConcurrencyController)
    await ctrl.start_monitoring()
    await ctrl.acquire()
    await ctrl.acquire()
    ctrl.release()
    ctrl.release(success=False)
    ctrl.report_wave_failures(98, 2)
    await ctrl.stop_monitoring()
    assert (ctrl.acquired, ctrl.released, ctrl.failures) == (2, 2, 1)
    assert (ctrl.max_in_use, ctrl.in_use) == (2, 0)
    assert ctrl.wave_reports == [(98, 2)]
    assert (ctrl.monitoring_starts, ctrl.monitoring_stops) == (1, 1)


async def test_immediate_controller_context_manager_marks_failures() -> None:
    ctrl = ImmediateController()
    with pytest.raises(RuntimeError):
        async with ctrl:
            raise RuntimeError("boom")
    async with ctrl:
        pass
    assert (ctrl.acquired, ctrl.released, ctrl.failures) == (2, 2, 1)
