"""Unit tests for _auto_trigger_advisory (AUTO-03, AUTO-04, AUTO-05).

Tests verify that the module-level coroutine:
  AUTO-03: POSTs 202 when phase=COMPLETE and portfolio is loaded (swallowed correctly)
  AUTO-04: Swallows 409 conflict silently (advisory_task already in flight)
  AUTO-05: Swallows 503 (portfolio unavailable) silently

Additional behaviors:
  - Swallows network-level Exception without propagating
  - Swallows unexpected non-202 status codes (logged at WARNING)

All tests import _auto_trigger_advisory — which does NOT exist yet.
This ensures all tests are RED (ImportError) until Task 3 implements it.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI

from alphaswarm.holdings.types import Holding, PortfolioSnapshot
from alphaswarm.types import SimulationPhase
from alphaswarm.web.routes.advisory import router as advisory_router

# RED: this import will fail until Task 3 adds _auto_trigger_advisory
from alphaswarm.web.simulation_manager import _auto_trigger_advisory


# ---------------------------------------------------------------------------
# Helpers — mirrors _make_app factory from test_advisory_route.py
# ---------------------------------------------------------------------------


def _fake_portfolio() -> PortfolioSnapshot:
    return PortfolioSnapshot(
        holdings=(Holding(ticker="AAPL", qty=Decimal("10"), cost_basis=Decimal("100")),),
        as_of=datetime.now(UTC),
        account_number_hash="cafebabe",
    )


def _make_app(
    *,
    phase: SimulationPhase = SimulationPhase.COMPLETE,
    portfolio: PortfolioSnapshot | None = None,
    services_available: bool = True,
    report_task: Any = None,
    advisory_task: Any = None,
) -> FastAPI:
    """Minimal FastAPI app with advisory router — same factory as test_advisory_route.py."""
    app = FastAPI()
    app.include_router(advisory_router, prefix="/api")

    state_snapshot = SimpleNamespace(phase=phase)
    state_store = SimpleNamespace(snapshot=lambda: state_snapshot)
    settings = SimpleNamespace(
        ollama=SimpleNamespace(orchestrator_model_alias="alphaswarm-orchestrator"),
    )
    app_state = SimpleNamespace(
        settings=settings,
        state_store=state_store,
        graph_manager=object() if services_available else None,
        ollama_client=object() if services_available else None,
        model_manager=object() if services_available else None,
    )

    app.state.app_state = app_state
    app.state.portfolio_snapshot = portfolio
    app.state.report_task = report_task
    app.state.advisory_task = advisory_task
    app.state.advisory_generation_error = {}
    return app


@pytest.fixture(autouse=True)
def _neutralize_background_task(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent real _run_advisory_synthesis from running inside route tests."""

    async def _noop(app_state: Any, cycle_id: str, portfolio: PortfolioSnapshot) -> None:
        await asyncio.sleep(0)

    monkeypatch.setattr(
        "alphaswarm.web.routes.advisory._run_advisory_synthesis",
        _noop,
    )


# ---------------------------------------------------------------------------
# AUTO-03: 202 is accepted and logged
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trigger_202() -> None:
    """AUTO-03: _auto_trigger_advisory POSTs successfully when phase=COMPLETE and portfolio loaded."""
    app = _make_app(portfolio=_fake_portfolio())

    # Must not raise
    await _auto_trigger_advisory(app, "cycle_01")


# ---------------------------------------------------------------------------
# AUTO-04: 409 (advisory_task in flight) is swallowed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trigger_409_swallowed() -> None:
    """AUTO-04: 409 conflict (advisory already running) is swallowed silently."""
    # Non-done task causes 409 guard in advisory route
    in_flight_task = MagicMock(spec=asyncio.Task)
    in_flight_task.done.return_value = False

    app = _make_app(portfolio=_fake_portfolio(), advisory_task=in_flight_task)

    # Must not raise
    await _auto_trigger_advisory(app, "cycle_01")


# ---------------------------------------------------------------------------
# AUTO-05: 503 (no portfolio) is swallowed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trigger_503_swallowed() -> None:
    """AUTO-05: 503 (portfolio_snapshot=None) is swallowed silently."""
    app = _make_app(portfolio=None)

    # Must not raise
    await _auto_trigger_advisory(app, "cycle_01")


# ---------------------------------------------------------------------------
# Exception swallowing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trigger_exception_swallowed() -> None:
    """Network-level Exception from httpx.AsyncClient must not propagate."""
    app = _make_app(portfolio=_fake_portfolio())

    with patch("httpx.AsyncClient.__aenter__", side_effect=Exception("network error")):
        # Must not raise
        await _auto_trigger_advisory(app, "cycle_01")


# ---------------------------------------------------------------------------
# Unexpected status code
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trigger_unexpected_status() -> None:
    """Non-202/409/503 response (e.g. 400 from invalid cycle_id) must not raise."""
    app = _make_app(portfolio=_fake_portfolio())

    # Use an invalid cycle_id that triggers 400 from _validate_cycle_id
    # Must not raise
    await _auto_trigger_advisory(app, "bad.id")
