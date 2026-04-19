# Phase 32: REST Controls and Simulation Control Bar - Context

**Gathered:** 2026-04-14
**Status:** Ready for planning

<domain>
## Phase Boundary

Add REST endpoints for simulation start, stop, shock injection, and replay cycle listing plus contract stubs for replay start/advance. Wire a browser-side control bar (persistent top strip) and shock injection drawer into the existing Vue SPA.

Phase 33 (Monitoring Panels), Phase 34 (Replay Mode Web UI), Phase 35 (Agent Interviews), and Phase 36 (Report Viewer) are out of scope.

</domain>

<decisions>
## Implementation Decisions

### Control Bar Layout
- **D-01:** Persistent top strip, always visible regardless of simulation state. The force graph renders below it in all states.
- **D-02:** Idle state: seed textarea + Start button. Both are disabled (greyed out) while a simulation is active — no half-disabled states.
- **D-03:** Active state: Stop button + phase label (e.g. "Round 2 / 3") + "+Inject Shock" button.
- **D-04:** A new `ControlBar.vue` component. Reads `snapshot.phase` (via existing `provide/inject` from App.vue) to determine idle vs active state. Does NOT need to read from new state — phase already flows through the WebSocket snapshot.

### Simulation Wiring (SimulationManager)
- **D-05:** `SimulationManager.start(seed)` calls `asyncio.create_task(run_simulation(...))` inside the `asyncio.Lock`. Stores the task as `self._task`. A done-callback on the task releases the lock and resets `_is_running = False`. `POST /api/simulate/start` returns 202 immediately.
- **D-06:** `SimulationManager.stop()` calls `self._task.cancel()` if a task is running. A new `POST /api/simulate/stop` endpoint is added to `routes/simulation.py`. Returns 200 OK `{status: "stopped"}` if a simulation was running; 409 if nothing to stop.
- **D-07:** `run_simulation()` from `src/alphaswarm/simulation.py` is the engine entry point. `SimulationManager` receives the `AppState` (already stored at `app.state.app_state`) and passes it through to the simulation call.

### Shock Injection
- **D-08:** `POST /api/simulate/shock` stores the shock text on `SimulationManager` as `self._pending_shock: str | None`. Returns `{status: "queued", message: "Shock queued for next round"}` on success.
- **D-09:** 409 guard: raises `HTTP 409` if no simulation is currently running (same pattern as simulate/start).
- **D-10:** `SimulationManager` exposes `pending_shock` property. The simulation engine can read and consume it between rounds in a later phase. Phase 32 stores and acknowledges only.
- **D-11:** Shock drawer UI: a slide-down panel that appears below the top control bar when "+Inject Shock" is clicked. Contains a textarea + Submit + Cancel. Does not overlay the force graph node interactions. Closes on submit or cancel.

### Replay Endpoints
- **D-12:** `GET /api/replay/cycles` — real Neo4j query. Returns list of completed cycle IDs with metadata (cycle_id, created_at, round_count). Queries `graph_manager` for cycles where simulation reached complete state. Returns 503 if Neo4j offline (same pattern as edges endpoint).
- **D-13:** `POST /api/replay/start/{cycle_id}` — contract stub. Returns `{status: "ok", cycle_id: ..., round_num: 1}` (correct schema). No actual replay state machine. Phase 34 fills in the logic.
- **D-14:** `POST /api/replay/advance` — contract stub. Returns `{status: "ok", round_num: 1}` (correct schema). No actual state progression in Phase 32.
- **D-15:** All replay endpoints live in a new `routes/replay.py`, registered in `create_app()` with `/api` prefix.

### Claude's Discretion
- Exact CSS for the top strip (height, background, padding, border)
- Slide-down animation timing for the shock drawer
- Whether `ControlBar.vue` emits events up to `App.vue` or calls the REST API directly
- Exact structlog component names for new route files
- Whether `stop` endpoint returns 200 or 204 on success

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase requirements
- `.planning/ROADMAP.md` §"Phase 32: REST Controls and Simulation Control Bar" — goal, success criteria SC-1 through SC-5

### Existing backend infrastructure (read before implementing)
- `src/alphaswarm/web/app.py` — `create_app()`: Phase 32 adds `replay_router` and `simulate_stop` wiring here
- `src/alphaswarm/web/simulation_manager.py` — stub methods `start()`, `stop()` are Phase 32 targets; all new simulation wiring goes here
- `src/alphaswarm/web/routes/simulation.py` — existing `POST /api/simulate/start` pattern; `stop` endpoint added to this file
- `src/alphaswarm/web/routes/edges.py` — pattern for Neo4j query endpoint with 503 fallback (replay/cycles follows this pattern)
- `src/alphaswarm/simulation.py` — `run_simulation()` entry point; `SimulationManager.start()` calls this

### Existing frontend infrastructure (read before implementing)
- `frontend/src/App.vue` — provides `snapshot`, `connected`, `selectedAgentId` via inject; `ControlBar.vue` added here
- `frontend/src/types.ts` — `StateSnapshot.phase` type; control bar reads this to toggle idle/active state
- `frontend/src/composables/useWebSocket.ts` — WebSocket snapshot already consumed; control bar doesn't need a new composable

### Neo4j query reference (for replay/cycles)
- `src/alphaswarm/graph.py` (or `graph_manager.py`) — existing query patterns; `read_latest_cycle_id()` and `read_influence_edges()` as reference for new `read_completed_cycles()` query

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `SimulationManager._lock` + `is_running` property — already scaffolded; Phase 32 wires `run_simulation()` call and `_task` reference inside the existing lock body
- `routes/edges.py` — 503 fallback pattern for Neo4j unavailable; replay/cycles copies this exactly
- `routes/simulation.py` — `SimulateStartRequest/Response` Pydantic model pattern; shock and stop endpoints follow the same shape
- `App.vue provide/inject` — `snapshot` already provided to all children; `ControlBar.vue` injects it to read `snapshot.phase`
- `StateSnapshot.phase` in `frontend/src/types.ts` — `'idle' | 'seeding' | 'round_1' | 'round_2' | 'round_3' | 'complete' | 'replay'` — control bar active detection: `phase !== 'idle' && phase !== 'complete'`

### Established Patterns
- **Router-per-domain:** New `routes/replay.py` with `APIRouter()`, registered via `app.include_router(replay_router, prefix="/api")` in `create_app()`
- **Lifespan owns stateful objects:** `SimulationManager` already on `app.state.sim_manager`; all new shock/stop methods go through it
- **structlog component naming:** `structlog.get_logger(component="web.replay")`, `component="web.simulation"` for stop endpoint
- **D3 + Vue pattern:** Control bar is pure Vue/REST — no D3 involvement

### Integration Points
- `web/app.py` `create_app()` — add `replay_router` import and `app.include_router(replay_router, prefix="/api")`
- `frontend/src/App.vue` — add `<ControlBar />` import and render above the idle/graph split
- `src/alphaswarm/simulation.py` `run_simulation()` signature — `SimulationManager.start()` must pass the correct `AppState` fields as kwargs

</code_context>

<specifics>
## Specific Ideas

- Control bar top strip: always visible, force graph renders below it — matches the layout selected (persistent, not conditional)
- Shock drawer slides down under the top bar (not modal overlay) — user can still see the graph while typing shock text
- Replay start/advance are stubs with correct schema in Phase 32 — Phase 34 fills in the real state machine

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 32-rest-controls-and-simulation-control-bar*
*Context gathered: 2026-04-14*
