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
from textual.timer import Timer
from textual.widget import Widget
from textual import work
from textual.widgets import Input, OptionList, RichLog, Static
from textual.widgets.option_list import Option

from alphaswarm.state import AgentState, BracketSummary, RationaleEntry, ReplayStore
from alphaswarm.types import SignalType, SimulationPhase

if TYPE_CHECKING:
    from alphaswarm.app import AppState
    from alphaswarm.config import AppSettings, BracketConfig
    from alphaswarm.graph import GraphStateManager
    from alphaswarm.interview import InterviewContext, InterviewEngine
    from alphaswarm.ollama_client import OllamaClient
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

    def render(self) -> str:
        return "   "

    def update_color(self, state: AgentState | None) -> None:
        """Update background color based on agent state. Only refreshes on change."""
        new_color = compute_cell_color(state)
        if new_color != self._current_color:
            self._current_color = new_color
            self.styles.background = new_color

    def on_click(self) -> None:
        """Open interview for this agent if simulation is complete (per D-02).

        Review #8: Real click-gate -- check replay mode first, notify user.
        """
        app = self.app
        if not isinstance(app, AlphaSwarmApp):
            return
        # Check if in replay mode first (per D-11, Review #8)
        if app._replay_store is not None:
            app.notify("Interviews unavailable during replay", severity="warning", timeout=3)
            return
        snapshot = app.app_state.state_store.snapshot()
        if snapshot.phase != SimulationPhase.COMPLETE:
            app.notify("Simulation in progress", severity="warning")
            return
        app.action_open_interview(self.agent_id)


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
    SimulationPhase.REPLAY: "Replay",
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

    def render_replay_header(
        self, cycle_id: str, round_num: int, auto_mode: bool, done: bool,
    ) -> None:
        """Render replay-mode header (per UI-SPEC, D-10)."""
        mode = "[DONE]" if done else ("[AUTO]" if auto_mode else "[PAUSED]")
        mode_color = "#78909C" if (done or not auto_mode) else "#66BB6A"
        self.update(
            f"  [#4FC3F7 bold]AlphaSwarm[/]  "
            f"[#78909C]|[/]  [#FFA726 bold]REPLAY[/] [#78909C]--[/] Cycle [#E0E0E0]{cycle_id}[/]  "
            f"[#78909C]|[/]  Round {round_num}/3  "
            f"[#78909C]|[/]  [{mode_color}]{mode}[/]  "
        )


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
        self._report_path: str = ""
        self._render_idle()

    def _render_idle(self) -> None:
        base = (
            "  [#78909C]RAM:[/] [#78909C]--[/]  "
            "[#78909C]|[/]  [#78909C]TPS:[/] [#78909C]--[/]  "
            "[#78909C]|[/]  [#78909C]Queue:[/] [#78909C]--[/]  "
            "[#78909C]|[/]  [#78909C]Slots:[/] [#78909C]--[/]"
        )
        if self._report_path:
            self.update(base + f"  [#78909C]|[/]  [#78909C]Report:[/] [#E0E0E0]{self._report_path}[/]")
        else:
            self.update(base)

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

        base = (
            f"  [#78909C]RAM:[/] [{ram_color}]{ram_pct:.0f}%[/]  "
            f"[#78909C]|[/]  [#78909C]TPS:[/] [#E0E0E0]{snapshot.tps:.1f}[/]  "
            f"[#78909C]|[/]  [#78909C]Queue:[/] [#E0E0E0]{gm.active_count}[/]  "
            f"[#78909C]|[/]  [#78909C]Slots:[/] [#E0E0E0]{gm.current_slots}[/]"
        )
        if self._report_path:
            self.update(base + f"  [#78909C]|[/]  [#78909C]Report:[/] [#E0E0E0]{self._report_path}[/]")
        else:
            self.update(base)

    def update_report_path(self, path: str) -> None:
        """Display the report file path in the footer (Phase 15, D-06)."""
        self._report_path = path
        self.update(f"Report: {path}")

    def render_replay_footer(self, cycle_id: str, round_num: int) -> None:
        """Render replay-mode footer with key hints (per UI-SPEC)."""
        self.update(
            f"  [#78909C]Mode:[/] [#E0E0E0]Replay[/]  "
            f"[#78909C]|[/]  [#78909C]Cycle:[/] [#E0E0E0]{cycle_id}[/]  "
            f"[#78909C]|[/]  [#78909C]Round:[/] [#E0E0E0]{round_num}/3[/]  "
            f"[#78909C]|[/]  [#4FC3F7]Space/Right:[/] [#E0E0E0]Next[/]  "
            f"[#4FC3F7]P:[/] [#E0E0E0]Play/Pause[/]  "
            f"[#4FC3F7]Esc:[/] [#E0E0E0]Exit[/]"
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
        self._delta_mode: bool = False
        self._delta_data: dict | None = None  # type: ignore[type-arg]

    def update_summaries(self, summaries: tuple[BracketSummary, ...]) -> None:
        """Store bracket summaries and trigger a re-render."""
        self._summaries = summaries
        self.refresh()

    def enable_delta_mode(self, delta_data: dict) -> None:  # type: ignore[type-arg]
        """Activate delta mode with shock impact data (per D-01, UI-SPEC)."""
        self._delta_mode = True
        self._delta_data = delta_data
        self.refresh()

    def reset_delta_mode(self) -> None:
        """Reset to live mode (for use on new simulation start in same TUI session)."""
        self._delta_mode = False
        self._delta_data = None
        self.refresh()

    def _render_live(self) -> Text:
        """Render bracket live-mode bars (original render logic)."""
        text = Text()
        text.append("Brackets\n", style="bold #4FC3F7")
        if not self._summaries:
            text.append("Awaiting data...\n", style="#78909C")
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

    def _render_delta(self) -> Text:
        """Render bracket delta bars (compact delta-only style per UI-SPEC)."""
        try:
            data = self._delta_data
            if not data or not data.get("bracket_deltas"):
                return self._render_live()
            text = Text()
            text.append("Brackets\n", style="bold #4FC3F7")
            round_n = data.get("injected_before_round", "?")
            text.append(f"[DELTA · Shock before Round {round_n}]\n", style="#4FC3F7")
            for b in data["bracket_deltas"]:
                bracket = b.get("bracket", "")
                dominant = b.get("dominant_post", "HOLD").upper()
                arrow = b.get("dominant_arrow", "·")
                delta = b.get("delta_buy_pct", 0.0)
                color = self._SIGNAL_COLORS.get(dominant.lower(), "#78909C")
                # Bar fill = abs(delta) / 100 * BAR_WIDTH, capped at BAR_WIDTH
                filled = min(round(abs(delta) / 100 * self.BAR_WIDTH), self.BAR_WIDTH)
                empty = self.BAR_WIDTH - filled
                delta_style = "#66BB6A" if delta > 0 else "#EF5350" if delta < 0 else "#78909C"
                text.append(f"{bracket:<14}  ", style="#78909C")
                text.append(f"{dominant:<4} ", style=color)
                text.append(f"{arrow} ", style=delta_style)
                text.append("[")
                text.append(self.FILL_CHAR * filled, style=color)
                text.append(self.EMPTY_CHAR * empty, style="#333333")
                text.append("] ", style="#E0E0E0")
                text.append(f"{delta:+.0f}%\n", style=f"bold {delta_style}")
            return text
        except Exception:
            import structlog as _structlog
            _structlog.get_logger(component="tui").warning(
                "bracket_delta_render_error",
                cycle_delta_data_keys=list((self._delta_data or {}).keys()),
            )
            self._delta_mode = False
            return self._render_live()

    def render(self) -> Text:
        """Dispatch to delta or live render based on mode."""
        if self._delta_mode and self._delta_data:
            return self._render_delta()
        return self._render_live()

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
# InterviewScreen — post-simulation agent Q&A overlay (Phase 14)
# ---------------------------------------------------------------------------


class InterviewScreen(Screen[None]):
    """Full-screen agent interview overlay (per D-01).

    Pushed on top of the dashboard. Agent ID in header, scrollable Q&A
    transcript (RichLog), input box at bottom. Escape pops back to grid.
    """

    BINDINGS = [("escape", "exit_interview", "Exit Interview")]

    DEFAULT_CSS = """
    InterviewScreen {
        background: #121212;
    }

    #interview-header {
        width: 100%;
        height: 1;
        background: #1E1E1E;
        color: #4FC3F7;
        text-style: bold;
        text-align: center;
        padding: 0 1;
    }

    #transcript {
        width: 100%;
        height: 1fr;
        background: #121212;
        color: #E0E0E0;
        padding: 0 1;
        margin: 0 0 0 0;
    }

    #interview-input {
        dock: bottom;
        width: 100%;
        margin: 0 1;
    }

    #interview-status {
        dock: bottom;
        width: 100%;
        height: 1;
        background: #1E1E1E;
        color: #78909C;
        text-align: center;
    }
    """

    def __init__(
        self,
        agent_id: str,
        cycle_id: str,
        graph_manager: GraphStateManager,
        ollama_client: OllamaClient,
        worker_model: str,
    ) -> None:
        super().__init__()
        self._agent_id = agent_id
        self._cycle_id = cycle_id
        self._graph_manager = graph_manager
        self._ollama_client = ollama_client
        self._worker_model = worker_model
        self._engine: InterviewEngine | None = None
        self._context: InterviewContext | None = None

    def compose(self) -> ComposeResult:
        yield Static(f"Interview: {self._agent_id}", id="interview-header")
        yield RichLog(id="transcript", markup=True, wrap=True, auto_scroll=True)
        yield Static("Esc to exit  |  Enter to send", id="interview-status")
        yield Input(placeholder="Ask a question...", id="interview-input")

    def on_mount(self) -> None:
        """Load agent context and initialize interview engine."""
        self.query_one("#interview-input", Input).focus()
        self.run_worker(self._initialize_engine(), exclusive=True, exit_on_error=False)

    async def _initialize_engine(self) -> None:
        """Load agent context from Neo4j and create InterviewEngine."""
        from alphaswarm.interview import InterviewEngine

        transcript = self.query_one("#transcript", RichLog)
        try:
            transcript.write(Text.from_markup("[#78909C]Loading agent context...[/]"))
            self._context = await self._graph_manager.read_agent_interview_context(
                self._agent_id, self._cycle_id
            )
            self._engine = InterviewEngine(
                context=self._context,
                ollama_client=self._ollama_client,
                model=self._worker_model,
            )
            # Update header with agent name
            header = self.query_one("#interview-header", Static)
            header.update(f"Interview: {self._context.agent_name} [{self._context.bracket}]")
            transcript.write(Text.from_markup(
                f"[#66BB6A]{self._context.agent_name} is ready to discuss their simulation decisions.[/]"
            ))
            transcript.write(Text(""))
        except Exception as e:
            transcript.write(Text.from_markup(f"[#EF5350]Failed to load agent context: {e}[/]"))
            logger.error("interview_init_failed", agent_id=self._agent_id, error=str(e))

    @work(exclusive=True)
    async def _send_message_worker(self, user_message: str) -> None:
        """Worker: send message to LLM, write response to transcript."""
        if self._engine is None or self._context is None:
            return
        transcript = self.query_one("#transcript", RichLog)
        transcript.write(Text.from_markup(f"[#4FC3F7]You:[/] {user_message}"))
        transcript.write(Text.from_markup("[#78909C]Thinking...[/]"))
        try:
            response = await self._engine.ask(user_message)
            transcript.write(Text.from_markup(f"[#66BB6A]{self._context.agent_name}:[/] {response}"))
            transcript.write(Text(""))  # blank line separator
        except Exception as e:
            transcript.write(Text.from_markup(f"[#EF5350]Error:[/] {e}"))
        self.query_one("#interview-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle user message submission."""
        message = event.value.strip()
        if not message:
            return
        event.input.value = ""  # clear input
        self._send_message_worker(message)

    def action_exit_interview(self) -> None:
        """Pop this screen and return to the dashboard (per D-01)."""
        self.dismiss(None)


# ---------------------------------------------------------------------------
# CyclePickerScreen — cycle selection overlay for replay mode (Phase 28)
# ---------------------------------------------------------------------------


class CyclePickerScreen(Screen[str | None]):
    """Cycle selection overlay for replay mode (per D-02, UI-SPEC).

    Review #4: Receives cycles from read_completed_cycles() -- only completed
    cycles (those with Round 3 decisions) are shown.
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    CyclePickerScreen {
        align: center middle;
        background: #121212;
    }

    #cycle-container {
        width: 56;
        height: auto;
        max-height: 16;
        border: solid #4FC3F7;
        padding: 1 2;
        background: #1E1E1E;
    }

    #cycle-title {
        width: 100%;
        text-align: center;
        color: #4FC3F7;
        text-style: bold;
        margin-bottom: 1;
    }

    #cycle-hint {
        width: 100%;
        text-align: center;
        color: #78909C;
        margin-top: 1;
    }
    """

    def __init__(self, cycles: list[dict]) -> None:
        super().__init__()
        self._cycles = cycles

    def compose(self) -> ComposeResult:
        with Container(id="cycle-container"):
            yield Static("Select Simulation Cycle", id="cycle-title")
            options: list[Option] = []
            for i, c in enumerate(self._cycles):
                short_id = str(c["cycle_id"])[:8]
                created = c.get("created_at", "")
                # Handle neo4j DateTime: convert to string if not already
                if hasattr(created, "to_native"):
                    created = created.to_native().strftime("%Y-%m-%d %H:%M")
                else:
                    created = str(created)[:16]
                suffix = "  (latest)" if i == 0 else ""
                label = f"{created}  --  {short_id}{suffix}"
                options.append(Option(label, id=str(c["cycle_id"])))
            yield OptionList(*options, id="cycle-list")
            yield Static(
                "Up/Down to select  \u00b7  Enter to replay  \u00b7  Esc to cancel",
                id="cycle-hint",
            )

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(str(event.option_id))

    def action_cancel(self) -> None:
        self.dismiss(None)


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

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("s", "save_results", "Save"),
        ("r", "start_replay", "Replay"),
        ("p", "toggle_replay_mode", "Play/Pause"),
        ("space", "replay_next_round", "Next Round"),
        ("right", "replay_next_round", "Next Round"),
    ]

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
        self._cycle_id: str | None = None
        self._last_sentinel_mtime: float = 0.0  # Phase 15: sentinel file polling (D-06, Pitfall 5)
        # Phase 28 -- replay mode state
        self.replay_cycle_id: str | None = None  # Set by CLI _handle_replay; None for normal TUI
        self.replay_cli_mode: bool = False        # Review #3: True when launched via CLI
        self._replay_store: ReplayStore | None = None
        self._replay_timer: Timer | None = None
        self._replay_round: int = 0
        self._replay_auto: bool = True
        self._replay_done: bool = False
        self._replay_cycle_short_id: str = ""
        self._replay_last_rendered_round: int = 0  # Review #2: tracks rendered round for sidebar dedup
        # Phase 26 — shock injection overlay edge latch
        self._shock_window_was_open: bool = False
        # Phase 27 — BracketPanel delta mode activation latch
        self._bracket_panel_delta_active: bool = False

    def on_mount(self) -> None:
        """Register theme, then start simulation or enter replay mode."""
        self.register_theme(ALPHASWARM_THEME)
        self.theme = "alphaswarm"

        if self.replay_cycle_id is not None:
            # CLI replay mode: skip simulation, enter replay directly
            self.set_interval(1 / 5, self._poll_snapshot)
            self.run_worker(
                self._enter_replay(self.replay_cycle_id),
                exclusive=True,
                exit_on_error=False,
            )
        elif not self.rumor:
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
            result = await run_simulation(
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
            self._cycle_id = result.cycle_id
            # Ensure COMPLETE is visible
            await self.app_state.state_store.set_phase(SimulationPhase.COMPLETE)
            # Build completion summary from final snapshot
            snap = self.app_state.state_store.snapshot()
            elapsed = _format_elapsed(snap.elapsed_seconds)
            signals = {"BUY": 0, "SELL": 0, "HOLD": 0}
            for st in snap.agent_states.values():
                if st and st.signal:
                    signals[st.signal] = signals.get(st.signal, 0) + 1
            self.notify(
                f"Simulation complete in {elapsed} — "
                f"BUY: {signals['BUY']}  SELL: {signals['SELL']}  HOLD: {signals['HOLD']}. "
                f"Press q to exit.",
                timeout=0,
            )
        except BaseException as e:
            # BaseException catches ExceptionGroup (Python 3.11+) which wraps
            # GovernorCrisisError when it propagates through asyncio.TaskGroup.
            logger.error("simulation_worker_failed", error=str(e))
            self.notify(
                f"Simulation failed: {e}. Press q to exit.",
                severity="error",
                timeout=0,
            )

    def action_open_interview(self, agent_id: str) -> None:
        """Push InterviewScreen overlay for the given agent (per D-01)."""
        if self._cycle_id is None:
            self.notify("No simulation completed yet", severity="warning")
            return
        if self.app_state.graph_manager is None:
            self.notify("Neo4j not connected", severity="error")
            return
        if self.app_state.ollama_client is None:
            self.notify("Ollama not connected", severity="error")
            return
        self.push_screen(
            InterviewScreen(
                agent_id=agent_id,
                cycle_id=self._cycle_id,
                graph_manager=self.app_state.graph_manager,
                ollama_client=self.app_state.ollama_client,
                worker_model=self.sim_settings.ollama.worker_model_alias,
            )
        )

    def action_save_results(self) -> None:
        """Save simulation results to a markdown file in results/."""
        import datetime
        from pathlib import Path

        if self._replay_store is not None:
            self.notify("Save unavailable during replay", severity="warning", timeout=3)
            return

        snap = self.app_state.state_store.snapshot()
        if snap.phase != SimulationPhase.COMPLETE:
            self.notify("Simulation not complete yet.", severity="warning")
            return

        results_dir = Path("results")
        results_dir.mkdir(exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = results_dir / f"sim_{ts}.md"

        elapsed = _format_elapsed(snap.elapsed_seconds)
        signals = {"BUY": 0, "SELL": 0, "HOLD": 0}
        for st in snap.agent_states.values():
            if st and st.signal:
                signals[st.signal] = signals.get(st.signal, 0) + 1

        lines = [
            f"# AlphaSwarm Simulation Results",
            f"",
            f"**Rumor:** {self.rumor}",
            f"**Elapsed:** {elapsed}",
            f"**Date:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}",
            f"",
            f"## Consensus",
            f"",
            f"| Signal | Count |",
            f"|--------|-------|",
            f"| BUY | {signals['BUY']} |",
            f"| SELL | {signals['SELL']} |",
            f"| HOLD | {signals['HOLD']} |",
            f"",
            f"## Brackets",
            f"",
            f"| Bracket | BUY | SELL | HOLD | Avg Confidence |",
            f"|---------|-----|------|------|----------------|",
        ]
        for b in snap.bracket_summaries:
            lines.append(
                f"| {b.display_name} | {b.buy_count} | {b.sell_count} "
                f"| {b.hold_count} | {b.avg_confidence:.0%} |"
            )

        lines.extend([
            f"",
            f"## Agent Decisions",
            f"",
            f"| Agent | Signal | Confidence |",
            f"|-------|--------|------------|",
        ])
        for agent_id in sorted(snap.agent_states.keys()):
            st = snap.agent_states[agent_id]
            if st and st.signal:
                lines.append(f"| {agent_id} | {st.signal} | {st.confidence:.0%} |")

        filename.write_text("\n".join(lines) + "\n")
        self.notify(f"Results saved to {filename}")

    # -------------------------------------------------------------------------
    # Phase 28: Replay mode methods
    # -------------------------------------------------------------------------

    async def _enter_replay(self, cycle_id: str) -> None:
        """Load cycle signals and enter replay mode (per D-06, D-08, D-09).

        ORDERING: Set _replay_store BEFORE any phase change. This prevents
        _poll_snapshot race (RESEARCH Pitfall 3).
        """
        if self.app_state.graph_manager is None:
            self.notify("Neo4j not connected -- cannot replay", severity="error")
            return
        gm = self.app_state.graph_manager
        try:
            signals = await gm.read_full_cycle_signals(cycle_id)
        except Exception as e:
            self.notify(f"Failed to load cycle data: {e}", severity="error", timeout=0)
            return
        if not signals:
            self.notify("No decision data found for this cycle", severity="error")
            return

        short_id = cycle_id[:8]
        self._replay_cycle_short_id = short_id
        self._replay_round = 1
        self._replay_auto = True
        self._replay_done = False
        self._replay_last_rendered_round = 0  # Review #2: force sidebar update on first round

        # Set store BEFORE phase change (Pitfall 3 mitigation)
        self._replay_store = ReplayStore(cycle_id=cycle_id, signals=signals)
        self._replay_store.set_round(1)

        # Load on-demand per-round data for Round 1 (per D-07)
        await self._load_replay_round_data(cycle_id, 1)

        # Start auto-advance timer (per D-03, 3s interval)
        self._replay_timer = self.set_interval(3.0, self._advance_replay_round)

        self.notify(
            f"Replaying cycle {short_id} -- 3 rounds, 3s per round",
            timeout=5,
        )

    async def _load_replay_round_data(self, cycle_id: str, round_num: int) -> None:
        """Load on-demand bracket and rationale data for a round (per D-07).

        Called during round transitions. Uses existing graph methods filtered by round.

        Review #11: Stale load guard -- if self._replay_round has advanced past
        round_num by the time this async method completes, discard the result
        to prevent overwriting newer round data.
        """
        if self.app_state.graph_manager is None or self._replay_store is None:
            return
        gm = self.app_state.graph_manager

        # Load bracket narratives for this round
        try:
            bracket_rows = await gm.read_bracket_narratives_for_round(cycle_id, round_num)
            # Review #11: Stale load guard
            if self._replay_store is None or round_num != self._replay_round:
                return  # Round advanced while we were loading; discard stale data
            bracket_summaries = tuple(
                BracketSummary(
                    bracket=row["bracket"],
                    display_name=row["bracket"].replace("_", " ").title(),
                    buy_count=int(row["buy_count"]),
                    sell_count=int(row["sell_count"]),
                    hold_count=int(row["hold_count"]),
                    total=int(row["buy_count"]) + int(row["sell_count"]) + int(row["hold_count"]),
                    avg_confidence=float(row["avg_confidence"]),
                    avg_sentiment=float(row["avg_sentiment"]),
                )
                for row in bracket_rows
            )
            self._replay_store.set_bracket_summaries(bracket_summaries)
        except Exception:
            logger.warning("replay_bracket_load_failed", cycle_id=cycle_id, round_num=round_num)

        # Load rationale entries for this round (per D-07, Pitfall 7)
        try:
            rationale_rows = await gm.read_rationale_entries_for_round(cycle_id, round_num, limit=10)
            # Review #11: Stale load guard (check again after second await)
            if self._replay_store is None or round_num != self._replay_round:
                return  # Round advanced while we were loading; discard stale data
            # Look up agent names from persona list (Pitfall 7 mitigation)
            persona_map = {p.id: p.name for p in self.personas}
            rationale_entries = tuple(
                RationaleEntry(
                    agent_id=persona_map.get(row["agent_id"], row["agent_id"]),
                    signal=SignalType(row["signal"]) if row["signal"] else SignalType.HOLD,
                    rationale=(row.get("rationale") or "")[:50],
                    round_num=round_num,
                )
                for row in rationale_rows
            )
            self._replay_store.set_rationale_entries(rationale_entries)
        except Exception:
            logger.warning("replay_rationale_load_failed", cycle_id=cycle_id, round_num=round_num)

    def _advance_replay_round(self) -> None:
        """Timer callback: advance to next replay round (per D-03, D-05).

        After Round 3 is displayed, stops timer and shows [DONE] indicator.
        """
        if self._replay_store is None:
            return
        if self._replay_round >= 3:
            # End of replay (per D-05)
            if self._replay_timer is not None:
                self._replay_timer.stop()
            self._replay_done = True
            self.notify("Replay complete -- Esc to exit", timeout=0)
            return
        self._replay_round += 1
        self._replay_store.set_round(self._replay_round)

        # Load on-demand data for the new round (async via run_worker)
        cycle_id = self._replay_store._cycle_id
        self.run_worker(
            self._load_replay_round_data(cycle_id, self._replay_round),
            exclusive=False,
            exit_on_error=False,
        )

    def action_start_replay(self) -> None:
        """Enter replay mode from TUI (per D-01, D-02). Gated on COMPLETE."""
        snapshot = self.app_state.state_store.snapshot()
        if snapshot.phase != SimulationPhase.COMPLETE:
            return  # Silently ignore -- not in COMPLETE phase
        if self._replay_store is not None:
            return  # Already in replay
        if self.app_state.graph_manager is None:
            self.notify("Neo4j not connected -- cannot replay", severity="error")
            return
        # Load completed cycles and show picker (or auto-select if only one)
        self.run_worker(
            self._start_replay_picker(),
            exclusive=True,
            exit_on_error=False,
        )

    async def _start_replay_picker(self) -> None:
        """Load completed cycles and push CyclePickerScreen (per D-02).

        Review #4: Uses read_completed_cycles() to filter to completed cycles only.
        """
        if self.app_state.graph_manager is None:
            return
        gm = self.app_state.graph_manager
        try:
            cycles = await gm.read_completed_cycles(limit=10)
        except Exception as e:
            self.notify(f"Failed to load cycles: {e}", severity="error")
            return
        if not cycles:
            self.notify("No completed simulation cycles found", severity="error")
            return
        if len(cycles) == 1:
            # Auto-select single cycle (per D-02: skip picker if only one)
            await self._enter_replay(cycles[0]["cycle_id"])
        else:
            self.push_screen(
                CyclePickerScreen(cycles),
                self._on_cycle_selected,
            )

    def _on_cycle_selected(self, cycle_id: str | None) -> None:
        """Callback from CyclePickerScreen dismiss (per D-02)."""
        if cycle_id is None:
            return  # User cancelled
        self.run_worker(
            self._enter_replay(cycle_id),
            exclusive=True,
            exit_on_error=False,
        )

    def action_toggle_replay_mode(self) -> None:
        """Toggle auto/manual replay mode (per D-03)."""
        if self._replay_store is None or self._replay_done:
            return
        if self._replay_auto:
            if self._replay_timer is not None:
                self._replay_timer.pause()
            self._replay_auto = False
            self.notify("Manual mode -- Space or Right to advance", timeout=3)
        else:
            if self._replay_timer is not None:
                self._replay_timer.resume()
            self._replay_auto = True
            self.notify("Auto-advance mode -- 3s per round", timeout=3)

    def action_replay_next_round(self) -> None:
        """Advance to next round in manual mode (per D-04)."""
        if self._replay_store is None or self._replay_done:
            return
        if self._replay_auto:
            return  # Ignored in auto mode (per D-04)
        self._advance_replay_round()

    def action_exit_replay(self) -> None:
        """Exit replay mode (per D-05, D-12).

        Review #3: CLI replay exits app entirely (no StateStore to restore).
        In-app replay restores COMPLETE state from prior StateStore snapshot.

        MUST stop timer before clearing store (Pitfall 2 mitigation).
        """
        if self._replay_store is None:
            return
        # Stop auto-advance timer (Pitfall 2)
        if self._replay_timer is not None:
            self._replay_timer.stop()
            self._replay_timer = None
        # Clear replay state
        self._replay_store = None
        self._replay_round = 0
        self._replay_auto = True
        self._replay_done = False
        self._replay_cycle_short_id = ""
        self._replay_last_rendered_round = 0

        # Review #3: CLI replay has no prior StateStore to restore
        if self.replay_cli_mode:
            self.exit()
            return

        # In-app replay: restore COMPLETE state from StateStore
        # Clear rationale sidebar from replay entries
        if self._rationale_sidebar is not None:
            self._rationale_sidebar._entries.clear()
            self._rationale_sidebar.refresh()

        # Restore BracketPanel to live mode
        if self._bracket_panel is not None:
            self._bracket_panel.reset_delta_mode()

    def key_escape(self) -> None:
        """Handle Escape: exit replay if active, otherwise ignore."""
        if self._replay_store is not None:
            self.action_exit_replay()

    def _poll_snapshot(self) -> None:
        """Timer callback: read snapshot, diff, update changed cells.

        Per TUI-02: Only refreshes cells that actually changed.
        Phase 28: Branches on _replay_store to read from ReplayStore (RESEARCH Pattern 2).
        """
        # Replay mode: read from ReplayStore instead of StateStore (per RESEARCH Pattern 2)
        if self._replay_store is not None:
            snapshot = self._replay_store.snapshot()
        else:
            snapshot = self.app_state.state_store.snapshot()

        if self._prev_snapshot is None:
            # First tick: update all cells and header
            for agent_id, cell in self._cells.items():
                agent_state = snapshot.agent_states.get(agent_id)
                cell.update_color(agent_state)
            if self._header_bar is not None:
                if self._replay_store is not None:
                    self._header_bar.render_replay_header(
                        cycle_id=self._replay_cycle_short_id,
                        round_num=self._replay_round,
                        auto_mode=self._replay_auto,
                        done=self._replay_done,
                    )
                else:
                    self._header_bar.update_from_snapshot(snapshot)
        else:
            # Diff: only update changed agents
            for agent_id, cell in self._cells.items():
                new_state = snapshot.agent_states.get(agent_id)
                old_state = self._prev_snapshot.agent_states.get(agent_id)
                if new_state != old_state:
                    cell.update_color(new_state)

            # Update header
            if self._header_bar is not None:
                if self._replay_store is not None:
                    # Replay header: update every tick (round/mode can change)
                    self._header_bar.render_replay_header(
                        cycle_id=self._replay_cycle_short_id,
                        round_num=self._replay_round,
                        auto_mode=self._replay_auto,
                        done=self._replay_done,
                    )
                elif (
                    snapshot.phase != self._prev_snapshot.phase
                    or snapshot.round_num != self._prev_snapshot.round_num
                    or int(snapshot.elapsed_seconds) != int(self._prev_snapshot.elapsed_seconds)
                ):
                    # Live mode: only update header if phase, round, or elapsed changed
                    self._header_bar.update_from_snapshot(snapshot)

        # Rationale sidebar update
        # Review #2: During replay, only update sidebar when round changes to prevent
        # duplication (ReplayStore.snapshot() returns same entries every poll tick).
        if self._replay_store is not None:
            if self._replay_round != self._replay_last_rendered_round:
                # Round changed -- update sidebar with new entries
                self._replay_last_rendered_round = self._replay_round
                if self._rationale_sidebar is not None:
                    self._rationale_sidebar._entries.clear()
                    for entry in snapshot.rationale_entries:
                        self._rationale_sidebar.add_entry(entry)
            # Skip normal rationale processing during replay (no drain needed)
        else:
            # Normal (non-replay) rationale processing -- drain queue
            if self._rationale_sidebar is not None:
                for entry in snapshot.rationale_entries:
                    self._rationale_sidebar.add_entry(entry)

        # Telemetry footer
        if self._telemetry_footer is not None:
            if self._replay_store is not None:
                # Replay footer: show replay-specific key hints
                self._telemetry_footer.render_replay_footer(
                    cycle_id=self._replay_cycle_short_id,
                    round_num=self._replay_round,
                )
            else:
                self._telemetry_footer.update_from_snapshot(snapshot)

        # Update bracket panel only when summaries change (TUI-05)
        if self._bracket_panel is not None:
            if snapshot.bracket_summaries != self._prev_bracket_summaries:
                self._bracket_panel.update_summaries(snapshot.bracket_summaries)
                self._prev_bracket_summaries = snapshot.bracket_summaries

        self._prev_snapshot = snapshot

        # Phase 15: Check for report sentinel file (D-06) -- skip during replay
        if self._replay_store is None:
            import json as _json
            from pathlib import Path as _Path
            sentinel_path = _Path(".alphaswarm") / "last_report.json"
            try:
                if sentinel_path.exists():
                    mtime = sentinel_path.stat().st_mtime
                    if mtime > self._last_sentinel_mtime:
                        self._last_sentinel_mtime = mtime
                        data = _json.loads(sentinel_path.read_text())
                        report_path = data.get("path", "")
                        if self._telemetry_footer is not None:
                            self._telemetry_footer.update_report_path(report_path)
            except (OSError, ValueError, KeyError):
                pass  # Sentinel file may be mid-write or malformed; skip silently

            # Phase 27 — activate BracketPanel delta mode post-simulation when shock detected
            self._check_bracket_delta_mode()

    def _check_bracket_delta_mode(self) -> None:
        """Phase 27 — trigger delta mode once when simulation completes with a shock.

        Called from _poll_snapshot (sync context). Uses run_worker for async graph read.
        The latch _bracket_panel_delta_active is set INSIDE the async worker AFTER
        enable_delta_mode() succeeds — not here. This allows retry on transient errors.
        """
        snapshot = self.app_state.state_store.snapshot()
        if (
            snapshot.phase == SimulationPhase.COMPLETE
            and self._cycle_id is not None
            and self._bracket_panel is not None
            and not self._bracket_panel_delta_active
        ):
            self.run_worker(
                self._activate_bracket_delta_mode(self._cycle_id),
                exclusive=False,
                exit_on_error=False,
            )

    async def _activate_bracket_delta_mode(self, cycle_id: str) -> None:
        """Phase 27 — async worker: read shock impact and enable BracketPanel delta mode.

        Only activates if a ShockEvent exists for the cycle.
        Runs in Textual's worker thread pool (never on the sync timer callback).

        LATCH TIMING: _bracket_panel_delta_active is set AFTER enable_delta_mode() succeeds.
        If this worker exits early (no shock, no graph_manager), the latch stays False and
        _check_bracket_delta_mode will re-run on the next 200ms tick. Once enable_delta_mode()
        is called, the latch is set to prevent further re-triggers.
        """
        if self.app_state.graph_manager is None:
            return
        gm = self.app_state.graph_manager
        shock_event = await gm.read_shock_event(cycle_id)
        if shock_event is None:
            # No shock for this cycle — live mode persists forever. Set latch to prevent
            # repeated Neo4j calls on every tick for a confirmed no-shock cycle.
            self._bracket_panel_delta_active = True
            return
        delta_data = await gm.read_shock_impact(cycle_id)
        if self._bracket_panel is not None:
            self._bracket_panel.enable_delta_mode(delta_data)
        # Latch is set ONLY after successful enable_delta_mode() call.
        # On transient failure before this line, latch stays False and next tick retries.
        self._bracket_panel_delta_active = True
