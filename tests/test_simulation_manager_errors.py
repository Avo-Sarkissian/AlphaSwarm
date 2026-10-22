"""SimulationManager publishes UI-safe RunErrors (docs/DECISIONS.md#adr-taskgroup-dispatch)."""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Awaitable, Callable, Iterator
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alphaswarm.errors import (
    BudgetExceededError,
    InferenceConfigError,
    RoundFailedError,
    run_error_from_exception,
)
from alphaswarm.state import StateStore
from alphaswarm.types import SimulationPhase
from alphaswarm.web.broadcaster import snapshot_to_json
from alphaswarm.web.simulation_manager import SimulationManager

SEED = "ZZZT Holdings is in late-stage talks to acquire QQQX Robotics for $4.2B in cash."


@contextlib.contextmanager
def _patched_run(
    run: Callable[..., Awaitable[Any]],
    *,
    load: Callable[..., Any] | None = None,
) -> Iterator[AsyncMock]:
    built = MagicMock()
    built.orchestrator.aclose = AsyncMock()
    built.worker.aclose = AsyncMock()
    load_patch = (
        patch("alphaswarm.config.load_inference_config", return_value=MagicMock())
        if load is None
        else patch("alphaswarm.config.load_inference_config", side_effect=load)
    )
    run_mock = AsyncMock(side_effect=run)
    with (
        load_patch,
        patch("alphaswarm.inference.factory.build_providers", return_value=built),
        patch("alphaswarm.inference.factory.build_controller", return_value=MagicMock()),
        patch("alphaswarm.inference.factory.inference_mode", return_value="local"),
        patch("alphaswarm.simulation.run_simulation", new=run_mock),
    ):
        yield run_mock


def _manager() -> tuple[SimulationManager, StateStore]:
    store = StateStore()
    app_state = MagicMock()
    app_state.state_store = store
    return SimulationManager(app_state, brackets=[]), store


async def _finish(sm: SimulationManager) -> None:
    task = sm._task
    assert task is not None
    await task


async def test_budget_error_sets_last_error_with_round() -> None:
    sm, store = _manager()

    async def _fail(**_: object) -> None:
        await store.set_phase(SimulationPhase.ROUND_2)
        await store.set_round(2)
        raise BudgetExceededError(Decimal("5.00"), Decimal("4.00"))

    with _patched_run(_fail):
        await sm.start(SEED)
        with pytest.raises(BudgetExceededError):
            await _finish(sm)

    err = store.last_error
    assert err is not None
    assert (err.code, err.round_num) == ("budget_exceeded", 2)
    snap = store.snapshot()
    assert snap.last_error == err
    assert snap.phase is SimulationPhase.IDLE


async def test_round_failure_sets_last_error_with_round() -> None:
    sm, store = _manager()

    async def _fail(**_: object) -> None:
        await store.set_phase(SimulationPhase.ROUND_1)
        await store.set_round(1)
        raise RoundFailedError(1, 100, 100, 50.0)

    with _patched_run(_fail):
        await sm.start(SEED)
        with pytest.raises(RoundFailedError):
            await _finish(sm)

    assert store.last_error is not None
    assert (store.last_error.code, store.last_error.round_num) == ("round_failed", 1)


async def test_failure_outside_a_round_has_no_round_number() -> None:
    sm, store = _manager()

    async def _fail(**_: object) -> None:
        await store.set_phase(SimulationPhase.SEEDING)
        raise RuntimeError("orchestrator crashed")

    with _patched_run(_fail):
        await sm.start(SEED)
        with pytest.raises(RuntimeError):
            await _finish(sm)

    assert store.last_error is not None
    assert store.last_error.code == "internal_error"
    assert store.last_error.round_num is None


async def test_cancel_leaves_last_error_empty() -> None:
    sm, store = _manager()
    entered = asyncio.Event()

    async def _block(**_: object) -> None:
        entered.set()
        await asyncio.Event().wait()

    with _patched_run(_block):
        await sm.start(SEED)
        await asyncio.wait_for(entered.wait(), timeout=2)
        sm.stop()
        with pytest.raises(asyncio.CancelledError):
            await _finish(sm)

    assert store.last_error is None
    assert store.snapshot().phase is SimulationPhase.IDLE


async def test_start_clears_previous_error() -> None:
    sm, store = _manager()
    await store.set_last_error(run_error_from_exception(RuntimeError("old"), round_num=None))

    async def _ok(**_: object) -> MagicMock:
        return MagicMock(cycle_id="00000000-0000-4000-8000-000000000006")

    with _patched_run(_ok):
        await sm.start(SEED)
        assert store.last_error is None  # cleared before the task even runs
        await _finish(sm)


async def test_invalid_inference_config_is_wrapped_without_leaking() -> None:
    sm, store = _manager()

    def _bad_config(*_: object, **__: object) -> object:
        raise ValueError(
            "Failed to parse inference config at /Users/someone/.secrets/inference.json: "
            "api_key input_value='sk-test-SECRET-1234'"
        )

    with _patched_run(AsyncMock(), load=_bad_config) as run_mock:
        await sm.start(SEED)
        with pytest.raises(InferenceConfigError) as exc_info:
            await _finish(sm)

    run_mock.assert_not_awaited()
    # Raised `from None`: tracebacks never render the ValueError text.
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__ is True
    err = store.last_error
    assert err is not None
    assert err.code == "inference_config_invalid"
    assert "SECRET" not in err.message
    assert ".secrets" not in err.message


async def test_last_error_reaches_the_websocket_frame() -> None:
    store = StateStore()
    await store.set_last_error(
        run_error_from_exception(RoundFailedError(3, 90, 100, 50.0), round_num=3)
    )
    frame = json.loads(snapshot_to_json(store))
    assert frame["last_error"]["code"] == "round_failed"
    assert frame["last_error"]["round_num"] == 3
    assert isinstance(frame["last_error"]["ts"], float)
