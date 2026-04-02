"""Tests for TUI interview components (Phase 14 Plan 02).

Tests AgentCell click gating, InterviewScreen composition,
cycle_id initialization, and action_open_interview guard logic.
Uses unittest.mock for graph_manager, ollama_client, and state_store.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alphaswarm.state import StateSnapshot, StateStore
from alphaswarm.tui import AgentCell, AlphaSwarmApp, InterviewScreen
from alphaswarm.types import SimulationPhase


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_app_state(
    phase: SimulationPhase = SimulationPhase.IDLE,
) -> MagicMock:
    """Create a mock AppState with a real StateStore set to the given phase."""
    mock = MagicMock()
    store = StateStore()
    # Manually set the phase without awaiting (for sync test setup)
    store._phase = phase
    mock.state_store = store
    mock.ollama_client = None
    mock.model_manager = None
    mock.graph_manager = None
    return mock


def _make_personas() -> list:
    """Create 100 minimal persona objects for grid rendering."""
    from alphaswarm.config import generate_personas, load_bracket_configs

    brackets = load_bracket_configs()
    return generate_personas(brackets)


def _make_brackets() -> list:
    from alphaswarm.config import load_bracket_configs

    return load_bracket_configs()


def _make_settings():
    from alphaswarm.config import AppSettings

    return AppSettings()


def _make_app(
    phase: SimulationPhase = SimulationPhase.IDLE,
    cycle_id: str | None = None,
) -> AlphaSwarmApp:
    """Create an AlphaSwarmApp with a configurable phase and cycle_id."""
    app = AlphaSwarmApp(
        rumor="test rumor",
        app_state=_make_mock_app_state(phase=phase),
        personas=_make_personas(),
        brackets=_make_brackets(),
        settings=_make_settings(),
    )
    app._cycle_id = cycle_id
    return app


# ---------------------------------------------------------------------------
# AgentCell click gating tests
# ---------------------------------------------------------------------------


async def test_agent_cell_click_during_simulation_shows_notification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Clicking AgentCell during active simulation shows 'Simulation in progress' warning."""
    for key in list(os.environ):
        if key.startswith("ALPHASWARM_"):
            monkeypatch.delenv(key, raising=False)

    app = _make_app(phase=SimulationPhase.ROUND_1)

    async with app.run_test(size=(80, 30)) as pilot:
        cells = list(app.query("AgentCell"))
        assert len(cells) > 0

        # Mock notify to capture calls
        with patch.object(app, "notify") as mock_notify:
            cells[0].on_click()
            mock_notify.assert_called_once_with(
                "Simulation in progress", severity="warning"
            )


async def test_agent_cell_click_when_complete_calls_action_open_interview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Clicking AgentCell when COMPLETE calls action_open_interview with agent_id."""
    for key in list(os.environ):
        if key.startswith("ALPHASWARM_"):
            monkeypatch.delenv(key, raising=False)

    app = _make_app(phase=SimulationPhase.COMPLETE)

    async with app.run_test(size=(80, 30)) as pilot:
        cells = list(app.query("AgentCell"))
        assert len(cells) > 0

        with patch.object(app, "action_open_interview") as mock_action:
            cells[0].on_click()
            mock_action.assert_called_once_with(cells[0].agent_id)


# ---------------------------------------------------------------------------
# InterviewScreen composition test
# ---------------------------------------------------------------------------


def test_interview_screen_compose_has_required_widgets() -> None:
    """InterviewScreen.compose() yields Static header, RichLog, Static status, Input."""
    from textual.widgets import Input, RichLog, Static

    screen = InterviewScreen(
        agent_id="quants_01",
        cycle_id="cycle-test-123",
        graph_manager=MagicMock(),
        ollama_client=MagicMock(),
        worker_model="alphaswarm-worker",
    )

    widgets = list(screen.compose())

    # Should yield 4 widgets: header (Static), transcript (RichLog), status (Static), input (Input)
    assert len(widgets) == 4
    assert isinstance(widgets[0], Static)  # header
    assert isinstance(widgets[1], RichLog)  # transcript
    assert isinstance(widgets[2], Static)  # status
    assert isinstance(widgets[3], Input)   # input


# ---------------------------------------------------------------------------
# cycle_id initialization test
# ---------------------------------------------------------------------------


def test_cycle_id_initialized_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """AlphaSwarmApp._cycle_id is None after init."""
    for key in list(os.environ):
        if key.startswith("ALPHASWARM_"):
            monkeypatch.delenv(key, raising=False)

    app = AlphaSwarmApp(
        rumor="test rumor",
        app_state=_make_mock_app_state(),
        personas=_make_personas(),
        brackets=_make_brackets(),
        settings=_make_settings(),
    )
    assert app._cycle_id is None


# ---------------------------------------------------------------------------
# action_open_interview guard tests
# ---------------------------------------------------------------------------


async def test_action_open_interview_without_cycle_id_shows_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """action_open_interview notifies warning when _cycle_id is None."""
    for key in list(os.environ):
        if key.startswith("ALPHASWARM_"):
            monkeypatch.delenv(key, raising=False)

    app = _make_app(phase=SimulationPhase.COMPLETE, cycle_id=None)

    async with app.run_test(size=(80, 30)) as pilot:
        with patch.object(app, "notify") as mock_notify:
            app.action_open_interview("quants_01")
            mock_notify.assert_called_once_with(
                "No simulation completed yet", severity="warning"
            )


async def test_action_open_interview_without_graph_shows_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """action_open_interview shows error when graph_manager is None."""
    for key in list(os.environ):
        if key.startswith("ALPHASWARM_"):
            monkeypatch.delenv(key, raising=False)

    app = _make_app(phase=SimulationPhase.COMPLETE, cycle_id="cycle-123")
    # graph_manager is None by default in _make_mock_app_state

    async with app.run_test(size=(80, 30)) as pilot:
        with patch.object(app, "notify") as mock_notify:
            app.action_open_interview("quants_01")
            mock_notify.assert_called_once_with(
                "Neo4j not connected", severity="error"
            )


async def test_action_open_interview_without_ollama_shows_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """action_open_interview shows error when ollama_client is None."""
    for key in list(os.environ):
        if key.startswith("ALPHASWARM_"):
            monkeypatch.delenv(key, raising=False)

    app = _make_app(phase=SimulationPhase.COMPLETE, cycle_id="cycle-123")
    app.app_state.graph_manager = MagicMock()  # graph is present
    # ollama_client is None by default

    async with app.run_test(size=(80, 30)) as pilot:
        with patch.object(app, "notify") as mock_notify:
            app.action_open_interview("quants_01")
            mock_notify.assert_called_once_with(
                "Ollama not connected", severity="error"
            )
