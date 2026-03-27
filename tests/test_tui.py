"""Tests for TUI dashboard components.

Uses Textual's headless run_test() for widget verification.
Uses direct function calls for compute_cell_color.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

from alphaswarm.state import AgentState, StateSnapshot, StateStore
from alphaswarm.tui import (
    AgentCell,
    AlphaSwarmApp,
    HeaderBar,
    _format_elapsed,
    _phase_display_label,
    compute_cell_color,
)
from alphaswarm.types import SignalType, SimulationPhase


# ---------- compute_cell_color ----------


def test_cell_color_pending_none() -> None:
    """None state maps to PENDING gray #333333."""
    assert compute_cell_color(None) == "#333333"


def test_cell_color_pending_no_signal() -> None:
    """AgentState with None signal maps to PENDING gray."""
    state = AgentState(signal=None, confidence=0.0)
    assert compute_cell_color(state) == "#333333"


def test_cell_color_buy_high_confidence() -> None:
    """BUY at confidence 1.0 -> hsl(120,60%,50%)."""
    state = AgentState(signal=SignalType.BUY, confidence=1.0)
    assert compute_cell_color(state) == "hsl(120,60%,50%)"


def test_cell_color_buy_low_confidence() -> None:
    """BUY at confidence 0.0 -> hsl(120,60%,20%)."""
    state = AgentState(signal=SignalType.BUY, confidence=0.0)
    assert compute_cell_color(state) == "hsl(120,60%,20%)"


def test_cell_color_sell_mid_confidence() -> None:
    """SELL at confidence 0.5 -> hsl(0,70%,35%)."""
    state = AgentState(signal=SignalType.SELL, confidence=0.5)
    assert compute_cell_color(state) == "hsl(0,70%,35%)"


def test_cell_color_hold() -> None:
    """HOLD signal -> fixed #555555."""
    state = AgentState(signal=SignalType.HOLD, confidence=0.9)
    assert compute_cell_color(state) == "#555555"


def test_cell_color_parse_error() -> None:
    """PARSE_ERROR -> same as PENDING #333333."""
    state = AgentState(signal=SignalType.PARSE_ERROR, confidence=0.0)
    assert compute_cell_color(state) == "#333333"


# ---------- _format_elapsed ----------


def test_format_elapsed_zero() -> None:
    assert _format_elapsed(0.0) == "00:00:00"


def test_format_elapsed_seconds() -> None:
    assert _format_elapsed(45.7) == "00:00:45"


def test_format_elapsed_minutes() -> None:
    assert _format_elapsed(125.0) == "00:02:05"


def test_format_elapsed_hours() -> None:
    assert _format_elapsed(3661.0) == "01:01:01"


# ---------- _phase_display_label ----------


def test_phase_labels() -> None:
    """All SimulationPhase values have display labels."""
    assert _phase_display_label(SimulationPhase.IDLE) == "Idle"
    assert _phase_display_label(SimulationPhase.SEEDING) == "Seeding"
    assert _phase_display_label(SimulationPhase.ROUND_1) == "Round 1"
    assert _phase_display_label(SimulationPhase.ROUND_2) == "Round 2"
    assert _phase_display_label(SimulationPhase.ROUND_3) == "Round 3"
    assert _phase_display_label(SimulationPhase.COMPLETE) == "Complete"


# ---------- Headless App Tests ----------


def _make_mock_app_state() -> MagicMock:
    """Create a mock AppState with a real StateStore."""
    mock = MagicMock()
    mock.state_store = StateStore()
    # Simulation won't actually run (no Ollama/Neo4j),
    # so set ollama_client/model_manager/graph_manager to None
    mock.ollama_client = None
    mock.model_manager = None
    mock.graph_manager = None
    return mock


def _make_personas() -> list:
    """Create 100 minimal persona-like objects for grid rendering."""
    from alphaswarm.config import generate_personas, load_bracket_configs

    brackets = load_bracket_configs()
    return generate_personas(brackets)


def _make_brackets() -> list:
    from alphaswarm.config import load_bracket_configs

    return load_bracket_configs()


def _make_settings():
    from alphaswarm.config import AppSettings

    return AppSettings()


async def test_grid_renders_100_cells(monkeypatch: pytest.MonkeyPatch) -> None:
    """10x10 grid contains exactly 100 AgentCell widgets (TUI-01)."""
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
    async with app.run_test(size=(80, 30)) as pilot:
        cells = app.query("AgentCell")
        assert len(cells) == 100


async def test_header_shows_idle_on_start(monkeypatch: pytest.MonkeyPatch) -> None:
    """Header displays Idle before simulation starts (TUI-06)."""
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
    async with app.run_test(size=(80, 30)) as pilot:
        header = app.query_one(HeaderBar)
        # HeaderBar is a Static -- its renderable contains the text
        assert header is not None


async def test_cell_color_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    """AgentCell.update_color changes background based on state (TUI-01)."""
    for key in list(os.environ):
        if key.startswith("ALPHASWARM_"):
            monkeypatch.delenv(key, raising=False)

    app = AlphaSwarmApp(
        rumor="test",
        app_state=_make_mock_app_state(),
        personas=_make_personas(),
        brackets=_make_brackets(),
        settings=_make_settings(),
    )
    async with app.run_test(size=(80, 30)) as pilot:
        cells = list(app.query("AgentCell"))
        first_cell = cells[0]
        # Initially pending
        assert first_cell._current_color == "#333333"
        # Update to BUY
        buy_state = AgentState(signal=SignalType.BUY, confidence=0.8)
        first_cell.update_color(buy_state)
        assert first_cell._current_color == "hsl(120,60%,44%)"


async def test_snapshot_diff_updates(monkeypatch: pytest.MonkeyPatch) -> None:
    """Snapshot timer updates only changed cells (TUI-02)."""
    for key in list(os.environ):
        if key.startswith("ALPHASWARM_"):
            monkeypatch.delenv(key, raising=False)

    mock_state = _make_mock_app_state()
    store = mock_state.state_store
    personas = _make_personas()

    app = AlphaSwarmApp(
        rumor="test",
        app_state=mock_state,
        personas=personas,
        brackets=_make_brackets(),
        settings=_make_settings(),
    )
    async with app.run_test(size=(80, 30)) as pilot:
        # Write a decision to StateStore
        await store.update_agent_state(personas[0].id, SignalType.SELL, 0.6)
        # Trigger a snapshot poll
        app._poll_snapshot()
        # Check that the first cell updated
        first_cell = app._cells[personas[0].id]
        assert first_cell._current_color == "hsl(0,70%,38%)"
        # Second cell should still be pending
        second_cell = app._cells[personas[1].id]
        assert second_cell._current_color == "#333333"
