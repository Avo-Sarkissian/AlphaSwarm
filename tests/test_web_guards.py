"""Route guards shared by the job routes."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from alphaswarm.errors import Neo4jUnavailableError
from alphaswarm.state import JobStatus, StateStore
from alphaswarm.web.errors import ApiError
from alphaswarm.web.guards import (
    load_inference_config_or_422,
    orchestrator_job_running,
    require_complete_cycle,
    require_graph,
    require_orchestrator_free,
    running_job_cycle,
)
from tests.support.web_app import CYCLE_A, CYCLE_B, CYCLE_UNKNOWN, FakeCycleGraph


def _state(graph: object | None = None) -> Any:
    return SimpleNamespace(graph_manager=graph, state_store=StateStore(), settings=object())


def _sim(running: bool = False) -> Any:
    return SimpleNamespace(is_running=running)


def test_require_graph_returns_manager_or_503() -> None:
    graph = FakeCycleGraph()
    assert require_graph(_state(graph)) is graph
    with pytest.raises(ApiError) as exc:
        require_graph(_state(None))
    assert (exc.value.status, exc.value.code) == (503, "graph_unavailable")


async def test_complete_cycle_passes() -> None:
    await require_complete_cycle(_state(FakeCycleGraph({CYCLE_A: "complete"})), _sim(), CYCLE_A)


async def test_unknown_cycle_is_404() -> None:
    with pytest.raises(ApiError) as exc:
        await require_complete_cycle(_state(FakeCycleGraph()), _sim(), CYCLE_UNKNOWN)
    assert (exc.value.status, exc.value.code) == (404, "cycle_not_found")


@pytest.mark.parametrize("status", ["running", "failed", "cancelled"])
async def test_unfinished_cycle_is_422_with_status(status: str) -> None:
    with pytest.raises(ApiError) as exc:
        await require_complete_cycle(_state(FakeCycleGraph({CYCLE_A: status})), _sim(), CYCLE_A)
    assert (exc.value.status, exc.value.code) == (422, "cycle_not_ready")
    assert exc.value.extra == {"cycle_status": status}


async def test_running_simulation_is_409_before_any_graph_read() -> None:
    graph = FakeCycleGraph({CYCLE_A: "complete"})
    with pytest.raises(ApiError) as exc:
        await require_complete_cycle(_state(graph), _sim(running=True), CYCLE_A)
    assert (exc.value.status, exc.value.code) == (409, "simulation_running")
    assert graph.status_calls == []


async def test_graph_outage_propagates_for_the_503_handler() -> None:
    graph = FakeCycleGraph(error=Neo4jUnavailableError("down", op="read_cycle_status"))
    with pytest.raises(Neo4jUnavailableError):
        await require_complete_cycle(_state(graph), _sim(), CYCLE_A)


@pytest.mark.parametrize(
    ("kind", "code"),
    [("report", "report_generation_in_progress"), ("advisory", "advisory_generation_in_progress")],
)
def test_require_orchestrator_free(kind: str, code: str) -> None:
    state = _state()
    require_orchestrator_free(state)
    state.state_store.set_job_status(kind, JobStatus("running", CYCLE_B))
    with pytest.raises(ApiError) as exc:
        require_orchestrator_free(state)
    assert (exc.value.status, exc.value.code) == (409, code)
    assert orchestrator_job_running(state) is True


def test_running_job_cycle_reports_only_running_jobs() -> None:
    state = _state()
    assert running_job_cycle(state, "report") is None
    state.state_store.set_job_status("report", JobStatus("running", CYCLE_A))
    assert running_job_cycle(state, "report") == CYCLE_A
    state.state_store.set_job_status("report", JobStatus("failed", CYCLE_A, "x"))
    assert running_job_cycle(state, "report") is None


async def test_invalid_inference_config_is_422_without_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _broken(settings: object) -> object:
        raise ValueError("Failed to parse inference config at /Users/someone/.secrets/x.json")

    monkeypatch.setattr("alphaswarm.web.guards.load_inference_config", _broken)
    with pytest.raises(ApiError) as exc:
        await load_inference_config_or_422(_state())
    assert (exc.value.status, exc.value.code) == (422, "inference_config_invalid")
    assert "/Users" not in exc.value.message


async def test_unreadable_inference_config_is_422_without_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _denied(settings: object) -> object:
        raise PermissionError(13, "Permission denied", "/Users/someone/.secrets/x.json")

    monkeypatch.setattr("alphaswarm.web.guards.load_inference_config", _denied)
    with pytest.raises(ApiError) as exc:
        await load_inference_config_or_422(_state())
    assert (exc.value.status, exc.value.code) == (422, "inference_config_invalid")
    assert "/Users" not in exc.value.message
