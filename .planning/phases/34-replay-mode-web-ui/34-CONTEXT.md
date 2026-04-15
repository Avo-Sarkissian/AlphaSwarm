# Phase 34: Replay Mode Web UI - Context

**Gathered:** 2026-04-14
**Status:** Ready for planning

<domain>
## Phase Boundary

Wire the three Phase 32 replay contract stubs (`replay_start`, `replay_advance`, and the already-live `replay_cycles`) into a real browser replay experience: cycle picker modal, round-by-round stepping in the ControlBar, and force graph re-render from stored Neo4j state. No new inference. The AgentSidebar / node-click flow requires no changes — it works identically in replay mode because it reads from `snapshot.agent_states` which ReplayStore already provides.

</domain>

<decisions>
## Implementation Decisions

### Cycle Picker UX
- **D-01:** Idle ControlBar gets a "Replay" button (alongside Start). Clicking opens a **modal overlay** listing completed cycles — cycle ID (truncated), date, seed rumor preview. Radio selection + Cancel / Start Replay buttons. Modal dismisses on selection or cancel. The modal is a new `CyclePicker.vue` component mounted in `App.vue`.
- **D-02:** The modal fetches `GET /api/replay/cycles` on open (not eagerly) to keep idle state lightweight.

### ControlBar Replay Mode Layout
- **D-03:** In replay mode, the seed textarea + Start button are **replaced** (v-if) with a compact replay strip — same single-row footprint. Layout: `[■ REPLAY]` badge | cycle ID + seed rumor truncated | Round N/3 indicator | `[▶ Next]` button | `[✕ Exit]` button.
- **D-04:** The REPLAY badge is the leftmost element of the strip and lives **inside the ControlBar** (not a floating overlay). Styled distinctly (e.g., amber/orange background, monospace text) to make replay mode unmistakable.
- **D-05:** `[▶ Next]` is disabled at Round 3/3 (no wrap-around). `[✕ Exit]` calls `POST /api/replay/stop` and returns to idle state.

### Round Stepping
- **D-06:** **Manual-only stepping** — user taps `[▶ Next]` to advance one round. No auto-advance timer. Stays pinned at Round 3/3 when complete (Next button disabled, no loop). Keeps the interaction deliberate and suited for decision inspection.

### Backend State Machine
- **D-07:** New `ReplayManager` class in `src/alphaswarm/web/replay_manager.py`. Holds `ReplayStore` instance, active `cycle_id`, current `round_num`. Mounted on `AppState` (same pattern as `SimulationManager`). Created in lifespan.
- **D-08:** `replay_start` fills in real logic: calls `graph_manager.read_full_cycle_signals(cycle_id)` to load all signals, constructs `ReplayStore`, sets round 1, updates phase to `SimulationPhase.REPLAY`, and triggers a WebSocket broadcast of the round-1 snapshot.
- **D-09:** `replay_advance` increments `round_num` on `ReplayManager` (max 3), calls `replay_store.set_round(new_round)`, and broadcasts the new snapshot through the existing `ConnectionManager.broadcast()` path.
- **D-10:** New `POST /api/replay/stop` endpoint resets `ReplayManager` to idle (clears store, resets phase). Called by `[✕ Exit]` in the frontend.
- **D-11:** The WebSocket broadcast loop reads `replay_manager.store.snapshot()` when replay is active, same tick interval as live simulation. No separate polling needed.

### Claude's Discretion
- Exact CSS styling of REPLAY badge (color palette within the amber/warning family)
- CyclePicker.vue internal layout (table vs list, truncation lengths)
- Error handling for `replay_start` when cycle_id is not found in Neo4j (return 404, frontend shows toast)
- `read_full_cycle_signals` query performance — already noted as needing profiling for 600+ nodes (from STATE.md blocker); handle gracefully with a timeout/loading state in the modal

</decisions>

<specifics>
## Specific Ideas

- Replay strip in ControlBar should feel like a "mode switch" — visually distinct enough that users can't confuse it for a live simulation at a glance. The `[■ REPLAY]` badge with amber/orange background achieves this.
- Cycle picker modal should show enough of the seed rumor to identify the cycle (e.g., first 60 chars) but not so much that it wraps.

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing replay stubs (contracts to fill in)
- `src/alphaswarm/web/routes/replay.py` — `ReplayCyclesResponse`, `ReplayStartResponse`, `ReplayAdvanceResponse` schemas; existing `replay_cycles` endpoint (fully live); stubs for `replay_start` and `replay_advance`

### Replay data layer (already built)
- `src/alphaswarm/state.py` lines ~246–300 — `ReplayStore` class: `set_round()`, `set_bracket_summaries()`, `set_rationale_entries()`, `snapshot()`
- `src/alphaswarm/graph.py` lines ~1779–1900 — `read_full_cycle_signals()` and `read_completed_cycles()` with Cypher queries

### Frontend integration points
- `frontend/src/components/ControlBar.vue` — existing single-row layout; `phaseLabel` map already has `'replay': 'Replay'` (line 44); pattern for REST calls (`startSimulation`, `stopSimulation`)
- `frontend/src/App.vue` — `selectedAgentId` + `sidebarOpen` wiring; where `CyclePicker.vue` modal should be mounted
- `frontend/src/types.ts` — `StateSnapshot` with `phase: 'replay'`; `AgentState`, `BracketSummary`, `RationaleEntry` types

### Prior phase context
- `.planning/phases/32-rest-controls-and-simulation-control-bar/32-CONTEXT.md` — D-13 (replay_start contract), D-14 (replay_advance contract)
- `.planning/phases/31-vue-spa-and-force-directed-graph/31-CONTEXT.md` — ForceGraph node-click → AgentSidebar flow (unchanged in replay)

### Web server infrastructure
- `src/alphaswarm/web/simulation_manager.py` — `SimulationManager` pattern to mirror for `ReplayManager`
- `src/alphaswarm/web/connection_manager.py` — `ConnectionManager.broadcast()` for pushing replay snapshots

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `ReplayStore` (`state.py:246`): fully built data store for replay — just needs instantiation and mounting on `AppState`; `set_round()` drives round transitions
- `read_full_cycle_signals()` (`graph.py:1782`): returns `dict[tuple[str, int], AgentState]` — exact input shape for `ReplayStore.__init__()`
- `read_completed_cycles()` (`graph.py:1845`): already used by the live `GET /api/replay/cycles` endpoint
- `ConnectionManager.broadcast()`: existing WebSocket broadcast used by live simulation — replay uses the same path with no changes to the WebSocket plumbing
- `ShockDrawer.vue` pattern: example of a Vue component managed entirely within `ControlBar.vue` via `v-if` and ref state — `CyclePicker.vue` follows the same pattern but mounts in `App.vue` as a modal
- `AgentSidebar.vue` + `ForceGraph.vue` node-click: no changes needed — reads `snapshot.agent_states` which `ReplayStore.snapshot()` already returns in the correct shape

### Established Patterns
- AppState holds singletons (SimulationManager, ConnectionManager, graph_manager) — `ReplayManager` gets mounted the same way in lifespan
- REST endpoints access `request.app.state.app_state` for singletons — `replay_start` and `replay_advance` follow this pattern
- `v-if` / `v-else` controls ControlBar content by simulation phase (already done for idle vs active states) — replay strip uses same toggle

### Integration Points
- `AppState` in `src/alphaswarm/web/app.py` — add `replay_manager: ReplayManager | None = None`
- `POST /api/replay/stop` — new endpoint in `replay.py`, called by `[✕ Exit]` button in ControlBar
- `App.vue` — add `showCyclePicker` ref and mount `<CyclePicker>` modal with `v-if`; `CyclePicker` emits `start-replay(cycleId)` which `App.vue` passes to `ControlBar` or directly calls the API
- `ControlBar.vue` — add `isReplay` computed (`snapshot.value.phase === 'replay'`); conditionally render replay strip vs seed/start strip

</code_context>

<deferred>
## Deferred Ideas

- Auto-advance playback mode (2-second interval timer) — out of scope for Phase 34; could be a future enhancement
- Replay scrubber / progress bar for jumping directly to Round N — Phase 34 does manual step only
- Sharing/exporting a replay link — out of scope

</deferred>

---

*Phase: 34-replay-mode-web-ui*
*Context gathered: 2026-04-14*
