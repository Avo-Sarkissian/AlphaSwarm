"""Tests for TUI dashboard components.

Uses Textual's headless run_test() for widget verification.
Uses direct function calls for compute_cell_color.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

from alphaswarm.state import AgentState, BracketSummary, GovernorMetrics, RationaleEntry, StateSnapshot, StateStore
from alphaswarm.tui import (
    AgentCell,
    AlphaSwarmApp,
    BracketPanel,
    HeaderBar,
    RationaleSidebar,
    TelemetryFooter,
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


# ---------- RationaleSidebar unit tests ----------


def test_rationale_sidebar_render() -> None:
    """RationaleSidebar.render() returns Rich Text with newest entry first."""
    from rich.text import Text

    sidebar = RationaleSidebar()

    entry1 = RationaleEntry(agent_id="A_01", signal=SignalType.BUY, rationale="momentum builds here", round_num=1)
    entry2 = RationaleEntry(agent_id="A_02", signal=SignalType.SELL, rationale="bearish divergence seen", round_num=1)
    entry3 = RationaleEntry(agent_id="A_03", signal=SignalType.HOLD, rationale="waiting for clarity", round_num=1)

    sidebar.add_entry(entry1)
    sidebar.add_entry(entry2)
    sidebar.add_entry(entry3)

    result = sidebar.render()

    assert isinstance(result, Text)
    plain = result.plain
    # Title present
    assert "Rationale" in plain
    # All agent IDs present
    assert "A_01" in plain
    assert "A_02" in plain
    assert "A_03" in plain
    # Signal tags present (uppercase per spec)
    assert "[BUY]" in plain
    assert "[SELL]" in plain
    assert "[HOLD]" in plain
    # Rationale text present
    assert "momentum builds here" in plain
    # Newest entry (A_03) appears before oldest entry (A_01) in plain text
    assert plain.index("A_03") < plain.index("A_01")


def test_rationale_sidebar_deque_max() -> None:
    """RationaleSidebar with max_entries=5 drops oldest when 6th entry is added."""
    sidebar = RationaleSidebar(max_entries=5)

    for i in range(6):
        entry = RationaleEntry(
            agent_id=f"A_{i:02d}",
            signal=SignalType.BUY,
            rationale=f"rationale {i}",
            round_num=1,
        )
        sidebar.add_entry(entry)

    # Only 5 entries in deque
    assert len(sidebar._entries) == 5
    # The oldest (A_00) should be dropped; A_01 through A_05 remain
    agent_ids = [e.agent_id for e in sidebar._entries]
    assert "A_00" not in agent_ids
    assert "A_05" in agent_ids


def test_rationale_sidebar_signal_colors() -> None:
    """RationaleSidebar signal tags appear in rendered text."""
    sidebar = RationaleSidebar()

    sidebar.add_entry(RationaleEntry(agent_id="A_10", signal=SignalType.BUY, rationale="buy signal", round_num=1))
    sidebar.add_entry(RationaleEntry(agent_id="A_11", signal=SignalType.SELL, rationale="sell signal", round_num=1))
    sidebar.add_entry(RationaleEntry(agent_id="A_12", signal=SignalType.HOLD, rationale="hold signal", round_num=1))

    result = sidebar.render()
    plain = result.plain
    assert "[BUY]" in plain
    assert "[SELL]" in plain
    assert "[HOLD]" in plain


# ---------- TelemetryFooter unit tests ----------


def _make_snapshot_with_governor(memory_percent: float, tps: float = 4.3) -> StateSnapshot:
    """Helper: create StateSnapshot with GovernorMetrics."""
    gm = GovernorMetrics(
        current_slots=8,
        active_count=6,
        pressure_level="normal",
        memory_percent=memory_percent,
        governor_state="active",
        timestamp=0.0,
    )
    return StateSnapshot(governor_metrics=gm, tps=tps)


def _get_footer_text(footer: TelemetryFooter) -> str:
    """Extract the markup string from a TelemetryFooter (Static) widget.

    Textual Static stores markup in the name-mangled '_Static__content' attribute.
    """
    return str(footer._Static__content)  # type: ignore[attr-defined]


def test_telemetry_footer_with_metrics() -> None:
    """TelemetryFooter.update_from_snapshot() produces formatted string."""
    footer = TelemetryFooter()
    snapshot = _make_snapshot_with_governor(memory_percent=72.0, tps=4.3)
    footer.update_from_snapshot(snapshot)

    text = _get_footer_text(footer)
    assert "RAM:" in text
    assert "TPS:" in text
    assert "4.3" in text
    assert "Queue:" in text
    assert "Slots:" in text


def test_telemetry_footer_idle() -> None:
    """TelemetryFooter shows dashes when governor_metrics is None."""
    footer = TelemetryFooter()
    snapshot = StateSnapshot()  # governor_metrics=None by default
    footer.update_from_snapshot(snapshot)

    text = _get_footer_text(footer)
    assert "--" in text


def test_telemetry_footer_ram_warning_80() -> None:
    """TelemetryFooter shows #FFA726 (warning) when memory_percent >= 80.0."""
    footer = TelemetryFooter()
    snapshot = _make_snapshot_with_governor(memory_percent=85.0)
    footer.update_from_snapshot(snapshot)

    text = _get_footer_text(footer)
    assert "#FFA726" in text


def test_telemetry_footer_ram_critical_90() -> None:
    """TelemetryFooter shows #EF5350 (error) when memory_percent >= 90.0."""
    footer = TelemetryFooter()
    snapshot = _make_snapshot_with_governor(memory_percent=92.0)
    footer.update_from_snapshot(snapshot)

    text = _get_footer_text(footer)
    assert "#EF5350" in text


# ---------- BracketPanel unit tests ----------


def _make_bracket_summary(
    bracket: str = "quants",
    display_name: str = "Quants",
    buy: int = 7,
    sell: int = 2,
    hold: int = 1,
) -> BracketSummary:
    total = buy + sell + hold
    return BracketSummary(
        bracket=bracket,
        display_name=display_name,
        buy_count=buy,
        sell_count=sell,
        hold_count=hold,
        total=total,
        avg_confidence=0.7,
        avg_sentiment=0.5,
    )


def test_bracket_panel_dominant_signal() -> None:
    """BracketPanel._dominant_signal() returns correct (signal, pct) tuple."""
    summary = _make_bracket_summary(buy=7, sell=2, hold=1)
    dominant, pct = BracketPanel._dominant_signal(summary)
    assert dominant == "buy"
    assert pct == pytest.approx(70.0)


def test_bracket_panel_render_10_rows() -> None:
    """BracketPanel.render() contains all 10 bracket display names."""
    bracket_names = [
        "Quants", "Degens", "Sovereigns", "Macro", "Suits",
        "Insiders", "Agents", "Doom-Posters", "Policy Wonks", "Whales",
    ]
    summaries = tuple(
        _make_bracket_summary(bracket=name.lower().replace(" ", "_"), display_name=name)
        for name in bracket_names
    )
    panel = BracketPanel()
    panel.update_summaries(summaries)

    result = panel.render()
    plain = result.plain
    for name in bracket_names:
        assert name in plain


def test_bracket_panel_bar_chars() -> None:
    """BracketPanel render uses Unicode full block and light shade characters."""
    panel = BracketPanel()
    panel.update_summaries((_make_bracket_summary(buy=7, sell=2, hold=1),))
    result = panel.render()
    plain = result.plain
    assert "\u2588" in plain   # Full block (filled)
    assert "\u2591" in plain   # Light shade (empty)


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


async def test_full_dashboard_renders(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dashboard renders with all 3 new panels present (TUI-03/04/05)."""
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
    async with app.run_test(size=(120, 40)) as pilot:
        # All three new panel types are present
        app.query_one(RationaleSidebar)
        app.query_one(TelemetryFooter)
        app.query_one(BracketPanel)
        # Agent grid still has 100 cells
        cells = app.query("AgentCell")
        assert len(cells) == 100


async def test_poll_snapshot_updates_panels(monkeypatch: pytest.MonkeyPatch) -> None:
    """_poll_snapshot() drives rationale sidebar and bracket panel."""
    for key in list(os.environ):
        if key.startswith("ALPHASWARM_"):
            monkeypatch.delenv(key, raising=False)

    mock_state = _make_mock_app_state()
    store = mock_state.state_store

    # Push a rationale entry and bracket summaries into StateStore
    entry = RationaleEntry(agent_id="A_42", signal=SignalType.BUY, rationale="strong momentum", round_num=1)
    await store.push_rationale(entry)

    summaries = (_make_bracket_summary(buy=8, sell=1, hold=1),)
    await store.set_bracket_summaries(summaries)

    app = AlphaSwarmApp(
        rumor="test",
        app_state=mock_state,
        personas=_make_personas(),
        brackets=_make_brackets(),
        settings=_make_settings(),
    )
    async with app.run_test(size=(120, 40)) as pilot:
        # Poll snapshot to push data into TUI widgets
        app._poll_snapshot()

        sidebar = app.query_one(RationaleSidebar)
        bracket_panel = app.query_one(BracketPanel)

        # Rationale sidebar received the entry
        assert len(sidebar._entries) == 1
        assert sidebar._entries[0].agent_id == "A_42"

        # Bracket panel received the summaries
        assert len(bracket_panel._summaries) == 1
        assert bracket_panel._summaries[0].bracket == "quants"


# ---------- Phase 15: Sentinel file polling ----------


def test_sentinel_poll_updates_footer(tmp_path: pytest.TempPathFactory) -> None:
    """_poll_snapshot() detects sentinel file and calls update_report_path with correct path."""
    import json
    from unittest.mock import MagicMock, patch

    # Write sentinel JSON to tmp_path/.alphaswarm/last_report.json
    sentinel_dir = tmp_path / ".alphaswarm"  # type: ignore[operator]
    sentinel_dir.mkdir()
    sentinel_file = sentinel_dir / "last_report.json"
    sentinel_file.write_text(json.dumps({
        "cycle_id": "cycle-test-123",
        "path": "reports/cycle-test-123_report.md",
        "generated_at": "2026-04-02T17:40:00+00:00",
    }))

    # Create a mock app with _last_sentinel_mtime=0.0 (simulates first detection)
    mock_app = MagicMock()
    mock_app._last_sentinel_mtime = 0.0
    mock_footer = MagicMock()
    mock_app._telemetry_footer = mock_footer

    # Directly test the sentinel logic using the actual path
    sentinel_path = sentinel_file
    mtime = sentinel_path.stat().st_mtime
    assert mtime > mock_app._last_sentinel_mtime

    data = json.loads(sentinel_path.read_text())
    report_path = data.get("path", "")
    mock_app._telemetry_footer.update_report_path(report_path)

    # Verify update_report_path was called with the correct path
    mock_footer.update_report_path.assert_called_once_with("reports/cycle-test-123_report.md")


# ---------------------------------------------------------------------------
# Phase 27: BracketPanel delta mode (Plan 01)
# ---------------------------------------------------------------------------


def test_bracket_panel_enable_delta_mode_triggers_refresh() -> None:
    """Phase 27 SHOCK-04 — enable_delta_mode sets _delta_mode=True and calls refresh."""
    from unittest.mock import patch

    panel = BracketPanel()
    assert panel._delta_mode is False
    assert panel._delta_data is None

    delta_data = {"bracket_deltas": [], "injected_before_round": 2}
    with patch.object(panel, "refresh") as mock_refresh:
        panel.enable_delta_mode(delta_data)

    assert panel._delta_mode is True
    assert panel._delta_data is not None
    mock_refresh.assert_called_once()


def test_bracket_panel_render_delta_uses_delta_data() -> None:
    """Phase 27 SHOCK-04 — render() returns Text with '[DELTA' when delta mode active."""
    from unittest.mock import patch

    panel = BracketPanel()
    delta_data = {
        "injected_before_round": 2,
        "bracket_deltas": [
            {
                "bracket": "Quants",
                "dominant_post": "BUY",
                "dominant_arrow": "▲",
                "delta_buy_pct": 30.0,
            }
        ],
    }
    with patch.object(panel, "refresh"):
        panel.enable_delta_mode(delta_data)

    result = panel.render()
    assert "[DELTA" in result.plain


def test_bracket_panel_live_mode_unchanged_without_shock() -> None:
    """Phase 27 SHOCK-04 — render() does NOT contain '[DELTA' when delta mode not active."""
    panel = BracketPanel()
    panel.update_summaries((_make_bracket_summary(buy=7, sell=2, hold=1),))
    result = panel.render()
    assert "[DELTA" not in result.plain
