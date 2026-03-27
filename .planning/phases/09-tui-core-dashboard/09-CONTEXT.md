# Phase 9: TUI Core Dashboard - Context

**Gathered:** 2026-03-26
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 9 builds the Textual TUI Core Dashboard on top of the completed headless simulation engine. Delivers: a `tui` CLI subcommand that launches a Textual app with a 10×10 agent grid (color+confidence-shade coded), a header bar (status, elapsed time, round counter), and snapshot-based rendering connected live to the simulation. StateStore stub (state.py) gets its full implementation here. No sidebar, no telemetry footer, no bracket panel (Phase 10). No Miro integration (v2).

</domain>

<decisions>
## Implementation Decisions

### Integration Model
- **D-01:** Same process, TUI-owned event loop. A new `tui` CLI subcommand launches the Textual app as the main process. The simulation (`run_simulation()`) runs as a Textual Worker (background asyncio task) within the same event loop. StateStore is the shared bridge — simulation writes, TUI reads. No IPC, no separate processes. Invocation: `python -m alphaswarm tui "rumor"`.
- **D-02:** Per-agent StateStore writes. The simulation writes each agent's decision to StateStore immediately after it resolves (not at round end). TUI's 200ms snapshot timer picks up whatever settled since the last tick. Grid cells light up one-by-one as agents finish their inference — visually dynamic, showing the wave of decisions propagating across the grid.

### Agent Grid Mapping
- **D-03:** Sequential, row by row. Agents 1–10 fill row 1, agents 11–20 fill row 2, and so on. Agent ID determines grid position. No semantic grouping by bracket in Phase 9. Clean and predictable — color tells the story, not layout.

### Cell Visual Design
- **D-04:** Color + confidence as brightness. Hue encodes signal (green=bullish, red=bearish, gray=pending). Brightness encodes confidence — low confidence (0.2) renders as a dim shade, high confidence (1.0) renders as full-intensity color. No text inside cells.
- **D-05:** Pending cells = fixed dim gray. Agents with no decision yet this round always render as the same dim gray, regardless of any prior state. Clear visual distinction between "not yet decided" and "decided with low confidence."

### Header Bar
- **D-06:** Status + elapsed + round counter. Header displays: `[SimulationPhase status]  |  Round X/3  |  Elapsed: HH:MM:SS`. Explicit round counter (`Round X/3`) alongside the status label. No seed rumor text in Phase 9 — deferred to Phase 10.

### Claude's Discretion
- Textual component structure: which Widgets to use, custom CSS, app layout file organization
- asyncio.Lock implementation details for StateStore thread safety
- How the 200ms snapshot timer is implemented in Textual (`set_interval` vs reactive attribute)
- Specific color values and gradient math for confidence-as-brightness (the exact RGB/hex for dim vs bright green/red)
- How `tui` subcommand is wired into the existing argparse structure in cli.py

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing Implementation (Primary)
- `src/alphaswarm/state.py` — `StateStore` stub + `StateSnapshot` frozen dataclass. Both are marked "Full implementation in Phase 9." `StateSnapshot` needs per-agent fields added. `StateStore` needs asyncio.Lock-guarded per-agent writes and the snapshot method expanded.
- `src/alphaswarm/app.py` — `AppState` already holds `state_store: StateStore` and `governor: ResourceGovernor`. The `create_app_state()` factory initializes StateStore.
- `src/alphaswarm/cli.py` — Subcommand routing via argparse. Add `tui` subcommand here alongside existing `inject` and `run`.
- `src/alphaswarm/simulation.py` — `run_simulation()` with `on_round_complete` callback. Per-agent StateStore writes need to be injected into the agent dispatch loop. `SimulationPhase` enum drives header status.
- `src/alphaswarm/types.py` — `BracketType` enum (10 archetypes), `SimulationPhase` enum (maps to header status labels), `SignalType` enum (BUY/SELL/HOLD → green/red/gray).

### Requirements
- `.planning/REQUIREMENTS.md` — TUI-01 (10×10 grid, color coding), TUI-02 (snapshot-based rendering, 200ms timer, changed-cells-only), TUI-06 (header: status + elapsed time)
- `.planning/ROADMAP.md` — Phase 9 success criteria (4 criteria)

### Prior Phase Context
- `.planning/phases/08-dynamic-influence-topology/08-CONTEXT.md` — D-07/D-08: BracketSummary in SimulationResult (available for Phase 10 bracket panel). D-09/D-10: Miro stub is standalone and not wired into pipeline.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `StateStore` / `StateSnapshot` in `state.py` — stub explicitly designed for Phase 9 expansion. `StateSnapshot` already has `phase: SimulationPhase` and `round_num: int` fields.
- `AppState` in `app.py` — already holds `state_store` reference. All subsystems already receive AppState, so the TUI can access StateStore through it.
- `run_simulation()` in `simulation.py` — `on_round_complete` callback pattern already wired. Per-agent write hook needs to be added (not a callback — direct StateStore.update_agent() call from within dispatch loop).
- `SimulationPhase` enum in `types.py` — maps directly to header status labels (Idle, Seeding, Round 1, Round 2, Round 3, Complete).

### Established Patterns
- Frozen dataclasses for immutable result containers (`Round1Result`, `SimulationResult`, `BracketSummary`)
- `structlog` with component-scoped loggers (`logger = structlog.get_logger(component="tui")`)
- `asyncio.TaskGroup` for batch operations (not bare `create_task`)
- Session-per-method for Neo4j (not relevant to TUI, but consistent with Phase 4 patterns)

### Integration Points
- `state.py` — Expand `StateSnapshot` with per-agent state dict. Add `update_agent_state()` method to `StateStore` with asyncio.Lock guard.
- `simulation.py` — Inject `state_store.update_agent_state(agent_id, signal, confidence)` call after each agent decision resolves in the dispatch loop.
- `cli.py` — Add `tui` subcommand to argparse. Launches Textual `AlphaSwarmApp` with seed rumor, creates AppState with `with_ollama=True, with_neo4j=True`.
- New `tui.py` module — Textual `App` subclass, `AgentCell` widget, grid layout, header bar, `set_interval` snapshot renderer.

</code_context>

<specifics>
## Specific Ideas

- Cell color logic: `SignalType.BUY` → green hue at confidence brightness; `SignalType.SELL` → red hue at confidence brightness; `SignalType.HOLD` or no decision → fixed dim gray
- Confidence brightness: map `confidence: float` (0.0–1.0) to a brightness multiplier (e.g., min brightness 0.25 so even low-confidence cells are visible)
- Grid layout: 100 cells in 10 rows × 10 columns, cells indexed sequentially by agent list order (agent 0 → cell [0,0], agent 99 → cell [9,9])
- Header format: `  AlphaSwarm  |  Round 1/3  |  ●  Seeding  |  00:01:23  ` (clean label-separated layout)
- Snapshot diff: TUI stores previous snapshot; on each 200ms tick, compares new snapshot to previous and only calls `cell.refresh()` on changed cells

</specifics>

<deferred>
## Deferred Ideas

- Seed rumor text display in header — deferred to Phase 10 (rationale sidebar phase)
- Agent hover tooltip (signal + confidence + rationale preview) — not in Phase 9 scope
- Bracket row grouping in grid — sequential layout chosen for Phase 9; bracket grouping could be a Phase 10 enhancement

</deferred>

---

*Phase: 09-tui-core-dashboard*
*Context gathered: 2026-03-26*
