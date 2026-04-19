# Phase 9: TUI Core Dashboard - Research

**Researched:** 2026-03-26
**Domain:** Textual TUI framework, async event loop integration, snapshot-based rendering
**Confidence:** HIGH

## Summary

Phase 9 builds a real-time terminal dashboard using Textual (>=8.1.1) that displays a 10x10 agent grid with color-coded cells, a header bar showing simulation status, and snapshot-based rendering on a 200ms timer. The simulation runs as a Textual Worker (background asyncio task) within the TUI's event loop, with `StateStore` as the shared bridge between simulation writes and TUI reads.

The Textual framework provides all required primitives: `layout: grid` with `grid-size: 10 10` for the agent grid, custom `Widget` subclasses with `DEFAULT_CSS` for cell styling, `set_interval(0.2, callback)` for the 200ms snapshot timer, `run_worker()` for background simulation execution, and `register_theme()` for custom dark theming. The existing codebase has a `StateStore` stub explicitly designed for Phase 9 expansion, a `SimulationPhase` enum that maps directly to header status labels, and `AppState` already holding a `state_store` reference.

**Primary recommendation:** Use Textual's `run_worker()` to launch `run_simulation()` as a background async Worker, with `StateStore` expanded to hold per-agent state via `asyncio.Lock`-guarded writes. The TUI reads immutable `StateSnapshot` objects on a 200ms `set_interval` timer and diffs against the previous snapshot to minimize redraws. Critical integration pitfall: `create_app_state()` calls `run_until_complete()` for Neo4j verification, which will crash inside Textual's already-running event loop -- must be called BEFORE `App.run()` (same pattern as existing `_handle_run` in cli.py).

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Same process, TUI-owned event loop. A new `tui` CLI subcommand launches the Textual app as the main process. The simulation (`run_simulation()`) runs as a Textual Worker (background asyncio task) within the same event loop. StateStore is the shared bridge -- simulation writes, TUI reads. No IPC, no separate processes. Invocation: `python -m alphaswarm tui "rumor"`.
- **D-02:** Per-agent StateStore writes. The simulation writes each agent's decision to StateStore immediately after it resolves (not at round end). TUI's 200ms snapshot timer picks up whatever settled since the last tick. Grid cells light up one-by-one as agents finish their inference -- visually dynamic, showing the wave of decisions propagating across the grid.
- **D-03:** Sequential, row by row. Agents 1-10 fill row 1, agents 11-20 fill row 2, and so on. Agent ID determines grid position. No semantic grouping by bracket in Phase 9. Clean and predictable -- color tells the story, not layout.
- **D-04:** Color + confidence as brightness. Hue encodes signal (green=bullish, red=bearish, gray=pending). Brightness encodes confidence -- low confidence (0.2) renders as a dim shade, high confidence (1.0) renders as full-intensity color. No text inside cells.
- **D-05:** Pending cells = fixed dim gray. Agents with no decision yet this round always render as the same dim gray, regardless of any prior state. Clear visual distinction between "not yet decided" and "decided with low confidence."
- **D-06:** Status + elapsed + round counter. Header displays: `[SimulationPhase status] | Round X/3 | Elapsed: HH:MM:SS`. Explicit round counter (`Round X/3`) alongside the status label. No seed rumor text in Phase 9 -- deferred to Phase 10.

### Claude's Discretion
- Textual component structure: which Widgets to use, custom CSS, app layout file organization
- asyncio.Lock implementation details for StateStore thread safety
- How the 200ms snapshot timer is implemented in Textual (`set_interval` vs reactive attribute)
- Specific color values and gradient math for confidence-as-brightness (the exact RGB/hex for dim vs bright green/red)
- How `tui` subcommand is wired into the existing argparse structure in cli.py

### Deferred Ideas (OUT OF SCOPE)
- Seed rumor text display in header -- deferred to Phase 10 (rationale sidebar phase)
- Agent hover tooltip (signal + confidence + rationale preview) -- not in Phase 9 scope
- Bracket row grouping in grid -- sequential layout chosen for Phase 9; bracket grouping could be a Phase 10 enhancement
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| TUI-01 | Textual app with 10x10 agent grid where each cell represents one agent, color-coded by current sentiment (green=bullish, red=bearish, gray=neutral/pending) | Textual `layout: grid` with `grid-size: 10 10` and `grid-gutter: 0`; custom `AgentCell(Widget)` with dynamic background color via `styles.background`; HSL color formula from UI-SPEC |
| TUI-02 | Snapshot-based rendering -- agents write to shared StateStore, TUI reads immutable snapshots on 200ms set_interval timer, only updating changed cells | `set_interval(1/5, callback)` on App/Widget; `StateSnapshot` frozen dataclass with per-agent dict; diff previous vs current snapshot; selective `cell.refresh()` |
| TUI-06 | Header displays global simulation status (Idle, Seeding, Round 1/2/3, Complete) and elapsed time | `SimulationPhase` enum already defines all status values; `Static` widget for header bar; `time.monotonic()` for elapsed time tracking |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

- **Concurrency:** 100% async (`asyncio`). No blocking I/O on the main event loop.
- **Runtime:** Python 3.11+ (Strict typing), `uv` (Package manager), `pytest-asyncio`.
- **UI:** `textual` (>=8.1.1) for a clean, minimalist terminal dashboard.
- **Logging:** `structlog` with component-scoped loggers.
- **Immutability pattern:** Frozen dataclasses for result containers.
- **Batch operations:** `asyncio.TaskGroup` (not bare `create_task`).
- **Clean/minimalist aesthetic** preferred by developer.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| textual | 8.1.1 | Terminal UI framework | CLAUDE.md mandates >=8.1.1; latest on PyPI; provides grid layout, custom widgets, Workers, timers, theming |
| asyncio | stdlib | Event loop, Lock, task management | Python stdlib; Textual Workers run on same asyncio loop |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| time (monotonic) | stdlib | Elapsed wall-clock time | Header elapsed timer -- `time.monotonic()` for drift-resistant timing |
| colorsys | stdlib | HSL to RGB conversion | Confidence-to-brightness color mapping (HSL lightness channel) |

### Testing
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest-asyncio | >=0.24.0 | Async test support | Already in dev dependencies; required for Textual `run_test()` |
| textual (run_test) | 8.1.1 | Headless app testing | Built into textual; `async with app.run_test() as pilot:` pattern |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| textual `set_interval` | reactive attribute + watcher | `set_interval` is simpler for fixed-rate polling; reactive is better for event-driven updates. For 200ms snapshot polling, `set_interval` is the right choice. |
| `colorsys.hls_to_rgb` | manual HSL math | colorsys is stdlib and handles edge cases; no reason to hand-roll |
| `asyncio.Lock` | no lock (single event loop) | Lock is needed because StateStore writes from Worker and reads from timer callback both run on the same event loop but interleave at await points |

**Installation:**
```bash
uv add textual>=8.1.1
```

**Version verification:** textual 8.1.1 confirmed as latest on PyPI (verified 2026-03-26). Not yet in pyproject.toml -- must be added as a dependency.

## Architecture Patterns

### Recommended Project Structure
```
src/alphaswarm/
    tui.py            # Textual App, AgentCell, AgentGrid, HeaderBar widgets
    state.py          # StateStore (expanded), StateSnapshot, AgentState
    cli.py            # Add 'tui' subcommand
    simulation.py     # Inject state_store.update_agent_state() calls
    types.py          # Unchanged (SimulationPhase, SignalType already exist)
```

### Pattern 1: Worker-Based Simulation Integration
**What:** The TUI App launches `run_simulation()` as a Textual Worker via `self.run_worker()`. The Worker runs on the same asyncio event loop. StateStore is the shared bridge -- simulation writes per-agent state, TUI reads snapshots.
**When to use:** Always -- this is the D-01 locked decision.
**Example:**
```python
# Source: Textual Workers docs (https://textual.textualize.io/guide/workers/)
from textual.app import App
from textual.worker import Worker

class AlphaSwarmApp(App):
    def on_mount(self) -> None:
        # Start simulation as background Worker
        self.run_worker(self._run_simulation(), exclusive=True, exit_on_error=False)
        # Start 200ms snapshot polling timer
        self.set_interval(1/5, self._poll_snapshot)

    async def _run_simulation(self) -> None:
        """Worker coroutine: runs simulation, writes to StateStore."""
        from alphaswarm.simulation import run_simulation
        try:
            await run_simulation(
                rumor=self.rumor,
                settings=self.settings,
                # ... all params
            )
            self.app_state.state_store.set_phase(SimulationPhase.COMPLETE)
        except Exception as e:
            self.notify(f"Simulation failed: {e}. Press q to exit.", severity="error")

    def _poll_snapshot(self) -> None:
        """Timer callback: read snapshot, diff, update changed cells."""
        snapshot = self.app_state.state_store.snapshot()
        # Compare with previous, update only changed cells
```

### Pattern 2: Snapshot Diff Rendering
**What:** TUI stores the previous `StateSnapshot`. On each 200ms tick, it reads a new snapshot, compares per-agent states, and calls `cell.refresh()` only on changed cells.
**When to use:** Every timer tick (TUI-02).
**Example:**
```python
# Source: Textual widget refresh pattern
def _poll_snapshot(self) -> None:
    new_snapshot = self.state_store.snapshot()
    if self._prev_snapshot is None:
        # First tick: update all cells
        self._update_all_cells(new_snapshot)
    else:
        # Diff: only update changed agents
        for agent_id, new_state in new_snapshot.agent_states.items():
            old_state = self._prev_snapshot.agent_states.get(agent_id)
            if old_state != new_state:
                cell = self._cells[agent_id]
                cell.agent_state = new_state  # triggers refresh
    # Update header if phase/round/elapsed changed
    if (new_snapshot.phase != self._prev_snapshot.phase or
        new_snapshot.round_num != self._prev_snapshot.round_num):
        self._header.update_status(new_snapshot)
    self._prev_snapshot = new_snapshot
```

### Pattern 3: StateStore with asyncio.Lock
**What:** StateStore uses `asyncio.Lock` to guard mutable per-agent state. Writes happen from the simulation Worker (one agent at a time, per D-02). Reads happen from the timer callback (snapshot() returns a frozen copy).
**When to use:** All StateStore mutations.
**Example:**
```python
import asyncio
from dataclasses import dataclass

@dataclass(frozen=True)
class AgentState:
    signal: SignalType | None = None
    confidence: float = 0.0

class StateStore:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._agent_states: dict[str, AgentState] = {}
        self._phase: SimulationPhase = SimulationPhase.IDLE
        self._round_num: int = 0
        self._start_time: float | None = None

    async def update_agent_state(
        self, agent_id: str, signal: SignalType, confidence: float
    ) -> None:
        async with self._lock:
            self._agent_states[agent_id] = AgentState(signal=signal, confidence=confidence)

    def snapshot(self) -> StateSnapshot:
        """Return immutable snapshot. No lock needed for read (dict copy is atomic enough
        at the granularity of 200ms polling)."""
        return StateSnapshot(
            phase=self._phase,
            round_num=self._round_num,
            agent_states=dict(self._agent_states),  # shallow copy
            elapsed_seconds=time.monotonic() - self._start_time if self._start_time else 0.0,
        )
```

### Pattern 4: Custom Theme Registration
**What:** Register a custom dark theme named "alphaswarm" with the UI-SPEC colors.
**When to use:** App initialization.
**Example:**
```python
# Source: Textual Theme docs (https://textual.textualize.io/guide/design/)
from textual.theme import Theme

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

class AlphaSwarmApp(App):
    def on_mount(self) -> None:
        self.register_theme(ALPHASWARM_THEME)
        self.theme = "alphaswarm"
```

### Pattern 5: AgentCell Color Computation
**What:** Map signal + confidence to HSL background color per UI-SPEC.
**When to use:** Every cell render/refresh.
**Example:**
```python
# Source: UI-SPEC color table
def compute_cell_color(state: AgentState | None) -> str:
    """Compute TCSS-compatible color string for an agent cell."""
    if state is None or state.signal is None:
        return "#333333"  # PENDING (D-05)
    if state.signal == SignalType.HOLD:
        return "#555555"  # HOLD fixed gray
    if state.signal == SignalType.BUY:
        h, s = 120, 60  # green hue
    elif state.signal == SignalType.SELL:
        h, s = 0, 70    # red hue
    else:
        return "#333333"  # fallback
    # Brightness formula: lightness = 20 + (confidence * 30)
    lightness = 20 + (state.confidence * 30)
    return f"hsl({h},{s}%,{lightness:.0f}%)"
```

### Anti-Patterns to Avoid
- **Running `create_app_state()` inside the Textual event loop:** `create_app_state()` calls `asyncio.get_event_loop().run_until_complete()` for Neo4j verification. This will crash with "RuntimeError: This event loop is already running" if called inside Textual's loop. Must create AppState BEFORE `App.run()`.
- **Using `recompose()` for rapid updates:** `recompose()` rebuilds the entire widget tree. For 200ms updates with 100 cells, use `cell.refresh()` (or reactive attribute) to update individual cells. Recompose is for structural changes only.
- **Bare `asyncio.create_task()` in Textual:** Use `self.run_worker()` instead. Workers are tied to the DOM lifecycle and get cleaned up automatically. Bare tasks can leak.
- **Blocking the event loop in Worker:** The simulation Worker must be fully async. Any blocking call (e.g., synchronous Neo4j, file I/O) would freeze the TUI. The existing simulation pipeline is already 100% async, so this should not be an issue.
- **Full-screen redraw on every tick:** Even with Textual's virtual DOM, redrawing 100 cells every 200ms is wasteful. The snapshot diff pattern (only refresh changed cells) is essential.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Grid layout | Manual character-position calculation | Textual `layout: grid` with `grid-size: 10 10` | Textual handles terminal resize, cell positioning, scroll automatically |
| Periodic timer | `asyncio.create_task` + `while True: await asyncio.sleep(0.2)` | `self.set_interval(1/5, callback)` | Textual timers integrate with the message queue, can be paused/resumed/stopped |
| Background task management | `asyncio.create_task` + manual cancellation | `self.run_worker(coro, exclusive=True)` | Workers handle lifecycle, cancellation, error reporting automatically |
| HSL to hex conversion | Manual math | `colorsys.hls_to_rgb` or Textual's native HSL color strings | Textual CSS accepts `hsl()` strings directly -- no conversion needed |
| Terminal resize handling | Signal handlers | Textual's built-in resize | Textual re-renders layout automatically on terminal resize |
| Theme/color variable system | Hardcoded hex values | `register_theme()` with Theme object | UI-SPEC defines 11 base colors; theme system generates shades/variants automatically |

**Key insight:** Textual provides the entire rendering pipeline -- grid layout, color theming, periodic timers, background workers, headless testing. The custom code is limited to: (1) StateStore expansion, (2) snapshot diff logic, (3) cell color computation, (4) wiring simulation into Worker.

## Common Pitfalls

### Pitfall 1: create_app_state() run_until_complete Crash
**What goes wrong:** `create_app_state()` calls `asyncio.get_event_loop().run_until_complete(driver.verify_connectivity())`. If called inside Textual's already-running event loop, this raises `RuntimeError: This event loop is already running`.
**Why it happens:** Textual owns the event loop via `App.run()`. Any `run_until_complete()` call inside that loop is illegal in standard asyncio.
**How to avoid:** Create AppState BEFORE launching the Textual app, exactly like `_handle_run()` in cli.py does. The `tui` subcommand handler must be synchronous, call `create_app_state()`, then pass the result into the Textual App constructor.
**Warning signs:** `RuntimeError` on startup, "This event loop is already running" in traceback.

### Pitfall 2: StateStore Lock Granularity
**What goes wrong:** Using a single lock for the entire StateStore blocks snapshot reads while any agent write is in progress. With 100 agents writing sequentially, this could cause the 200ms timer to miss ticks.
**Why it happens:** Overprotective locking. The simulation writes one agent at a time (atomic dict update), and the snapshot read creates a shallow copy.
**How to avoid:** The lock only needs to guard structural consistency. For the Phase 9 use case: (a) individual agent state updates are atomic dict assignments, (b) snapshot() copies the dict. The lock prevents a snapshot from reading a partially-updated batch. In practice, since writes are individual agent updates (not batch), a lock is lightweight. Alternative: skip the lock entirely and accept that a snapshot might miss the very latest write (200ms polling granularity makes this invisible).
**Warning signs:** Timer callbacks backing up, visible rendering lag.

### Pitfall 3: Simulation Writes Not Reaching StateStore
**What goes wrong:** The simulation runs correctly but the grid stays gray because per-agent writes to StateStore are not injected into the dispatch loop.
**Why it happens:** `run_simulation()` currently does not write per-agent state to StateStore. It fires `on_round_complete` callbacks at round boundaries, but D-02 requires per-agent writes as each agent resolves.
**How to avoid:** Inject `state_store.update_agent_state()` calls into the dispatch loop (inside `dispatch_wave` or at the point where each agent's decision is collected). This requires modifying `simulation.py` to accept a `state_store` parameter and write after each agent resolves.
**Warning signs:** Grid updates only at round boundaries (3 bulk updates instead of gradual cell-by-cell).

### Pitfall 4: Phase/Round State Not Updating in StateStore
**What goes wrong:** The header shows "Idle" throughout the simulation because `SimulationPhase` transitions in `run_simulation()` only update a local variable and log via structlog -- they never write to StateStore.
**Why it happens:** The existing simulation logs phase transitions but has no mechanism to push them to StateStore.
**How to avoid:** Add `state_store.set_phase(phase)` and `state_store.set_round(round_num)` calls at each phase transition point in `run_simulation()`. The StateStore already has a `phase` field in StateSnapshot.
**Warning signs:** Header stuck on "Idle" or never showing round transitions.

### Pitfall 5: Elapsed Time Drift
**What goes wrong:** Elapsed time shows inaccurate values because it's computed from a wall-clock timestamp that doesn't account for pauses or system sleep.
**Why it happens:** Using `time.time()` instead of `time.monotonic()`. Also, computing elapsed in the timer callback adds 200ms jitter.
**How to avoid:** Store `time.monotonic()` at simulation start in StateStore. Compute elapsed in `snapshot()` as `monotonic() - start_time`. Use `monotonic()` which is immune to system clock adjustments.
**Warning signs:** Elapsed time jumps or resets unexpectedly.

### Pitfall 6: Worker Error Handling
**What goes wrong:** Simulation crashes inside the Worker and the TUI exits abruptly or freezes.
**Why it happens:** Default `exit_on_error=True` in `run_worker()` causes the app to exit when a Worker raises an exception.
**How to avoid:** Use `exit_on_error=False` when creating the Worker. Handle `Worker.StateChanged` events and check for `WorkerState.ERROR`. Display error via `self.notify()` per UI-SPEC error state: "Simulation failed: {error}. Press q to exit."
**Warning signs:** App exits with traceback instead of showing error in TUI.

### Pitfall 7: PARSE_ERROR Signal Not Handled in Color Logic
**What goes wrong:** Agent with `SignalType.PARSE_ERROR` crashes the color computation function.
**Why it happens:** `PARSE_ERROR` is a valid `SignalType` variant but has no defined color mapping in the UI-SPEC.
**How to avoid:** Treat `PARSE_ERROR` same as `HOLD` (fixed `#555555` gray) or same as `PENDING` (`#333333`). The UI-SPEC defines BUY, SELL, HOLD, PENDING but not PARSE_ERROR explicitly. Safest: map to PENDING gray since the agent effectively has no valid decision.
**Warning signs:** Exception in color computation, blank/missing cells.

## Code Examples

### Complete AgentCell Widget
```python
# Source: Textual Widget docs + UI-SPEC color formula
from textual.widget import Widget

class AgentCell(Widget):
    """A single agent cell in the 10x10 grid. Color-only, no text."""

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

    def update_color(self, state: AgentState | None) -> None:
        """Update background color based on agent state."""
        color = compute_cell_color(state)
        if self.styles.background != color:
            self.styles.background = color
```

### App Compose with Grid Layout
```python
# Source: Textual Grid layout docs
from textual.app import App, ComposeResult
from textual.containers import Container

class AlphaSwarmApp(App):
    CSS = """
    #agent-grid {
        layout: grid;
        grid-size: 10 10;
        grid-gutter: 0;
        width: 30;
        height: 10;
        align: center middle;
    }
    """

    def compose(self) -> ComposeResult:
        yield HeaderBar()
        with Container(id="agent-grid"):
            for i in range(100):
                yield AgentCell(agent_id=self._agent_ids[i])
```

### TUI CLI Subcommand Handler
```python
# Source: Existing _handle_run pattern in cli.py
def _handle_tui(rumor: str) -> None:
    """Synchronous handler: create AppState BEFORE Textual event loop."""
    from alphaswarm.app import create_app_state

    settings = AppSettings()
    brackets = load_bracket_configs()
    personas = generate_personas(brackets)
    # MUST happen before App.run() -- uses run_until_complete internally
    app_state = create_app_state(settings, personas, with_ollama=True, with_neo4j=True)

    # Pass pre-initialized AppState to Textual app
    tui_app = AlphaSwarmApp(rumor=rumor, app_state=app_state)
    tui_app.run()
```

### Headless Test Pattern
```python
# Source: Textual Testing docs (https://textual.textualize.io/guide/testing/)
import pytest
from unittest.mock import AsyncMock, MagicMock

async def test_grid_renders_100_cells():
    """Verify 10x10 grid contains 100 AgentCell widgets."""
    app = AlphaSwarmApp(rumor="test", app_state=mock_app_state)
    async with app.run_test(size=(80, 30)) as pilot:
        cells = app.query("AgentCell")
        assert len(cells) == 100

async def test_header_shows_idle_on_start():
    """Header displays 'Idle' before simulation starts."""
    app = AlphaSwarmApp(rumor="test", app_state=mock_app_state)
    async with app.run_test(size=(80, 30)) as pilot:
        header = app.query_one(HeaderBar)
        assert "Idle" in header.render()
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| textual 0.x (pre-1.0 API) | textual 8.x (stable API, renamed from 0.x) | 2025 (version jump) | Major API stabilization; CSS variables, Theme system, Worker API all stable |
| `App.dark = True/False` toggle | `register_theme()` + `self.theme = "name"` | textual 1.0+ | Full theme system with 11 base colors and auto-generated variants |
| Manual async task management | `@work` decorator / `run_worker()` | textual 0.18+ | Workers tied to DOM lifecycle, automatic cleanup, exclusive mode |

**Deprecated/outdated:**
- `App.dark` property for dark mode: Still works but `register_theme()` is the modern approach
- `rich.console` for terminal UI: Textual supersedes Rich for interactive apps (Rich is still used for static output)

## Open Questions

1. **Per-agent write injection point in simulation.py**
   - What we know: D-02 requires per-agent StateStore writes. The simulation's `dispatch_wave()` returns a batch list of decisions. The per-agent resolution happens inside `dispatch_wave` via `asyncio.TaskGroup`.
   - What's unclear: Whether to inject the StateStore write inside `dispatch_wave` (modifying the batch dispatcher) or add a callback/hook pattern to `dispatch_wave` that fires after each individual agent resolves.
   - Recommendation: Add a `on_agent_complete` callback parameter to `dispatch_wave()` that fires after each agent resolves. This keeps the dispatcher generic and avoids coupling it to StateStore. The simulation passes `lambda agent_id, dec: state_store.update_agent_state(agent_id, dec.signal, dec.confidence)` as the callback.

2. **StateStore lock necessity**
   - What we know: Both the simulation Worker and the timer callback run on the same asyncio event loop. Python's GIL + asyncio's cooperative scheduling means dict operations are atomic between await points.
   - What's unclear: Whether a lock is actually needed given that individual dict writes (`self._agent_states[agent_id] = ...`) are atomic in CPython and the snapshot reads copy the dict.
   - Recommendation: Include the `asyncio.Lock` for correctness (it's cheap and prevents future surprises if the code evolves), but document that it's defensive rather than strictly necessary for the current single-loop architecture.

3. **Resetting agent states between rounds**
   - What we know: D-05 says pending cells are fixed dim gray. Between rounds, agents should reset to pending before their new decisions arrive.
   - What's unclear: Whether to reset all 100 agents to pending at round start (clean slate per round) or let old states persist until overwritten.
   - Recommendation: Reset all agent states to None (pending) at each round start. This gives the visual effect of cells going gray then lighting up again as agents resolve in the new round. The `set_phase(ROUND_N)` call should also clear agent states.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.11+ | Runtime | Needs verification at install | -- | -- |
| textual | TUI framework | Not installed (not in pyproject.toml) | 8.1.1 on PyPI | Must install: `uv add textual>=8.1.1` |
| Ollama | Simulation inference | External service | -- | TUI renders but simulation fails gracefully (UI-SPEC error state) |
| Neo4j | Graph state persistence | Docker container | -- | TUI renders but simulation fails gracefully (UI-SPEC error state) |
| pytest-asyncio | Testing | Installed | >=0.24.0 | Already in dev deps |

**Missing dependencies with no fallback:**
- `textual>=8.1.1` must be added to pyproject.toml and installed

**Missing dependencies with fallback:**
- Ollama/Neo4j: TUI handles their absence via startup error messages (per UI-SPEC error states), not crashes

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.0+ with pytest-asyncio 0.24.0+ |
| Config file | pyproject.toml `[tool.pytest.ini_options]` with `asyncio_mode = "auto"` |
| Quick run command | `pytest tests/test_tui.py -x` |
| Full suite command | `pytest tests/ -x` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| TUI-01 | 10x10 grid renders 100 AgentCell widgets with correct color coding | unit | `pytest tests/test_tui.py::test_grid_renders_100_cells -x` | Wave 0 |
| TUI-01 | BUY cells render green, SELL cells render red, pending cells render gray | unit | `pytest tests/test_tui.py::test_cell_color_mapping -x` | Wave 0 |
| TUI-02 | Snapshot timer reads StateStore and updates only changed cells | unit | `pytest tests/test_tui.py::test_snapshot_diff_updates -x` | Wave 0 |
| TUI-02 | StateStore.snapshot() returns immutable StateSnapshot with agent states | unit | `pytest tests/test_state.py::test_state_snapshot_with_agents -x` | Wave 0 |
| TUI-06 | Header displays correct SimulationPhase label and elapsed time | unit | `pytest tests/test_tui.py::test_header_status_display -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_tui.py tests/test_state.py -x`
- **Per wave merge:** `pytest tests/ -x`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_tui.py` -- covers TUI-01, TUI-02, TUI-06 (new file, does not exist)
- [ ] `tests/test_state.py` -- covers StateStore expansion (new file; existing tests are in test_app.py but StateStore tests need dedicated file)
- [ ] textual dependency: `uv add textual>=8.1.1` -- must be installed before tests can import

## Sources

### Primary (HIGH confidence)
- [Textual Workers Guide](https://textual.textualize.io/guide/workers/) -- Worker API, `run_worker()`, `@work` decorator, exclusive mode, error handling
- [Textual Grid Layout](https://textual.textualize.io/styles/grid/) -- `grid-size`, `grid-gutter`, `grid-columns` CSS properties
- [Textual Grid-Size](https://textual.textualize.io/styles/grid/grid_size/) -- `grid-size: 10 10` syntax for rows and columns
- [Textual Widget Guide](https://textual.textualize.io/guide/widgets/) -- Custom widgets, `render()`, `DEFAULT_CSS`, reactive attributes
- [Textual CSS Guide](https://textual.textualize.io/guide/CSS/) -- TCSS syntax, selectors, variables, nesting
- [Textual Testing Guide](https://textual.textualize.io/guide/testing/) -- `run_test()`, Pilot, headless mode, `await pilot.pause()`
- [Textual Themes Guide](https://textual.textualize.io/guide/design/) -- `Theme` constructor, `register_theme()`, base color variables
- [Textual Timer API](https://textual.textualize.io/api/timer/) -- Timer class, pause/resume/stop, callback signatures
- [PyPI textual](https://pypi.org/project/textual/) -- Version 8.1.1 verified as latest

### Secondary (MEDIUM confidence)
- [Textual Stopwatch Tutorial](https://github.com/Textualize/textual/blob/main/docs/examples/tutorial/stopwatch.py) -- `set_interval` usage pattern with pause/resume
- [Textual App API](https://textual.textualize.io/api/app/) -- `register_theme()`, `set_interval()`, `run_worker()` method signatures

### Tertiary (LOW confidence)
- None -- all findings verified against official Textual documentation

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- textual 8.1.1 is mandated by CLAUDE.md and confirmed on PyPI; all APIs verified against official docs
- Architecture: HIGH -- Worker + set_interval + grid layout are all documented Textual patterns; integration model is locked by D-01
- Pitfalls: HIGH -- `run_until_complete` conflict is a well-known asyncio issue; StateStore integration points verified against existing codebase

**Research date:** 2026-03-26
**Valid until:** 2026-04-26 (Textual API is stable at 8.x; 30-day window is conservative)
