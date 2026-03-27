"""Textual TUI dashboard for AlphaSwarm simulation visualization.

Provides a 10x10 agent grid with color-coded cells, a header bar with
simulation status, and snapshot-based rendering on a 200ms timer.

Per D-01: Simulation runs as a Textual Worker within the TUI's event loop.
Per D-02: Grid cells update per-agent as decisions resolve via StateStore snapshots.
"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

import structlog
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Container
from textual.screen import Screen
from textual.theme import Theme
from textual.widget import Widget
from textual.widgets import Input, Static

from alphaswarm.state import AgentState, BracketSummary, RationaleEntry
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
# RationaleSidebar widget (D-03, D-04, TUI-03)
# ---------------------------------------------------------------------------


class RationaleSidebar(Widget):
    """Scrolling rationale log showing high-influence agent reasoning, newest first.

    Entries prepend at the top via deque.appendleft(). Renders Rich Text via render().
    Per D-04: newest entries always at the top; older entries scroll down.
    """

    DEFAULT_CSS = """
    RationaleSidebar {
        width: 40;
        height: 100%;
        background: $panel;
        border-left: solid $secondary;
        padding: 0 1;
    }
    """

    # Signal tag color mapping per UI-SPEC
    _SIGNAL_COLORS: dict[str, str] = {
        "buy": "#66BB6A",    # $success
        "sell": "#EF5350",   # $error
        "hold": "#78909C",   # $secondary
    }

    def __init__(self, max_entries: int = 50) -> None:
        super().__init__()
        self._entries: deque[RationaleEntry] = deque(maxlen=max_entries)

    def add_entry(self, entry: RationaleEntry) -> None:
        """Add entry to front (newest first per D-04)."""
        self._entries.appendleft(entry)
        self.refresh()

    def render(self) -> Text:
        text = Text()
        text.append("Rationale\n", style="bold #4FC3F7")
        for entry in self._entries:
            text.append("> ", style="#78909C")
            text.append(f"{entry.agent_id} ", style="#E0E0E0")
            color = self._SIGNAL_COLORS.get(entry.signal.value, "#78909C")
            text.append(f"[{entry.signal.value.upper()}] ", style=f"bold {color}")
            text.append(f"{entry.rationale}\n", style="#E0E0E0")
        return text


# ---------------------------------------------------------------------------
# TelemetryFooter widget (D-06, TUI-04)
# ---------------------------------------------------------------------------


class TelemetryFooter(Static):
    """Single-line telemetry footer displaying RAM, TPS, Queue depth, and Slots.

    Updates from StateSnapshot on each 200ms poll tick.
    Per D-06: 4 inline metrics with color-coded RAM threshold warnings.
    """

    DEFAULT_CSS = """
    TelemetryFooter {
        width: 1fr;
        height: 1;
        background: $panel;
        padding: 0 1;
    }
    """

    def __init__(self) -> None:
        super().__init__("")
        self._render_idle()

    def _render_idle(self) -> None:
        self.update(
            "  [#78909C]RAM:[/] [#78909C]--[/]  "
            "[#78909C]|[/]  [#78909C]TPS:[/] [#78909C]--[/]  "
            "[#78909C]|[/]  [#78909C]Queue:[/] [#78909C]--[/]  "
            "[#78909C]|[/]  [#78909C]Slots:[/] [#78909C]--[/]"
        )

    def update_from_snapshot(self, snapshot: StateSnapshot) -> None:
        """Update telemetry display from a StateSnapshot."""
        gm = snapshot.governor_metrics
        if gm is None:
            self._render_idle()
            return

        ram_pct = gm.memory_percent
        if ram_pct >= 90.0:
            ram_color = "#EF5350"
        elif ram_pct >= 80.0:
            ram_color = "#FFA726"
        else:
            ram_color = "#E0E0E0"

        self.update(
            f"  [#78909C]RAM:[/] [{ram_color}]{ram_pct:.0f}%[/]  "
            f"[#78909C]|[/]  [#78909C]TPS:[/] [#E0E0E0]{snapshot.tps:.1f}[/]  "
            f"[#78909C]|[/]  [#78909C]Queue:[/] [#E0E0E0]{gm.active_count}[/]  "
            f"[#78909C]|[/]  [#78909C]Slots:[/] [#E0E0E0]{gm.current_slots}[/]"
        )


# ---------------------------------------------------------------------------
# BracketPanel widget (D-07, D-08, TUI-05)
# ---------------------------------------------------------------------------


class BracketPanel(Widget):
    """Bracket sentiment aggregation panel showing 10 progress bars.

    Each row renders one bracket's dominant signal as a Unicode block bar.
    Updates only when bracket_summaries change between snapshots (per TUI-05).
    Per D-07/D-08: bar fill = dominant signal percentage, color = dominant signal.
    """

    DEFAULT_CSS = """
    BracketPanel {
        width: 40;
        height: 100%;
        background: $panel;
        border-left: solid $secondary;
        padding: 1 1 0 1;
    }
    """

    FILL_CHAR = "\u2588"   # Full block
    EMPTY_CHAR = "\u2591"  # Light shade
    BAR_WIDTH = 20

    _SIGNAL_COLORS: dict[str, str] = {
        "buy": "#66BB6A",    # $success
        "sell": "#EF5350",   # $error
        "hold": "#78909C",   # $secondary
    }

    def __init__(self) -> None:
        super().__init__()
        self._summaries: tuple[BracketSummary, ...] = ()

    def update_summaries(self, summaries: tuple[BracketSummary, ...]) -> None:
        """Store bracket summaries and trigger a re-render."""
        self._summaries = summaries
        self.refresh()

    def render(self) -> Text:
        text = Text()
        text.append("Brackets\n", style="bold #4FC3F7")
        if not self._summaries:
            text.append("[#78909C]Awaiting data...[/]\n")
            return text
        for s in self._summaries:
            dominant, pct = self._dominant_signal(s)
            color = self._SIGNAL_COLORS.get(dominant, "#78909C")
            filled = round(pct / 100 * self.BAR_WIDTH)
            empty = self.BAR_WIDTH - filled

            text.append(f"{s.display_name:<14}  ", style="#78909C")
            text.append("[")
            text.append(self.FILL_CHAR * filled, style=color)
            text.append(self.EMPTY_CHAR * empty, style="#333333")
            text.append(f"] {pct:.0f}%\n", style="#E0E0E0")
        return text

    @staticmethod
    def _dominant_signal(s: BracketSummary) -> tuple[str, float]:
        """Return (dominant_signal, percentage). Tie-break: BUY > SELL > HOLD."""
        counts = [("buy", s.buy_count), ("sell", s.sell_count), ("hold", s.hold_count)]
        dominant = max(counts, key=lambda x: x[1])
        total = s.total
        pct = (dominant[1] / total * 100) if total > 0 else 0.0
        return dominant[0], pct


# ---------------------------------------------------------------------------
# RumorInputScreen — shown on launch when no rumor is provided
# ---------------------------------------------------------------------------


class RumorInputScreen(Screen[str]):
    """Full-screen rumor input. Dismisses with the rumor string on Enter."""

    BINDINGS = [("escape", "quit", "Quit")]

    DEFAULT_CSS = """
    RumorInputScreen {
        align: center middle;
        background: #121212;
    }

    #input-container {
        width: 72;
        height: auto;
        border: solid #4FC3F7;
        padding: 2 3;
        background: #1E1E1E;
    }

    #as-title {
        width: 100%;
        text-align: center;
        color: #4FC3F7;
        text-style: bold;
        margin-bottom: 1;
    }

    #as-subtitle {
        width: 100%;
        text-align: center;
        color: #78909C;
        margin-bottom: 2;
    }

    #rumor-input {
        width: 100%;
    }

    #as-hint {
        width: 100%;
        text-align: center;
        color: #78909C;
        margin-top: 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Container(id="input-container"):
            yield Static("AlphaSwarm", id="as-title")
            yield Static("Enter a market rumor to simulate", id="as-subtitle")
            yield Input(
                placeholder="e.g. Apple is acquiring OpenAI for $300B...",
                id="rumor-input",
            )
            yield Static("Enter to start  ·  Esc to quit", id="as-hint")

    def on_mount(self) -> None:
        self.query_one("#rumor-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        rumor = event.value.strip()
        if rumor:
            self.dismiss(rumor)

    def action_quit(self) -> None:
        self.app.exit()


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
    #main-row {
        width: 100%;
        height: 1fr;
        layout: horizontal;
    }

    #grid-container {
        width: 1fr;
        height: 100%;
        align: center middle;
    }

    #agent-grid {
        layout: grid;
        grid-size: 10 10;
        grid-gutter: 0;
        width: 30;
        height: 10;
    }

    #bottom-row {
        dock: bottom;
        width: 100%;
        height: 12;
        layout: horizontal;
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
        self._rationale_sidebar: RationaleSidebar | None = None
        self._telemetry_footer: TelemetryFooter | None = None
        self._bracket_panel: BracketPanel | None = None
        self._prev_bracket_summaries: tuple[BracketSummary, ...] = ()

    def on_mount(self) -> None:
        """Register theme, then either show rumor input or start simulation."""
        self.register_theme(ALPHASWARM_THEME)
        self.theme = "alphaswarm"

        if not self.rumor:
            self.push_screen(RumorInputScreen(), self._on_rumor_received)
        else:
            self._start_simulation()

    def _on_rumor_received(self, rumor: str) -> None:
        """Called when RumorInputScreen dismisses with the user's rumor."""
        self.rumor = rumor
        self._start_simulation()

    def _start_simulation(self) -> None:
        """Start the simulation Worker and the snapshot polling timer."""
        self.run_worker(self._run_simulation(), exclusive=True, exit_on_error=False)
        self.set_interval(1 / 5, self._poll_snapshot)

    def compose(self) -> ComposeResult:
        """Compose the dashboard layout: header + main-row + bottom-row (D-01)."""
        self._header_bar = HeaderBar()
        yield self._header_bar

        self._rationale_sidebar = RationaleSidebar()
        self._telemetry_footer = TelemetryFooter()
        self._bracket_panel = BracketPanel()

        with Container(id="main-row"):
            with Container(id="grid-container"):
                with Container(id="agent-grid"):
                    # Sequential row-by-row mapping (D-03)
                    for i, persona in enumerate(self.personas):
                        cell = AgentCell(agent_id=persona.id)
                        self._cells[persona.id] = cell
                        yield cell
            yield self._rationale_sidebar

        with Container(id="bottom-row"):
            yield self._telemetry_footer
            yield self._bracket_panel

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

        # NEW: Drain rationale entries from snapshot and add to sidebar (TUI-03)
        if self._rationale_sidebar is not None:
            for entry in snapshot.rationale_entries:
                self._rationale_sidebar.add_entry(entry)

        # NEW: Update telemetry footer from snapshot (TUI-04)
        if self._telemetry_footer is not None:
            self._telemetry_footer.update_from_snapshot(snapshot)

        # NEW: Update bracket panel only when summaries change (TUI-05)
        if self._bracket_panel is not None:
            if snapshot.bracket_summaries != self._prev_bracket_summaries:
                self._bracket_panel.update_summaries(snapshot.bracket_summaries)
                self._prev_bracket_summaries = snapshot.bracket_summaries

        self._prev_snapshot = snapshot
