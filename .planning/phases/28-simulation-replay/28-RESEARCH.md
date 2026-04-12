# Phase 28: Simulation Replay - Research

**Researched:** 2026-04-12
**Domain:** TUI replay mode, Neo4j Cypher read optimization, Textual widget extension
**Confidence:** HIGH

## Summary

Phase 28 adds simulation replay -- the ability to re-render any completed simulation cycle from stored Neo4j state, stepping through Rounds 1-3 in the TUI without re-running agent inference. The technical challenge is threefold: (1) designing a performant upfront Cypher query (`read_full_cycle_signals`) that loads all 3 rounds of agent decisions in a single aggregated read, (2) implementing a `ReplayStore` that feeds the existing `StateSnapshot`-driven rendering pipeline without touching `StateStore`, and (3) extending `AlphaSwarmApp` with replay-mode key bindings, header/footer switching, and a Textual `Timer`-based auto-advance mechanism.

The codebase is mature and highly structured. All integration points are well-documented in CONTEXT.md. The primary risk is the Cypher query performance on cycles with 600+ nodes (100 agents x 3 rounds x 2+ node types) -- this requires PROFILE/EXPLAIN verification against a populated graph. The existing composite index `(d.cycle_id, d.round)` on Decision nodes directly supports the upfront query, making the performance target of <2s achievable.

**Primary recommendation:** Implement in three layers -- (1) graph read methods + `ReplayStore`, (2) CLI subcommand + TUI replay mode with auto-advance/manual step, (3) CyclePickerScreen overlay + integration polish.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Two entry points -- CLI `alphaswarm replay --cycle <id>` (follows `_handle_X` pattern in `cli.py`) and a TUI key binding available when `SimulationPhase.COMPLETE` (post-simulation). CLI defaults `--cycle` to most recent cycle (reuse `read_latest_cycle_id()` pattern from `report` subcommand).
- **D-02:** TUI key binding triggers cycle selection (most recent cycle auto-selected, or a simple picker if multiple cycles exist). Available only when `SimulationPhase.COMPLETE` -- same gate as `AgentCell.on_click` for interviews.
- **D-03:** Auto-advance by default -- rounds step forward automatically with a configurable delay (default: 3s per round). A key binding (e.g., `P`) toggles between auto-play and manual step mode.
- **D-04:** In manual mode, right-arrow or Space advances to the next round. Navigation is forward-only (no reverse) for Phase 28.
- **D-05:** Replay ends after Round 3 is displayed. TUI returns to `SimulationPhase.COMPLETE` idle state (or stays on Round 3 view until user dismisses). No looping.
- **D-06:** Hybrid loading strategy -- one upfront query loads agent decision signals (signal, confidence, sentiment) for all 3 rounds. This is the grid data needed to color cells across all rounds without per-round round-trips.
- **D-07:** Richer per-round data (bracket narratives, rationale sidebar entries, rationale episodes) loads on-demand as each round is displayed. Uses existing `read_bracket_narratives(cycle_id)` and related methods, filtered per round.
- **D-08:** New `read_full_cycle_signals(cycle_id)` method on `GraphStateManager` handles the upfront load. Returns a dict keyed by `(agent_id, round)` -> `{signal, confidence, sentiment}`. This is the query that needs COLLECT performance profiling (STATE.md blocker -- benchmark against 600+ nodes before shipping).
- **D-09:** Reuse `AlphaSwarmApp` in replay mode -- same app, same grid, bracket panel, and rationale sidebar widgets. Replay feeds the existing `StateStore`-driven rendering by writing replayed snapshots into a `ReplayStore` (already established as separate from `StateStore` per prior decisions).
- **D-10:** Header badge displays `REPLAY -- Cycle {short_id}` to visually distinguish from live simulation. `SimulationPhase` gains a `REPLAY` state (or replay is signaled via a flag on `AppState`) so controls can gate on it.
- **D-11:** Shock injection controls (key bindings, `ShockInputScreen`) are disabled during replay -- no `open_shock_window()` calls when in replay mode. Run/seed controls similarly suppressed.
- **D-12:** `ReplayStore` is the data source during replay -- `StateStore` is not written to. On replay exit, `StateStore` snapshot from the completed simulation is restored.

### Claude's Discretion
- Exact key binding for TUI replay trigger and manual-step control
- Whether `SimulationPhase.REPLAY` is a new enum value or a flag on `AppState`
- Cycle picker UX if multiple cycles exist (simple list or inline prompt)
- `read_full_cycle_signals()` Cypher query design (COLLECT structure, index usage)
- How replay exit restores the prior TUI state cleanly
- Auto-advance timer implementation (Textual `set_interval` or `asyncio.sleep` in a Worker)

### Deferred Ideas (OUT OF SCOPE)
- Reverse round navigation (step backward through rounds) -- forward-only in Phase 28, can add later
- Replay loop / auto-repeat -- out of scope
- Exporting a replay as a video or GIF -- future idea
- Side-by-side cycle comparison (two replays at once) -- future phase
- Replay speed control (configurable delay via `--speed` flag or TUI slider) -- the 3s default covers Phase 28; fine-grained control deferred
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| REPLAY-01 | Simulation replay from stored Neo4j state (re-render without re-inference) | Upfront `read_full_cycle_signals()` Cypher loads grid data; `ReplayStore` feeds snapshots to existing TUI pipeline; on-demand `read_bracket_narratives_for_round()` and rationale episode reads populate sidebar/panel per round; CLI `replay` subcommand + TUI `r` key binding provide dual entry points |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

| Directive | Impact on Phase 28 |
|-----------|-------------------|
| 100% async (`asyncio`), no blocking I/O | All Neo4j reads in replay must be async. `ReplayStore` snapshot reads are sync (same as `StateStore`) -- only the initial data load and per-round on-demand reads are async |
| Local First, no cloud APIs | Replay is entirely local (Neo4j reads, no inference) -- no conflict |
| Memory safety (psutil, 90% pause) | Replay uses no inference and minimal memory. No governor interaction needed |
| `uv` package manager | No new dependencies for Phase 28 |
| Python 3.11+ strict typing | All new code must have type annotations |
| `structlog` for logging | New `component="replay"` logger for replay-specific logs |
| `pydantic` for validation | `ReplayStore` data structures can use dataclasses (matching `StateStore` pattern) |
| `textual>=8.1.1` | Confirmed installed at 8.1.1. `OptionList` widget, `Timer` API, `Screen` overlay all available |
| `pytest-asyncio` for testing | asyncio_mode = "auto" configured. All async tests auto-detected |

## Standard Stack

### Core (Already Installed -- No New Dependencies)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| textual | 8.1.1 | TUI dashboard, `OptionList` for cycle picker, `Timer` for auto-advance | Already the project's TUI framework |
| neo4j | 5.28.3 | Async Cypher reads for cycle signals and per-round data | Already the project's graph driver |
| structlog | (installed) | Replay-scoped logging | Project standard |

### No New Dependencies

Phase 28 requires zero new PyPI packages. All functionality is built on top of existing `textual` widgets and `neo4j` async queries.

## Architecture Patterns

### Recommended Project Structure (Files Modified/Created)

```
src/alphaswarm/
  types.py           # ADD: SimulationPhase.REPLAY enum value
  state.py           # ADD: ReplayStore class (new, separate from StateStore)
  graph.py           # ADD: read_full_cycle_signals(), read_completed_cycles(),
                     #       read_bracket_narratives_for_round(), read_rationale_entries_for_round()
  tui.py             # MODIFY: AlphaSwarmApp replay bindings, HeaderBar replay rendering,
                     #          TelemetryFooter replay mode, _poll_snapshot replay branch
                     # ADD: CyclePickerScreen overlay class
  cli.py             # ADD: replay_parser subcommand, _handle_replay() async handler
tests/
  test_state.py      # ADD: ReplayStore unit tests
  test_graph.py      # ADD: read_full_cycle_signals mock tests
  test_tui.py        # ADD: replay mode widget tests
```

### Pattern 1: ReplayStore (Parallel Store, Not Subclass)

**What:** A new class that exposes the same `snapshot() -> StateSnapshot` interface as `StateStore`, but is read-only and populated from pre-loaded Neo4j data. Per STATE.md decision: "ReplayStore is separate from StateStore -- destructive snapshot drain and timer corruption make reuse unsafe."

**When to use:** During replay mode only. The TUI's `_poll_snapshot()` switches its data source from `StateStore` to `ReplayStore`.

**Design:**

```python
@dataclass
class ReplayStore:
    """Read-only store for replay mode. Feeds StateSnapshot to TUI pipeline."""

    _cycle_id: str
    _signals: dict[tuple[str, int], AgentState]  # (agent_id, round) -> AgentState
    _current_round: int = 0
    _bracket_summaries: tuple[BracketSummary, ...] = ()
    _rationale_entries: tuple[RationaleEntry, ...] = ()

    def set_round(self, round_num: int) -> None:
        """Advance to the given round. Rebuilds agent_states for that round."""
        self._current_round = round_num

    def set_bracket_summaries(self, summaries: tuple[BracketSummary, ...]) -> None:
        """Set bracket summaries for the current round (loaded on-demand)."""
        self._bracket_summaries = summaries

    def set_rationale_entries(self, entries: tuple[RationaleEntry, ...]) -> None:
        """Set rationale entries for the current round (loaded on-demand)."""
        self._rationale_entries = entries

    def snapshot(self) -> StateSnapshot:
        """Return snapshot for the current replay round."""
        agent_states = {
            agent_id: state
            for (agent_id, rnd), state in self._signals.items()
            if rnd == self._current_round
        }
        return StateSnapshot(
            phase=SimulationPhase.REPLAY,
            round_num=self._current_round,
            agent_count=100,
            agent_states=agent_states,
            elapsed_seconds=0.0,  # No elapsed time in replay
            governor_metrics=None,  # No governor in replay
            tps=0.0,  # No inference in replay
            rationale_entries=self._rationale_entries,
            bracket_summaries=self._bracket_summaries,
        )
```

**Key insight:** `ReplayStore.snapshot()` returns the same `StateSnapshot` type. The TUI rendering code does not need to know whether it's live or replayed. The only behavioral difference is the data source.

### Pattern 2: _poll_snapshot Branching

**What:** The existing `_poll_snapshot` timer callback (200ms) needs to check whether replay mode is active and read from `ReplayStore` instead of `StateStore`.

**Design:**

```python
def _poll_snapshot(self) -> None:
    if self._replay_store is not None:
        snapshot = self._replay_store.snapshot()
    else:
        snapshot = self.app_state.state_store.snapshot()
    # ... existing diff and render logic (unchanged) ...
```

**Why not a second timer:** A dedicated replay timer would create race conditions with the existing 200ms poll timer. Better to reuse the same timer and switch the data source.

### Pattern 3: Textual Timer for Auto-Advance

**What:** `set_interval(3.0, callback)` returns a `Timer` object. Store the reference. Call `timer.stop()` on exit, `timer.pause()`/`timer.resume()` for play/pause toggle.

**Design:**

```python
def _start_replay(self, cycle_id: str, signals: dict) -> None:
    self._replay_store = ReplayStore(cycle_id=cycle_id, signals=signals)
    self._replay_round = 1
    self._replay_auto = True
    self._replay_store.set_round(1)
    self._load_round_data(1)  # on-demand bracket/rationale load
    self._replay_timer = self.set_interval(3.0, self._advance_replay_round)

def _advance_replay_round(self) -> None:
    if self._replay_round >= 3:
        self._replay_timer.stop()
        # Show [DONE] state
        return
    self._replay_round += 1
    self._replay_store.set_round(self._replay_round)
    self._load_round_data(self._replay_round)

def action_toggle_replay_mode(self) -> None:
    if self._replay_auto:
        self._replay_timer.pause()
        self._replay_auto = False
    else:
        self._replay_timer.resume()
        self._replay_auto = True
```

**Textual Timer API (verified from docs):**
- `timer.stop()` -- permanently stops the timer
- `timer.pause()` -- pauses without destroying
- `timer.resume()` -- resumes a paused timer
- `timer.reset()` -- restarts from the beginning

### Pattern 4: CyclePickerScreen Overlay

**What:** A `Screen[str | None]` overlay using `OptionList` widget for cycle selection. Follows the established `RumorInputScreen` pattern (same CSS structure, border, centering).

**Design:** Uses `OptionList` widget (built into Textual 8.1.1). Each option shows `{date} {time} -- {short_id}` with `(latest)` suffix on the first entry. On `OptionList.OptionSelected` event, `self.dismiss(cycle_id)`. On Escape, `self.dismiss(None)`.

**Key properties of OptionList (verified from docs):**
- Constructor accepts string arguments or `Option(prompt, id=...)` instances
- `on_option_list_option_selected` handler receives `message.option_id`
- Built-in Up/Down/Enter/Home/End key bindings
- `highlighted` reactive property tracks current selection index

### Pattern 5: CLI Replay Subcommand

**What:** `alphaswarm replay --cycle <id>` follows the `_handle_report` pattern exactly.

**Design:**

```python
# In main():
replay_parser = subparsers.add_parser("replay", help="Replay a completed simulation")
replay_parser.add_argument(
    "--cycle", type=str, default=None,
    help="Cycle ID to replay (defaults to most recent)",
)

# Handler:
async def _handle_replay(cycle_id: str | None) -> None:
    settings = AppSettings()
    brackets = load_bracket_configs()
    personas = generate_personas(brackets)
    app_state = create_app_state(settings, personas, with_ollama=False, with_neo4j=True)
    # NOTE: with_ollama=False -- replay needs no inference
    assert app_state.graph_manager is not None
    try:
        if cycle_id is None:
            cycle_id = await app_state.graph_manager.read_latest_cycle_id()
            if cycle_id is None:
                print("Error: No simulation cycles found.", file=sys.stderr)
                sys.exit(1)
        # Launch TUI in replay mode
        tui_app = AlphaSwarmApp(
            rumor="",  # Not needed for replay
            app_state=app_state,
            personas=personas,
            brackets=brackets,
            settings=settings,
        )
        tui_app.replay_cycle_id = cycle_id  # Signal replay mode
        tui_app.run()
    finally:
        await app_state.graph_manager.close()
```

**Critical difference from `_handle_tui`:** `with_ollama=False`. Replay does not need Ollama at all. This means `_handle_replay` can work even without Ollama running.

### Pattern 6: Discretion Recommendation -- SimulationPhase.REPLAY

**Recommendation:** Add `REPLAY = "replay"` to the `SimulationPhase` enum. This is cleaner than a boolean flag on `AppState` because:
1. All existing phase gates (`if phase != COMPLETE`) automatically exclude REPLAY
2. `_PHASE_LABELS` map naturally extends with one entry
3. `AgentCell.on_click` already gates on `phase != COMPLETE` -- REPLAY is automatically excluded
4. UI-SPEC explicitly designs around `SimulationPhase.REPLAY`

### Anti-Patterns to Avoid

- **Writing to StateStore during replay:** StateStore has destructive queue drains (rationale queue `get_nowait`). Writing replay data to StateStore would corrupt the original simulation state. Use ReplayStore exclusively.
- **Creating a second poll timer for replay:** Two timers polling at different rates create visual stuttering and race conditions. Reuse the existing 200ms timer.
- **Loading all data upfront:** Loading bracket narratives, rationale episodes, and rationale entries for all 3 rounds upfront wastes memory and slows startup. The hybrid approach (signals upfront, richer data on-demand) is correct.
- **Blocking the event loop with Neo4j reads:** On-demand per-round data must be loaded via `run_worker()` (async Worker) -- never synchronously inside `_poll_snapshot`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Cycle selection UI | Custom key navigation + rendering | `OptionList` widget in a `Screen[str\|None]` overlay | Built-in Up/Down/Enter/Esc bindings, highlight tracking, scrolling |
| Auto-advance timer | `asyncio.sleep` in a loop | `self.set_interval(3.0, callback)` returning `Timer` | Textual's `Timer` has native `pause()`/`resume()`/`stop()` lifecycle |
| Snapshot diffing | Custom diff engine for replay | Existing `_poll_snapshot` diff logic | Already handles changed-cell detection; just switch data source |

**Key insight:** Replay adds new data sources and mode gates but reuses the entire TUI rendering pipeline unchanged.

## Common Pitfalls

### Pitfall 1: ReplayStore Snapshot Draining Rationale Entries

**What goes wrong:** `StateStore.snapshot()` has a side effect -- it drains up to 5 rationale entries from the queue per call. If `ReplayStore.snapshot()` mimics this, the 200ms poll timer would empty the rationale list in 1 second.
**Why it happens:** The drain pattern makes sense for live simulation (continuous flow of entries) but not for replay (fixed set of entries per round).
**How to avoid:** `ReplayStore.snapshot()` returns the full rationale entries tuple every time. No drain. The `RationaleSidebar.add_entry()` method is called once per round transition (when new rationale entries are loaded), not on every snapshot poll.
**Warning signs:** Rationale sidebar shows entries for 0.2-1 second then goes blank.

### Pitfall 2: Timer Not Stopped on Replay Exit

**What goes wrong:** If the 3s auto-advance timer is not stopped when the user presses Escape, it continues firing and calls `_advance_replay_round()` after `_replay_store` is set to None, causing an AttributeError.
**Why it happens:** Textual timers are persistent -- they don't stop when mode changes.
**How to avoid:** `action_exit_replay()` must explicitly call `self._replay_timer.stop()` and set `self._replay_timer = None`.
**Warning signs:** Crash or ghost round advances after exiting replay.

### Pitfall 3: _poll_snapshot Race During Replay Entry

**What goes wrong:** Between setting `SimulationPhase.REPLAY` and populating `_replay_store`, the existing `_poll_snapshot` reads from `StateStore` and sees a REPLAY phase with no replay data.
**Why it happens:** Replay entry is a multi-step process (load data, create store, switch phase).
**How to avoid:** Set `_replay_store` BEFORE changing phase. The `_poll_snapshot` check should be `if self._replay_store is not None` (not `if phase == REPLAY`), so data availability gates the switch, not the phase enum.
**Warning signs:** Flash of empty/wrong data on replay entry.

### Pitfall 4: read_bracket_narratives Hardcoded to Round 3

**What goes wrong:** The existing `read_bracket_narratives()` hardcodes `round: 3` in its Cypher. Replaying Rounds 1 and 2 would show Round 3 bracket data.
**Why it happens:** The method was written for the post-simulation report, which only cares about final state.
**How to avoid:** Create a new `read_bracket_narratives_for_round(cycle_id, round_num)` method (or add an optional `round_num` parameter). Do NOT modify the existing method signature to avoid breaking the report pipeline.
**Warning signs:** Bracket panel shows identical data across all 3 replay rounds.

### Pitfall 5: COLLECT Query Performance Without Index Hit

**What goes wrong:** The `read_full_cycle_signals()` Cypher query does a full scan instead of using the `decision_cycle_round` composite index, causing >2s query time on 600+ nodes.
**Why it happens:** Neo4j may not use the index if the query structure doesn't match the index key order or if the COLLECT aggregation forces a full scan.
**How to avoid:** Structure the query to match the index: `MATCH (d:Decision {cycle_id: $cycle_id})` first (hits the index on `cycle_id`), then `COLLECT` by round. Run `PROFILE` on the query before shipping. The existing index `(d.cycle_id, d.round)` covers this pattern.
**Warning signs:** Query time >2s in profiling. `PROFILE` output shows NodeByLabelScan instead of NodeIndexSeek.

### Pitfall 6: CLI Replay Launching TUI Without Ollama

**What goes wrong:** The CLI `replay` handler calls `create_app_state(with_ollama=False)`, but `AlphaSwarmApp.__init__` or `_run_simulation` may assert `ollama_client is not None`.
**Why it happens:** The existing TUI path always creates Ollama connections.
**How to avoid:** In replay mode, `_run_simulation` is never called (no simulation worker started). Ensure `on_mount` in replay mode skips simulation startup and directly enters replay. Gate the simulation worker launch on `replay_cycle_id is None`.
**Warning signs:** Assertion error on TUI startup when Ollama is not running.

### Pitfall 7: Rationale Entries Need Agent Name, Not Just ID

**What goes wrong:** The `RationaleSidebar` displays `entry.agent_id` but the replay rationale query from Neo4j returns Decision nodes which have only `agent_id`, not `agent_name`.
**Why it happens:** During live simulation, the rationale entries are constructed from in-memory persona data. During replay, they must be reconstructed from Neo4j.
**How to avoid:** The `read_rationale_entries_for_round()` query should JOIN Agent nodes to get `a.name` and `a.bracket`. Or, since personas are already loaded in-memory (passed to `AlphaSwarmApp`), look up names from the persona list (same pattern as `read_agent_interview_context`).
**Warning signs:** Sidebar shows internal IDs like `quants_03` instead of agent display names.

## Code Examples

### Cypher: read_full_cycle_signals (Upfront Load)

```python
# Source: Designed for existing schema. Uses composite index (d.cycle_id, d.round).
async def _read_full_cycle_signals_tx(
    tx: AsyncManagedTransaction,
    cycle_id: str,
) -> list[dict]:
    result = await tx.run(
        """
        MATCH (a:Agent)-[:MADE]->(d:Decision {cycle_id: $cycle_id})
        RETURN
            a.id AS agent_id,
            d.round AS round_num,
            d.signal AS signal,
            d.confidence AS confidence,
            d.sentiment AS sentiment
        ORDER BY d.round, a.id
        """,
        cycle_id=cycle_id,
    )
    return [dict(record) async for record in result]
```

**Why flat rows instead of COLLECT:** Flat rows avoid the overhead of COLLECT aggregation on 300 rows (100 agents x 3 rounds). Python-side dict-keying by `(agent_id, round)` is trivially fast. COLLECT would not reduce row count here -- it would just nest the data.

**Expected cardinality:** 300 rows (100 agents x 3 rounds). Each row ~5 fields. Well under Neo4j's result set limits.

**Index usage:** `Decision {cycle_id: $cycle_id}` hits the `decision_cycle_round` composite index on the `cycle_id` prefix. PROFILE should show `NodeIndexSeek`.

### Cypher: read_completed_cycles (Cycle Picker)

```python
# Source: Based on existing read_latest_cycle_id pattern.
async def _read_completed_cycles_tx(
    tx: AsyncManagedTransaction,
    limit: int = 10,
) -> list[dict]:
    """Return cycles that have Round 3 decisions (completed simulations)."""
    result = await tx.run(
        """
        MATCH (c:Cycle)
        WHERE EXISTS {
            MATCH (:Agent)-[:MADE]->(d:Decision {cycle_id: c.cycle_id, round: 3})
        }
        RETURN
            c.cycle_id AS cycle_id,
            c.created_at AS created_at,
            c.seed_rumor AS seed_rumor
        ORDER BY c.created_at DESC
        LIMIT $limit
        """,
        limit=limit,
    )
    return [dict(record) async for record in result]
```

**Completeness check:** A cycle is "complete" when it has Round 3 Decision nodes. This matches the existing convention (all report queries filter on `round: 3`).

### Cypher: read_bracket_narratives_for_round

```python
# Source: Adapted from existing read_bracket_narratives (graph.py:1188)
# Only change: parameterized round instead of hardcoded 3
async def _read_bracket_narratives_for_round_tx(
    tx: AsyncManagedTransaction,
    cycle_id: str,
    round_num: int,
) -> list[dict]:
    result = await tx.run(
        """
        MATCH (a:Agent)-[:MADE]->(d:Decision {cycle_id: $cycle_id, round: $round_num})
        RETURN
            a.bracket AS bracket,
            sum(CASE WHEN d.signal = 'BUY' THEN 1 ELSE 0 END) AS buy_count,
            sum(CASE WHEN d.signal = 'SELL' THEN 1 ELSE 0 END) AS sell_count,
            sum(CASE WHEN d.signal = 'HOLD' THEN 1 ELSE 0 END) AS hold_count,
            avg(d.confidence) AS avg_confidence,
            avg(d.sentiment) AS avg_sentiment
        ORDER BY bracket
        """,
        cycle_id=cycle_id,
        round_num=round_num,
    )
    return [dict(record) async for record in result]
```

### Cypher: read_rationale_entries_for_round

```python
# Source: Based on RationaleEpisode schema from graph.py:726-743
# Uses episode_cycle_round index on (re.cycle_id, re.round)
async def _read_rationale_entries_for_round_tx(
    tx: AsyncManagedTransaction,
    cycle_id: str,
    round_num: int,
    limit: int = 10,
) -> list[dict]:
    result = await tx.run(
        """
        MATCH (a:Agent)-[:MADE]->(d:Decision {cycle_id: $cycle_id, round: $round_num})
        MATCH (d)-[:HAS_EPISODE]->(re:RationaleEpisode)
        RETURN
            a.id AS agent_id,
            d.signal AS signal,
            re.rationale AS rationale,
            d.round AS round_num
        ORDER BY d.confidence DESC
        LIMIT $limit
        """,
        cycle_id=cycle_id,
        round_num=round_num,
        limit=limit,
    )
    return [dict(record) async for record in result]
```

**Limit rationale:** Top 10 entries per round (by confidence) keeps the sidebar readable. Live simulation pushes up to 50 entries via queue; replay should show a curated subset.

### Textual: CyclePickerScreen with OptionList

```python
# Source: Textual OptionList docs + existing RumorInputScreen pattern
from textual.screen import Screen
from textual.widgets import Static
from textual.widgets.option_list import Option, OptionList

class CyclePickerScreen(Screen[str | None]):
    """Cycle selection overlay for replay mode."""

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
    """

    def __init__(self, cycles: list[dict]) -> None:
        super().__init__()
        self._cycles = cycles

    def compose(self) -> ComposeResult:
        with Container(id="cycle-container"):
            yield Static("Select Simulation Cycle", id="cycle-title")
            options = []
            for i, c in enumerate(self._cycles):
                short_id = c["cycle_id"][:8]
                suffix = "  (latest)" if i == 0 else ""
                label = f"{c['created_at']}  --  {short_id}{suffix}"
                options.append(Option(label, id=c["cycle_id"]))
            yield OptionList(*options, id="cycle-list")
            yield Static("Up/Down to select  ·  Enter to replay  ·  Esc to cancel", id="cycle-hint")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option_id)

    def action_cancel(self) -> None:
        self.dismiss(None)
```

### Textual: HeaderBar Replay Rendering

```python
# Source: Extends existing HeaderBar._render_header (tui.py:170-182)
def _render_replay_header(
    self, cycle_id: str, round_num: int, auto_mode: bool, done: bool,
) -> None:
    short_id = cycle_id[:8]
    mode = "[DONE]" if done else ("[AUTO]" if auto_mode else "[PAUSED]")
    mode_color = "#78909C" if (done or not auto_mode) else "#66BB6A"
    self.update(
        f"  [#4FC3F7 bold]AlphaSwarm[/]  "
        f"[#78909C]|[/]  [#FFA726 bold]REPLAY[/] [#78909C]--[/] Cycle [#E0E0E0]{short_id}[/]  "
        f"[#78909C]|[/]  Round {round_num}/3  "
        f"[#78909C]|[/]  [{mode_color}]{mode}[/]  "
    )
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| COLLECT aggregation for grouped Neo4j reads | Flat rows + Python-side keying | Long-standing Neo4j best practice | Simpler queries, better index usage, faster for moderate cardinalities (<1000 rows) |
| Custom timers via `asyncio.sleep` in Workers | Textual `set_interval` with `Timer.pause()/resume()` | Textual 0.80+ | Native lifecycle management, no manual asyncio coordination needed |

**Deprecated/outdated:**
- None relevant. All project dependencies are current.

## Open Questions

1. **Rationale truncation for replay sidebar**
   - What we know: Live simulation truncates rationale to 50 chars before pushing to `StateStore` queue. Neo4j stores the full rationale text in `RationaleEpisode.rationale`.
   - What's unclear: Should replay rationale entries be truncated to 50 chars to match live behavior, or show more text since there's no real-time pressure?
   - Recommendation: Truncate to 50 chars for consistency with the live sidebar rendering. The sidebar width is 40 chars and the format includes agent_id + signal prefix, so 50 chars is already the visual limit.

2. **`created_at` datetime formatting in CyclePickerScreen**
   - What we know: `c.created_at` is stored as Neo4j `datetime()`, which the Python driver returns as a `neo4j.time.DateTime` object.
   - What's unclear: Exact formatting needed for display in the picker.
   - Recommendation: Convert to Python `datetime` via `.to_native()` and format as `%Y-%m-%d %H:%M`.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.0+ with pytest-asyncio 0.24.0+ |
| Config file | `pyproject.toml` (`[tool.pytest.ini_options]`, `asyncio_mode = "auto"`) |
| Quick run command | `uv run pytest tests/test_state.py tests/test_graph.py tests/test_tui.py -x -q` |
| Full suite command | `uv run pytest tests/ -x -q` |

### Phase Requirements to Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| REPLAY-01a | `read_full_cycle_signals()` returns correct dict structure | unit (mock) | `uv run pytest tests/test_graph.py::test_read_full_cycle_signals -x` | No -- Wave 0 |
| REPLAY-01b | `read_completed_cycles()` returns only cycles with Round 3 decisions | unit (mock) | `uv run pytest tests/test_graph.py::test_read_completed_cycles -x` | No -- Wave 0 |
| REPLAY-01c | `ReplayStore.snapshot()` returns correct `StateSnapshot` per round | unit | `uv run pytest tests/test_state.py::test_replay_store_snapshot -x` | No -- Wave 0 |
| REPLAY-01d | `ReplayStore` round advancement updates agent_states | unit | `uv run pytest tests/test_state.py::test_replay_store_round_advance -x` | No -- Wave 0 |
| REPLAY-01e | `SimulationPhase.REPLAY` enum value exists | unit | `uv run pytest tests/test_state.py::test_simulation_phase_replay -x` | No -- Wave 0 |
| REPLAY-01f | HeaderBar renders replay format | unit | `uv run pytest tests/test_tui.py::test_header_replay_format -x` | No -- Wave 0 |
| REPLAY-01g | CLI `replay` subcommand parses args | unit | `uv run pytest tests/test_cli.py::test_replay_subcommand -x` | No -- Wave 0 |
| REPLAY-01h | Cypher query perf < 2s (integration) | integration | `uv run pytest tests/test_graph_integration.py::test_full_cycle_signals_perf -x` | No -- Wave 0 |

### Sampling Rate

- **Per task commit:** `uv run pytest tests/test_state.py tests/test_graph.py tests/test_tui.py -x -q`
- **Per wave merge:** `uv run pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_state.py` -- add `ReplayStore` unit tests (snapshot, round advance, rationale/bracket setting)
- [ ] `tests/test_graph.py` -- add `read_full_cycle_signals`, `read_completed_cycles`, `read_bracket_narratives_for_round` mock tests
- [ ] `tests/test_tui.py` -- add HeaderBar replay rendering test, AgentCell click disabled during REPLAY
- [ ] `tests/test_cli.py` -- add replay subcommand argument parsing test

## Sources

### Primary (HIGH confidence)
- `src/alphaswarm/state.py` -- StateStore, StateSnapshot, BracketSummary, RationaleEntry (full read, pattern verified)
- `src/alphaswarm/graph.py` -- GraphStateManager, all read methods, schema indexes, Decision/Cycle node structure (full read of relevant sections)
- `src/alphaswarm/tui.py` -- AlphaSwarmApp, HeaderBar, AgentCell, _poll_snapshot, key bindings, overlay patterns (full read)
- `src/alphaswarm/types.py` -- SimulationPhase enum, SignalType enum (full read)
- `src/alphaswarm/app.py` -- AppState dataclass, create_app_state factory (full read)
- `src/alphaswarm/cli.py` -- _handle_report, _handle_tui, main() argparse patterns (full read of relevant sections)
- [Textual Timer API](https://textual.textualize.io/api/timer/) -- Timer.stop(), Timer.pause(), Timer.resume() methods
- [Textual OptionList Widget](https://textual.textualize.io/widgets/option_list/) -- OptionList constructor, OptionSelected event, Option class

### Secondary (MEDIUM confidence)
- [Textual Screens Guide](https://textual.textualize.io/guide/screens/) -- Screen[T] dismiss pattern, push_screen callback

### Tertiary (LOW confidence)
- None. All findings verified against codebase and official Textual docs.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- no new dependencies, all verified installed at specific versions
- Architecture: HIGH -- all patterns derived from existing codebase code, verified against actual file contents
- Pitfalls: HIGH -- derived from direct code analysis of StateStore drain behavior, Timer lifecycle, and Cypher index structure
- Cypher performance: MEDIUM -- query design is sound and indexes exist, but actual performance on 600+ nodes requires runtime PROFILE verification (documented in success criteria)

**Research date:** 2026-04-12
**Valid until:** 2026-05-12 (stable -- no dependency changes expected)
