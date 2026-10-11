"""Handlers that end a background task log the exception itself.

A bare error=str(exc) loses the type and the stack; exc_info= lets the JSON
renderer emit a structured traceback (without locals).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI


class _RecordingLog:
    """Stand-in for a module-level structlog logger that records every call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def __getattr__(self, level: str) -> Callable[..., None]:
        def _log(event: str, **kw: Any) -> None:
            self.calls.append((level, event, kw))

        return _log

    def kwargs_for(self, event: str) -> dict[str, Any]:
        return next(kw for _level, name, kw in self.calls if name == event)


async def _failed_task(exc: BaseException) -> asyncio.Task[None]:
    async def _fail() -> None:
        raise exc

    task: asyncio.Task[None] = asyncio.get_running_loop().create_task(_fail())
    await asyncio.wait({task})
    return task


async def test_simulation_failure_is_logged_with_exc_info(monkeypatch: pytest.MonkeyPatch) -> None:
    from alphaswarm.web import simulation_manager as module

    log = _RecordingLog()
    monkeypatch.setattr(module, "log", log)
    boom = RuntimeError("round 2 exploded")
    manager = module.SimulationManager(MagicMock(), [])
    await manager._lock.acquire()  # _on_task_done releases the run lock

    manager._on_task_done(await _failed_task(boom))

    assert log.kwargs_for("simulation_failed") == {"error": "round 2 exploded", "exc_info": boom}


async def test_report_task_failure_is_logged_with_exc_info(monkeypatch: pytest.MonkeyPatch) -> None:
    from alphaswarm.web.routes import report as module

    log = _RecordingLog()
    monkeypatch.setattr(module, "log", log)
    boom = RuntimeError("template exploded")
    app = FastAPI()

    module._on_report_task_done(await _failed_task(boom), "cycle-1", app)

    assert log.kwargs_for("report_task_exception_recorded")["exc_info"] is boom
    assert app.state.report_generation_error["cycle-1"]["error"] == "report_generation_failed"


async def test_advisory_task_failure_is_logged_with_exc_info(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from alphaswarm.web.routes import advisory as module

    log = _RecordingLog()
    monkeypatch.setattr(module, "log", log)
    boom = RuntimeError("synthesis exploded")
    app = FastAPI()

    module._on_advisory_task_done(await _failed_task(boom), "cycle-1", app)

    assert log.kwargs_for("advisory_task_exception_recorded")["exc_info"] is boom
    assert app.state.advisory_generation_error["cycle-1"]["error"] == "advisory_generation_failed"
