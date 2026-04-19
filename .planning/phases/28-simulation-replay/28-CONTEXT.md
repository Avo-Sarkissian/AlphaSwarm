# Phase 28: Simulation Replay - Context

**Gathered:** 2026-04-12
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 28 adds simulation replay: the ability to re-render any completed simulation cycle from stored Neo4j state, stepping through Rounds 1–3 in the TUI without re-running agent inference. Delivered via a CLI `replay` subcommand and a TUI shortcut available post-simulation. No new inference calls, no new graph writes. Live simulation controls (shock injection, run) are disabled during replay.

</domain>

<decisions>
## Implementation Decisions

### Entry Point
- **D-01:** Two entry points — CLI `alphaswarm replay --cycle <id>` (follows `_handle_X` pattern in `cli.py`) and a TUI key binding available when `SimulationPhase.COMPLETE` (post-simulation). CLI defaults `--cycle` to most recent cycle (reuse `read_latest_cycle_id()` pattern from `report` subcommand).
- **D-02:** TUI key binding triggers cycle selection (most recent cycle auto-selected, or a simple picker if multiple cycles exist). Available only when `SimulationPhase.COMPLETE` — same gate as `AgentCell.on_click` for interviews.

### Round Navigation
- **D-03:** Auto-advance by default — rounds step forward automatically with a configurable delay (default: 3s per round). A key binding (e.g., `P`) toggles between auto-play and manual step mode.
- **D-04:** In manual mode, `→` or `Space` advances to the next round. Navigation is forward-only (no reverse) for Phase 28.
- **D-05:** Replay ends after Round 3 is displayed. TUI returns to `SimulationPhase.COMPLETE` idle state (or stays on Round 3 view until user dismisses). No looping.

### Data Loading
- **D-06:** Hybrid loading strategy — one upfront query loads agent decision signals (signal, confidence, sentiment) for all 3 rounds. This is the grid data needed to color cells across all rounds without per-round round-trips.
- **D-07:** Richer per-round data (bracket narratives, rationale sidebar entries, rationale episodes) loads on-demand as each round is displayed. Uses existing `read_bracket_narratives(cycle_id)` and related methods, filtered per round.
- **D-08:** New `read_full_cycle_signals(cycle_id)` method on `GraphStateManager` handles the upfront load. Returns a dict keyed by `(agent_id, round)` → `{signal, confidence, sentiment}`. This is the query that needs COLLECT performance profiling (STATE.md blocker — benchmark against 600+ nodes before shipping).

### TUI Replay Mode
- **D-09:** Reuse `AlphaSwarmApp` in replay mode — same app, same grid, bracket panel, and rationale sidebar widgets. Replay feeds the existing `StateStore`-driven rendering by writing replayed snapshots into a `ReplayStore` (already established as separate from `StateStore` per prior decisions).
- **D-10:** Header badge displays `REPLAY — Cycle {short_id}` to visually distinguish from live simulation. `SimulationPhase` gains a `REPLAY` state (or replay is signaled via a flag on `AppState`) so controls can gate on it.
- **D-11:** Shock injection controls (key bindings, `ShockInputScreen`) are disabled during replay — no `open_shock_window()` calls when in replay mode. Run/seed controls similarly suppressed.
- **D-12:** `ReplayStore` is the data source during replay — `StateStore` is not written to. On replay exit, `StateStore` snapshot from the completed simulation is restored.

### Claude's Discretion
- Exact key binding for TUI replay trigger and manual-step control
- Whether `SimulationPhase.REPLAY` is a new enum value or a flag on `AppState`
- Cycle picker UX if multiple cycles exist (simple list or inline prompt)
- `read_full_cycle_signals()` Cypher query design (COLLECT structure, index usage)
- How replay exit restores the prior TUI state cleanly
- Auto-advance timer implementation (Textual `set_interval` or `asyncio.sleep` in a Worker)

</decisions>

<specifics>
## Specific Ideas

- The header badge `REPLAY — Cycle {id}` is explicitly called out in the success criteria — make it prominent.
- Auto-advance default of 3s per round gives enough time to read the bracket panel and rationale sidebar before the next round loads.
- The `read_full_cycle_signals()` query is the performance-critical path — profile with `EXPLAIN`/`PROFILE` Cypher against a real populated graph before finalizing.

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements
- `.planning/REQUIREMENTS.md` — REPLAY-01 (simulation replay from stored Neo4j state, re-render without re-inference)
- `.planning/ROADMAP.md` — Phase 28 success criteria (CLI subcommand, TUI rendering, Cypher perf under 2s, visual distinction)

### CLI Layer
- `src/alphaswarm/cli.py` — `main()` (line 771, argparse subcommand pattern), `_handle_report()` (line 664, async handler pattern to follow), `_handle_tui()` (line 554, TUI launch pattern), `read_latest_cycle_id` usage in `_handle_report` for cycle defaulting

### TUI Layer
- `src/alphaswarm/tui.py` — `AlphaSwarmApp` (entry point for replay mode), `RumorInputScreen` / `InterviewScreen` (overlay patterns), `AgentCell` (SimulationPhase gate pattern for key bindings), `StateStore` integration points
- `src/alphaswarm/app.py` — `AppState` dataclass, `SimulationPhase` enum (where `REPLAY` state or flag lives)
- `src/alphaswarm/state.py` — `StateStore`, `StateSnapshot` (understand what replay must feed into)

### Graph Layer
- `src/alphaswarm/graph.py` — `read_agent_interview_context()` (line 988, per-agent read pattern), `read_consensus_summary()` (line 1090), `read_bracket_narratives()` (line 1169), `read_latest_cycle_id()` (line 1460), existing COLLECT-based read methods for perf comparison
- `src/alphaswarm/graph.py` — cycle_id indexes (lines 64–68, relevant for query planning on `read_full_cycle_signals`)

### Prior Phase Decisions
- `.planning/phases/14-agent-interviews/14-CONTEXT.md` — D-12/D-13 (worker model lifecycle, `push_screen` overlay pattern, `cycle_id` retrieval from `AppState`)
- `.planning/phases/15-post-simulation-report/15-CONTEXT.md` — D-04 (CLI-only trigger pattern), D-12 (model lifecycle serialization — replay uses no model, so no conflict)
- `.planning/phases/09-tui-core-dashboard/09-CONTEXT.md` — TUI aesthetic, snapshot-based rendering, `StateStore` pattern

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `read_latest_cycle_id()` (graph.py:1460) — defaults `--cycle` to most recent; already used in `report` subcommand
- `read_bracket_narratives(cycle_id)` and all other `read_*` methods (graph.py:1090–1525) — richer per-round data loading reuses these directly
- `_handle_report()` (cli.py:664) — direct structural template for `_handle_replay()` async handler
- `AgentCell` click gate (`SimulationPhase.COMPLETE` check) — same pattern for TUI replay key binding gate
- `ShockInputScreen` edge latch pattern — reference for disabling shock controls in replay mode

### Established Patterns
- CLI subcommands: `argparse` `add_subparsers`, `_handle_X()` async handler, `asyncio.run()` dispatch (cli.py:771–850)
- TUI state injection: `StateStore` snapshot written by simulation, read by 200ms tick — replay feeds equivalent snapshots from `ReplayStore`
- `structlog` component-scoped logger: `logger = structlog.get_logger(component="replay")`

### Integration Points
- `cli.py main()` — add `replay_parser = subparsers.add_parser("replay", ...)` and dispatch to `_handle_replay()`
- `app.py AppState` — add replay flag or `SimulationPhase.REPLAY` state; gate shock/run controls on it
- `graph.py GraphStateManager` — add `read_full_cycle_signals(cycle_id)` method (new upfront query)
- `tui.py AlphaSwarmApp` — add replay key binding (gated on `COMPLETE`), replay mode header update, control suppression

</code_context>

<deferred>
## Deferred Ideas

- Reverse round navigation (step backward through rounds) — forward-only in Phase 28, can add later
- Replay loop / auto-repeat — out of scope
- Exporting a replay as a video or GIF — future idea
- Side-by-side cycle comparison (two replays at once) — future phase
- Replay speed control (configurable delay via `--speed` flag or TUI slider) — the 3s default covers Phase 28; fine-grained control deferred

</deferred>

---

*Phase: 28-simulation-replay*
*Context gathered: 2026-04-12*
