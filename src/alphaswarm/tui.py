"""Textual TUI dashboard for AlphaSwarm simulation visualization.

Provides a 10x10 agent grid with color-coded cells, a header bar with
simulation status, and snapshot-based rendering on a 200ms timer.

Per D-01: Simulation runs as a Textual Worker within the TUI's event loop.
Per D-02: Grid cells update per-agent as decisions resolve via StateStore snapshots.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from textual.app import App, ComposeResult
from textual.containers import Container
from textual.theme import Theme
from textual.widget import Widget
from textual.widgets import Static

from alphaswarm.state import AgentState
from alphaswarm.types import SignalType, SimulationPhase

if TYPE_CHECKING:
    from alphaswarm.app import AppState
    from alphaswarm.config import AppSettings, BracketConfig
    from alphaswarm.state import StateSnapshot
    from alphaswarm.types import AgentPersona

logger = structlog.get_logger(component="tui")


# ---------------------------------------------------------------------------
# Color computation (UI-SPEC color table)
# ---------------------------------------------------------------------------


def compute_cell_color(state: AgentState | None) -> str:
    """Compute TCSS-compatible color string for an agent cell.

    Color mapping per UI-SPEC:
    - BUY: HSL(120, 60%, 20-50%) green, brightness = confidence
    - SELL: HSL(0, 70%, 20-50%) red, brightness = confidence
    - HOLD: #555555 fixed gray
    - PENDING (None signal): #333333 fixed dim gray (D-05)
    - PARSE_ERROR: #333333 same as PENDING (no valid decision)
    """
    if state is None or state.signal is None:
        return "#333333"
    if state.signal == SignalType.HOLD:
        return "#555555"
    if state.signal == SignalType.PARSE_ERROR:
        return "#333333"
    if state.signal == SignalType.BUY:
        h, s = 120, 60
    elif state.signal == SignalType.SELL:
        h, s = 0, 70
    else:
        return "#333333"  # fallback
    lightness = 20 + (state.confidence * 30)
    return f"hsl({h},{s}%,{lightness:.0f}%)"


# ---------------------------------------------------------------------------
# AgentCell widget
# ---------------------------------------------------------------------------


class AgentCell(Widget):
    """A single agent cell in the 10x10 grid. Color-only, no text (D-04)."""

    DEFAULT_CSS = """
    AgentCell {
        width: 3;
        height: 1;
        background: #333333;
    }
    """

    def __init__(self, agent_id: str) -> None:
        super().__init__()
        self.agent_id = agent_id
        self._current_color = "#333333"

    def update_color(self, state: AgentState | None) -> None:
        """Update background color based on agent state. Only refreshes on change."""
        new_color = compute_cell_color(state)
        if new_color != self._current_color:
            self._current_color = new_color
            self.styles.background = new_color


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _format_elapsed(seconds: float) -> str:
    """Format elapsed seconds as HH:MM:SS."""
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


_PHASE_LABELS: dict[SimulationPhase, str] = {
    SimulationPhase.IDLE: "Idle",
    SimulationPhase.SEEDING: "Seeding",
    SimulationPhase.ROUND_1: "Round 1",
    SimulationPhase.ROUND_2: "Round 2",
    SimulationPhase.ROUND_3: "Round 3",
    SimulationPhase.COMPLETE: "Complete",
}


def _phase_display_label(phase: SimulationPhase) -> str:
    """Map SimulationPhase enum to display label per UI-SPEC."""
    return _PHASE_LABELS.get(phase, phase.value)


# ---------------------------------------------------------------------------
# HeaderBar widget (D-06 format)
# ---------------------------------------------------------------------------


class HeaderBar(Static):
    """Header bar showing simulation status, round counter, and elapsed time.

    Format per D-06:
      AlphaSwarm  |  Round X/3  |  [bullet] Status  |  HH:MM:SS
    """

    DEFAULT_CSS = """
    HeaderBar {
        dock: top;
        width: 100%;
        height: 1;
        background: $surface;
        color: $foreground;
        text-style: bold;
        padding: 0 1;
    }
    """

    def __init__(self) -> None:
        super().__init__("")
        self._render_header(SimulationPhase.IDLE, 0, 0.0)

    def _render_header(
        self, phase: SimulationPhase, round_num: int, elapsed: float,
    ) -> None:
        """Render header content with Rich markup for color."""
        label = _phase_display_label(phase)
        elapsed_str = _format_elapsed(elapsed)
        round_display = round_num if round_num > 0 else 0
        self.update(
            f"  [#4FC3F7 bold]AlphaSwarm[/]  "
            f"[#78909C]|[/]  Round {round_display}/3  "
            f"[#78909C]|[/]  [#4FC3F7]\u25cf[/] [bold]{label}[/]  "
            f"[#78909C]|[/]  {elapsed_str}  "
        )

    def update_from_snapshot(self, snapshot: StateSnapshot) -> None:
        """Update header from a StateSnapshot."""
        self._render_header(snapshot.phase, snapshot.round_num, snapshot.elapsed_seconds)


# ---------------------------------------------------------------------------
# Theme definition (UI-SPEC)
# ---------------------------------------------------------------------------


ALPHASWARM_THEME = Theme(
    name="alphaswarm",
    primary="#4FC3F7",
    secondary="#78909C",
    foreground="#E0E0E0",
    background="#121212",
    surface="#1E1E1E",
    panel="#252525",
    accent="#4FC3F7",
    success="#66BB6A",
    warning="#FFA726",
    error="#EF5350",
    dark=True,
)


# ---------------------------------------------------------------------------
# AlphaSwarmApp (D-01 same-process, Worker pattern)
# ---------------------------------------------------------------------------


class AlphaSwarmApp(App):
    """AlphaSwarm TUI dashboard.

    Per D-01: Simulation runs as a Textual Worker. StateStore is the shared bridge.
    Per TUI-02: 200ms set_interval reads snapshots and diffs for changed cells.
    """

    CSS = """
    #grid-container {
        align: center middle;
        width: 100%;
        height: 100%;
    }

    #agent-grid {
        layout: grid;
        grid-size: 10 10;
        grid-gutter: 0;
        width: 30;
        height: 10;
    }
    """

    BINDINGS = [("q", "quit", "Quit")]

    def __init__(
        self,
        rumor: str,
        app_state: AppState,
        personas: list[AgentPersona],
        brackets: list[BracketConfig],
        settings: AppSettings,
    ) -> None:
        super().__init__()
        self.rumor = rumor
        self.app_state = app_state
        self.personas = personas
        self.brackets = brackets
        self.sim_settings = settings
        self._cells: dict[str, AgentCell] = {}
        self._prev_snapshot: StateSnapshot | None = None
        self._header_bar: HeaderBar | None = None

    def on_mount(self) -> None:
        """Register theme, start simulation Worker, start snapshot timer."""
        self.register_theme(ALPHASWARM_THEME)
        self.theme = "alphaswarm"

        # Start simulation as background Worker (D-01)
        self.run_worker(self._run_simulation(), exclusive=True, exit_on_error=False)

        # Start 200ms snapshot polling timer (TUI-02)
        self.set_interval(1 / 5, self._poll_snapshot)

    def compose(self) -> ComposeResult:
        """Compose the dashboard layout: header + centered grid."""
        self._header_bar = HeaderBar()
        yield self._header_bar
        with Container(id="grid-container"):
            with Container(id="agent-grid"):
                # Sequential row-by-row mapping (D-03)
                for i, persona in enumerate(self.personas):
                    cell = AgentCell(agent_id=persona.id)
                    self._cells[persona.id] = cell
                    yield cell

    async def _run_simulation(self) -> None:
        """Worker coroutine: runs simulation, writes to StateStore via state_store parameter."""
        from alphaswarm.simulation import run_simulation

        assert self.app_state.ollama_client is not None
        assert self.app_state.model_manager is not None
        assert self.app_state.graph_manager is not None

        try:
            await self.app_state.graph_manager.ensure_schema()
            await run_simulation(
                rumor=self.rumor,
                settings=self.sim_settings,
                ollama_client=self.app_state.ollama_client,
                model_manager=self.app_state.model_manager,
                graph_manager=self.app_state.graph_manager,
                governor=self.app_state.governor,
                personas=list(self.personas),
                brackets=list(self.brackets),
                state_store=self.app_state.state_store,
            )
            # Ensure COMPLETE is visible
            await self.app_state.state_store.set_phase(SimulationPhase.COMPLETE)
        except Exception as e:
            logger.error("simulation_worker_failed", error=str(e))
            self.notify(
                f"Simulation failed: {e}. Press q to exit.",
                severity="error",
                timeout=0,
            )

    def _poll_snapshot(self) -> None:
        """Timer callback: read snapshot, diff, update changed cells.

        Per TUI-02: Only refreshes cells that actually changed.
        """
        snapshot = self.app_state.state_store.snapshot()

        if self._prev_snapshot is None:
            # First tick: update all cells and header
            for agent_id, cell in self._cells.items():
                agent_state = snapshot.agent_states.get(agent_id)
                cell.update_color(agent_state)
            if self._header_bar is not None:
                self._header_bar.update_from_snapshot(snapshot)
        else:
            # Diff: only update changed agents
            for agent_id, cell in self._cells.items():
                new_state = snapshot.agent_states.get(agent_id)
                old_state = self._prev_snapshot.agent_states.get(agent_id)
                if new_state != old_state:
                    cell.update_color(new_state)

            # Update header if phase, round, or elapsed changed (elapsed always changes)
            if self._header_bar is not None:
                if (
                    snapshot.phase != self._prev_snapshot.phase
                    or snapshot.round_num != self._prev_snapshot.round_num
                    or int(snapshot.elapsed_seconds) != int(self._prev_snapshot.elapsed_seconds)
                ):
                    self._header_bar.update_from_snapshot(snapshot)

        self._prev_snapshot = snapshot
