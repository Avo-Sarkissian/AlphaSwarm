"""Unit tests for SimulationManager auto-advisory trigger (AUTO-01, AUTO-02).

Tests verify:
  AUTO-01: _run() captures cycle_id from SimulationResult and stores on self._last_cycle_id
  AUTO-02: _on_task_done() schedules on_complete callback on success only
           (cancelled / exception tasks must NOT trigger callback)
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from alphaswarm.web.simulation_manager import SimulationManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app_state() -> Any:
    """Minimal app_state stub accepted by SimulationManager."""
    state_store = SimpleNamespace(
        snapshot=MagicMock(return_value=SimpleNamespace(phase="complete")),
        set_phase=AsyncMock(),
    )
    return SimpleNamespace(
        settings=SimpleNamespace(
            ollama=SimpleNamespace(orchestrator_model_alias="test-model"),
            governor=MagicMock(),  # Task 15a: build_controller receives settings.governor
        ),
        state_store=state_store,
        ollama_client=object(),
        graph_manager=object(),
        model_manager=object(),
        governor=MagicMock(),
        personas=[],
        market_provider=None,
        news_provider=None,
    )


def _make_task(*, cancelled: bool = False, exception: BaseException | None = None) -> MagicMock:
    """Return a mock asyncio.Task that reports the given completion state."""
    t = MagicMock(spec=asyncio.Task)
    t.cancelled.return_value = cancelled
    t.exception.return_value = exception
    return t


def _build_manager(
    on_complete: Callable[[str], Awaitable[None]] | None = None,
) -> SimulationManager:
    """Construct a SimulationManager with a minimal stub app_state."""
    return SimulationManager(
        app_state=_make_app_state(),
        brackets=[],
        on_complete=on_complete,
    )


# ---------------------------------------------------------------------------
# AUTO-01: _run() stores cycle_id from SimulationResult
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cycle_id_stored(monkeypatch: pytest.MonkeyPatch) -> None:
    """AUTO-01: _run() must store result.cycle_id on self._last_cycle_id."""
    fake_result = SimpleNamespace(cycle_id="abc123")

    async def _fake_run_simulation(**kwargs: Any) -> SimpleNamespace:
        return fake_result

    # run_simulation is imported locally inside _run(), so patch at source module.
    monkeypatch.setattr(
        "alphaswarm.simulation.run_simulation",
        _fake_run_simulation,
    )

    # Task 15a: _run now calls load_inference_config + build_providers/build_controller
    # before run_simulation. Patch these so the test works with the SimpleNamespace stub.
    fake_built = SimpleNamespace(
        orchestrator=SimpleNamespace(aclose=AsyncMock()),
        worker=SimpleNamespace(aclose=AsyncMock()),
        budget_meter=object(),
    )
    monkeypatch.setattr(
        "alphaswarm.config.load_inference_config", lambda *a, **kw: SimpleNamespace()
    )
    monkeypatch.setattr("alphaswarm.inference.factory.build_providers", lambda *a, **kw: fake_built)
    monkeypatch.setattr(
        "alphaswarm.inference.factory.build_controller", lambda *a, **kw: MagicMock()
    )
    monkeypatch.setattr("alphaswarm.inference.factory.inference_mode", lambda *a, **kw: "local")

    manager = _build_manager()
    # _run() does not need the lock to be held — acquire just so release inside
    # _on_task_done won't error if called; here we call _run() directly.
    await manager._run("seed-text")

    assert manager._last_cycle_id == "abc123"


# ---------------------------------------------------------------------------
# AUTO-02: _on_task_done schedules callback only on success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_done_callback_schedules_task() -> None:
    """AUTO-02: successful task completion schedules on_complete with cycle_id."""
    received: list[str] = []

    async def _on_complete(cycle_id: str) -> None:
        received.append(cycle_id)

    manager = _build_manager(on_complete=_on_complete)
    manager._last_cycle_id = "abc123"

    # Acquire lock so _on_task_done can release it
    await manager._lock.acquire()

    task = _make_task(cancelled=False, exception=None)
    manager._on_task_done(task)

    # Let the scheduled coroutine execute
    await asyncio.sleep(0)

    assert received == ["abc123"], f"Expected ['abc123'], got {received}"


@pytest.mark.asyncio
async def test_no_trigger_on_cancel() -> None:
    """AUTO-02: cancelled task must NOT call on_complete."""
    received: list[str] = []

    async def _on_complete(cycle_id: str) -> None:
        received.append(cycle_id)

    manager = _build_manager(on_complete=_on_complete)
    manager._last_cycle_id = "abc123"

    await manager._lock.acquire()
    task = _make_task(cancelled=True, exception=None)
    manager._on_task_done(task)
    await asyncio.sleep(0)

    assert received == [], f"Expected no callback on cancel, got {received}"


@pytest.mark.asyncio
async def test_no_trigger_on_exception() -> None:
    """AUTO-02: failed task must NOT call on_complete."""
    received: list[str] = []

    async def _on_complete(cycle_id: str) -> None:
        received.append(cycle_id)

    manager = _build_manager(on_complete=_on_complete)
    manager._last_cycle_id = "abc123"

    await manager._lock.acquire()
    task = _make_task(cancelled=False, exception=RuntimeError("boom"))
    manager._on_task_done(task)
    await asyncio.sleep(0)

    assert received == [], f"Expected no callback on exception, got {received}"


@pytest.mark.asyncio
async def test_on_complete_none_is_safe() -> None:
    """_on_task_done is safe when on_complete=None and _last_cycle_id=None."""
    manager = _build_manager(on_complete=None)
    manager._last_cycle_id = None  # type: ignore[assignment]

    await manager._lock.acquire()
    task = _make_task(cancelled=False, exception=None)

    # Must not raise
    manager._on_task_done(task)
    await asyncio.sleep(0)
