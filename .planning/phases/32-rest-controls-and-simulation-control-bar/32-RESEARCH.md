# Phase 32: REST Controls and Simulation Control Bar - Research

**Researched:** 2026-04-14
**Domain:** FastAPI REST endpoints + Vue 3 control bar UI + SimulationManager wiring
**Confidence:** HIGH

## Summary

Phase 32 connects the web frontend to the simulation engine. The backend work involves (1) wiring `SimulationManager.start()` to actually call `run_simulation()` via `asyncio.create_task`, (2) adding stop/shock endpoints to the existing simulation router, (3) creating a new replay router with one real Neo4j query endpoint and two contract stubs, and (4) fixing a missing data gap where `brackets` are not currently stored on `app.state`. The frontend work involves a new `ControlBar.vue` component (persistent top strip) and a `ShockDrawer.vue` slide-down panel, both pure Vue/REST with no D3 involvement.

The entire backend infrastructure is already scaffolded: `SimulationManager` exists with lock/guard, the sub-router pattern is established, the 503 Neo4j fallback pattern is proven in `edges.py`, and `read_completed_cycles()` already exists on `GraphStateManager`. The frontend has design tokens, `provide/inject` for snapshot state, and a working Vite proxy for `/api` calls. The primary complexity is correctly wiring the `create_task` + done-callback pattern so the lock releases properly and `_is_running` stays accurate.

**Primary recommendation:** Follow the existing patterns exactly -- router-per-domain for `routes/replay.py`, Pydantic request/response models per the `simulation.py` pattern, and `inject('snapshot')` in `ControlBar.vue` for phase detection.

<user_constraints>

## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Persistent top strip, always visible regardless of simulation state. The force graph renders below it in all states.
- **D-02:** Idle state: seed textarea + Start button. Both are disabled (greyed out) while a simulation is active -- no half-disabled states.
- **D-03:** Active state: Stop button + phase label (e.g. "Round 2 / 3") + "+Inject Shock" button.
- **D-04:** A new `ControlBar.vue` component. Reads `snapshot.phase` (via existing `provide/inject` from App.vue) to determine idle vs active state. Does NOT need to read from new state -- phase already flows through the WebSocket snapshot.
- **D-05:** `SimulationManager.start(seed)` calls `asyncio.create_task(run_simulation(...))` inside the `asyncio.Lock`. Stores the task as `self._task`. A done-callback on the task releases the lock and resets `_is_running = False`. `POST /api/simulate/start` returns 202 immediately.
- **D-06:** `SimulationManager.stop()` calls `self._task.cancel()` if a task is running. A new `POST /api/simulate/stop` endpoint is added to `routes/simulation.py`. Returns 200 OK `{status: "stopped"}` if a simulation was running; 409 if nothing to stop.
- **D-07:** `run_simulation()` from `src/alphaswarm/simulation.py` is the engine entry point. `SimulationManager` receives the `AppState` (already stored at `app.state.app_state`) and passes it through to the simulation call.
- **D-08:** `POST /api/simulate/shock` stores the shock text on `SimulationManager` as `self._pending_shock: str | None`. Returns `{status: "queued", message: "Shock queued for next round"}` on success.
- **D-09:** 409 guard: raises `HTTP 409` if no simulation is currently running (same pattern as simulate/start).
- **D-10:** `SimulationManager` exposes `pending_shock` property. The simulation engine can read and consume it between rounds in a later phase. Phase 32 stores and acknowledges only.
- **D-11:** Shock drawer UI: a slide-down panel that appears below the top control bar when "+Inject Shock" is clicked. Contains a textarea + Submit + Cancel. Does not overlay the force graph node interactions. Closes on submit or cancel.
- **D-12:** `GET /api/replay/cycles` -- real Neo4j query. Returns list of completed cycle IDs with metadata (cycle_id, created_at, round_count). Queries `graph_manager` for cycles where simulation reached complete state. Returns 503 if Neo4j offline (same pattern as edges endpoint).
- **D-13:** `POST /api/replay/start/{cycle_id}` -- contract stub. Returns `{status: "ok", cycle_id: ..., round_num: 1}` (correct schema). No actual replay state machine. Phase 34 fills in the logic.
- **D-14:** `POST /api/replay/advance` -- contract stub. Returns `{status: "ok", round_num: 1}` (correct schema). No actual state progression in Phase 32.
- **D-15:** All replay endpoints live in a new `routes/replay.py`, registered in `create_app()` with `/api` prefix.

### Claude's Discretion
- Exact CSS for the top strip (height, background, padding, border)
- Slide-down animation timing for the shock drawer
- Whether `ControlBar.vue` emits events up to `App.vue` or calls the REST API directly
- Exact structlog component names for new route files
- Whether `stop` endpoint returns 200 or 204 on success

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope.

</user_constraints>

<phase_requirements>

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| BE-05 | Simulation start endpoint wired to engine | `SimulationManager.start()` refactored to `create_task(run_simulation(...))` with done-callback; existing 409 guard preserved |
| BE-06 | Simulation stop endpoint | New `POST /api/simulate/stop` in `routes/simulation.py`; calls `self._task.cancel()` |
| BE-07 | Shock injection endpoint | New `POST /api/simulate/shock` in `routes/simulation.py`; stores `_pending_shock` on SimulationManager |
| BE-08 | Replay cycles listing (real Neo4j query) | New `routes/replay.py` with `GET /api/replay/cycles`; delegates to existing `graph_manager.read_completed_cycles()` |
| BE-09 | Replay start stub | `POST /api/replay/start/{cycle_id}` contract stub in `routes/replay.py`; correct response schema for Phase 34 |
| BE-10 | Replay advance stub | `POST /api/replay/advance` contract stub in `routes/replay.py`; correct response schema for Phase 34 |
| CTL-01 | Control bar with start/stop | New `ControlBar.vue` with idle/active states; reads `snapshot.phase` via `inject`; calls REST endpoints |
| CTL-02 | Shock injection drawer | New `ShockDrawer.vue` slide-down panel; textarea + submit + cancel; calls `POST /api/simulate/shock` |

</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| FastAPI | already installed | REST endpoints + Pydantic models | Project standard (Phase 29) |
| Pydantic | already installed | Request/response model validation | Project standard (CLAUDE.md) |
| structlog | already installed | Structured logging per route file | Project standard (CLAUDE.md) |
| Vue 3 | ^3.5.0 | ControlBar + ShockDrawer components | Project standard (Phase 31) |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| neo4j async driver | already installed | `read_completed_cycles()` for replay/cycles | Replay cycles endpoint |

### No New Dependencies Required

This phase uses only libraries already in the project. No `npm install` or `uv add` needed.

## Architecture Patterns

### Backend: New Files + Modified Files

```
src/alphaswarm/web/
  app.py                    # MODIFY: add replay_router import + include_router
  simulation_manager.py     # MODIFY: wire run_simulation, add _task, stop(), shock
  routes/
    simulation.py           # MODIFY: add stop + shock endpoints
    replay.py               # NEW: replay cycles, start stub, advance stub
    edges.py                # NO CHANGE (already done in Phase 31)
```

```
frontend/src/
  App.vue                   # MODIFY: add ControlBar import + render above graph
  components/
    ControlBar.vue           # NEW: persistent top strip
    ShockDrawer.vue          # NEW: slide-down shock injection panel (child of ControlBar or App)
```

### Pattern 1: SimulationManager.start() with create_task + done-callback (D-05)

**What:** The current `start()` method is `async` and blocks until the simulation completes (it awaits inside the lock). Phase 32 changes this to fire-and-forget via `create_task`, returning immediately so the HTTP response can be sent (202 Accepted).

**When to use:** Any long-running background work triggered by a REST endpoint.

**Critical implementation detail:**
```python
# The current implementation (WRONG for Phase 32 -- blocks until simulation ends):
async def start(self, seed: str) -> None:
    if self._lock.locked():
        raise SimulationAlreadyRunningError(...)
    async with self._lock:
        self._is_running = True
        try:
            pass  # Phase 32 wires here
        finally:
            self._is_running = False

# Phase 32 target implementation:
async def start(self, seed: str) -> None:
    if self._lock.locked():
        raise SimulationAlreadyRunningError(...)
    await self._lock.acquire()
    self._is_running = True
    # create_task INSIDE the lock -- lock stays held until done-callback fires
    self._task = asyncio.create_task(self._run(seed))
    self._task.add_done_callback(self._on_task_done)

def _on_task_done(self, task: asyncio.Task) -> None:
    self._is_running = False
    self._task = None
    self._lock.release()
    # Log completion or exception
    if task.exception() is not None:
        log.error("simulation_failed", error=str(task.exception()))
    else:
        log.info("simulation_completed")
```

**Why done-callback pattern:** The `async with self._lock` pattern would require awaiting inside the lock body. With `create_task`, the lock must be manually acquired and released via callback. The done-callback is synchronous (runs on the event loop's next iteration after the task completes), so it can call `self._lock.release()` safely.

### Pattern 2: Router-per-domain (D-15, established in Phase 29)
**What:** Each domain gets its own `routes/*.py` file with `APIRouter()`.
**Registration:** `app.include_router(replay_router, prefix="/api")` in `create_app()`.
**Example:** See existing `routes/edges.py`, `routes/simulation.py`, `routes/health.py`.

### Pattern 3: Neo4j 503 Fallback (edges.py pattern, for replay/cycles)
**What:** Check `graph_manager is None`, raise `HTTPException(503)` with `{"error": "graph_unavailable"}`.
**Exact reuse:** The replay/cycles endpoint copies this pattern verbatim from `edges.py`.

### Pattern 4: ControlBar Phase Detection (D-04)
**What:** `ControlBar.vue` injects `snapshot` and computes `isActive` from `snapshot.phase`.
**Logic:** Active when `phase !== 'idle' && phase !== 'complete'`. Idle/complete shows seed textarea + Start. Active shows Stop + phase label + Inject Shock.

### Anti-Patterns to Avoid
- **Awaiting run_simulation inside the lock body:** This would make `POST /simulate/start` block until the entire 3-round simulation completes (minutes). Must use `create_task` and return immediately.
- **Forgetting to release the lock on task failure:** If the simulation task raises an exception, the done-callback MUST still release the lock. Using `task.exception()` check in the callback handles this.
- **Creating a new composable for control bar state:** The control bar reads `snapshot.phase` which already exists. No new WebSocket composable or REST polling needed.
- **Overlaying shock drawer on the force graph:** D-11 explicitly requires the drawer does NOT overlay graph node interactions. Use `position: relative` flow layout, not `position: absolute` overlay.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Completed cycles query | Custom Cypher query | `graph_manager.read_completed_cycles()` | Already exists, returns `[{cycle_id, created_at, seed_rumor}]` |
| Lock-based concurrency guard | Manual boolean flags | `asyncio.Lock` + `_is_running` flag | Already scaffolded on `SimulationManager` |
| Request/response validation | Manual dict parsing | Pydantic `BaseModel` subclasses | Project pattern from `routes/simulation.py` |
| Frontend REST calls | Axios or custom fetch wrapper | Native `fetch()` | No additional dependency needed; Vue 3 projects commonly use native fetch for simple REST |

## Common Pitfalls

### Pitfall 1: Missing `brackets` in SimulationManager
**What goes wrong:** `run_simulation()` requires `brackets: list[BracketConfig]` as a parameter. Currently, `brackets` is created in the lifespan function but NOT stored on `app.state` or passed to `SimulationManager`.
**Why it happens:** Phase 29 scaffolded `SimulationManager` with only `app_state`, and `brackets` was not needed until Phase 32 wires the actual simulation call.
**How to avoid:** Either (a) store `brackets` on `app.state.brackets` in the lifespan and pass to `SimulationManager`, or (b) pass `brackets` to `SimulationManager.__init__()` alongside `app_state`. Option (b) is cleaner -- the SimulationManager should have everything it needs to call `run_simulation()`.
**Warning signs:** `TypeError: run_simulation() missing required argument: 'brackets'` at runtime.

### Pitfall 2: Lock Not Released on Simulation Crash
**What goes wrong:** If `run_simulation()` raises an unhandled exception, the lock stays held forever and no new simulation can start.
**Why it happens:** With `create_task`, the lock is manually acquired. If the done-callback does not handle exceptions, the lock never releases.
**How to avoid:** The `_on_task_done` callback MUST call `self._lock.release()` unconditionally (in a finally-like fashion), regardless of whether `task.exception()` is set.
**Warning signs:** After a simulation crash, `POST /simulate/start` returns 409 permanently.

### Pitfall 3: Shock Endpoint 409 Logic Inverted
**What goes wrong:** D-09 says shock returns 409 if NO simulation is running. This is the opposite of the start endpoint (which returns 409 if a simulation IS running).
**Why it happens:** Easy to copy-paste the start endpoint 409 logic and forget to invert the condition.
**How to avoid:** Shock endpoint checks `if not sim_manager.is_running: raise 409`. Start endpoint checks `if sim_manager.is_running: raise 409` (via lock).
**Warning signs:** Shock succeeds when no simulation is running, fails when one is.

### Pitfall 4: `settings` vs `AppState.settings` for run_simulation
**What goes wrong:** `run_simulation()` takes `settings: AppSettings` as its second parameter. The lifespan creates a fresh `settings = AppSettings()` but `app_state` also stores `app_state.settings`. Using different settings objects could cause subtle divergence.
**Why it happens:** `create_app_state()` receives `settings` and stores it on `AppState.settings`.
**How to avoid:** Always use `self._app_state.settings` inside `SimulationManager` -- it is the same object created in the lifespan.
**Warning signs:** Configuration changes not reflected in simulation runs.

### Pitfall 5: Forgetting to set phase to COMPLETE after simulation
**What goes wrong:** After `run_simulation()` finishes, the TUI explicitly calls `state_store.set_phase(SimulationPhase.COMPLETE)`. If `SimulationManager` does not do this in the done-callback, the phase may stay on `round_3` and the control bar never returns to idle state.
**Why it happens:** The `run_simulation()` function itself does not set COMPLETE -- the caller is responsible (see TUI line 943).
**How to avoid:** In `SimulationManager._run()` or the done-callback, explicitly call `await self._app_state.state_store.set_phase(SimulationPhase.COMPLETE)` after `run_simulation()` returns successfully. Note: done-callbacks are synchronous, so if the COMPLETE set needs to be async, do it in the `_run()` wrapper coroutine instead.
**Warning signs:** After simulation finishes, control bar stays in "active" state.

### Pitfall 6: Control Bar Layout Pushes Graph Down
**What goes wrong:** Adding a fixed-height control bar at the top means the force graph `height` calculation must account for the bar height. Otherwise the graph overflows or clips.
**Why it happens:** The graph currently uses `100vh` or `window.innerHeight`.
**How to avoid:** Use CSS `flex` layout in `App.vue` with the control bar as a non-shrinking element and the graph container as `flex: 1`. Or use `calc(100vh - var(--control-bar-height))`.
**Warning signs:** Graph nodes appear behind the control bar or the page becomes scrollable.

### Pitfall 7: Concurrent Shock Injection Guard Missing
**What goes wrong:** D-09 says a second concurrent shock shows HTTP 409. But the decision also says the guard fires when no simulation is running. These are two separate checks: (1) no simulation running = 409, (2) `_pending_shock` already set = 409. Success criteria SC-2 explicitly requires the second guard.
**Why it happens:** Only implementing one of the two checks.
**How to avoid:** Two conditions: `if not is_running: 409` AND `if _pending_shock is not None: 409`.
**Warning signs:** Two shock requests both succeed when only one should.

## Code Examples

Verified patterns from the existing codebase:

### Pydantic Request/Response Models (from routes/simulation.py)
```python
# Source: src/alphaswarm/web/routes/simulation.py lines 16-27
class SimulateStartRequest(BaseModel):
    seed: str

class SimulateStartResponse(BaseModel):
    status: str
    message: str
```

### 503 Neo4j Guard (from routes/edges.py)
```python
# Source: src/alphaswarm/web/routes/edges.py lines 38-44
app_state = request.app.state.app_state
graph_manager = app_state.graph_manager
if graph_manager is None:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"error": "graph_unavailable", "message": "Neo4j is not connected"},
    )
```

### read_completed_cycles Return Shape (from graph.py)
```python
# Source: src/alphaswarm/graph.py lines 1864-1884
# Returns: [{"cycle_id": str, "created_at": datetime, "seed_rumor": str}, ...]
# Note: D-12 wants round_count too -- this must be computed or the query extended.
# The existing query does NOT return round_count. Phase 32 can hard-code 3 (all
# completed cycles have 3 rounds by definition) or add a COUNT subquery.
```

### run_simulation Call Site (from tui.py)
```python
# Source: src/alphaswarm/tui.py lines 930-940
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
# After simulation: explicitly set phase to COMPLETE
await self.app_state.state_store.set_phase(SimulationPhase.COMPLETE)
```

### Vue inject Pattern (from AgentSidebar.vue)
```typescript
// Source: frontend/src/components/AgentSidebar.vue lines 14-15
const snapshot = inject<Ref<StateSnapshot>>('snapshot')!
const latestRationales = inject<Ref<Map<string, RationaleEntry>>>('latestRationales')!
```

### App.vue provide/inject Setup (existing)
```typescript
// Source: frontend/src/App.vue lines 7-14
const { snapshot, connected, reconnectFailed, latestRationales } = useWebSocket()
provide('snapshot', snapshot)
provide('connected', connected)
provide('latestRationales', latestRationales)
```

### Existing CSS Design Tokens (from variables.css)
```css
/* Source: frontend/src/assets/variables.css -- relevant for control bar styling */
--color-bg-secondary: #1a1d27;     /* use for control bar background */
--color-border: #374151;            /* use for bottom border */
--color-accent: #3b82f6;            /* use for Start button */
--color-destructive: #ef4444;       /* use for Stop button */
--color-text-primary: #e5e7eb;      /* use for labels */
--color-text-muted: #6b7280;        /* use for disabled states */
--space-sm: 8px;                    /* control bar padding */
--space-md: 16px;                   /* control bar padding */
--font-size-body: 14px;             /* control bar text */
--font-size-label: 12px;            /* phase label */
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| SimulationManager.start() blocks until done | create_task + done-callback (Phase 32) | Now | HTTP 202 returned immediately |
| Brackets created but not stored | Store on SimulationManager (Phase 32) | Now | Required for run_simulation call |
| SimulationManager.stop() is no-op | Cancels _task (Phase 32) | Now | User can abort simulations |

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.0+ with pytest-asyncio 0.24+ |
| Config file | `pyproject.toml` [tool.pytest.ini_options] asyncio_mode = "auto" |
| Quick run command | `uv run pytest tests/test_web.py -x` |
| Full suite command | `uv run pytest tests/ -x` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| BE-05 | POST /simulate/start returns 202 and launches simulation task | unit | `uv run pytest tests/test_web.py::test_simulate_start_202 -x` | Wave 0 |
| BE-05 | SimulationManager.start() creates task with done-callback | unit | `uv run pytest tests/test_web.py::test_sim_manager_creates_task -x` | Wave 0 |
| BE-06 | POST /simulate/stop returns 200 when running, 409 when not | unit | `uv run pytest tests/test_web.py::test_simulate_stop_200_and_409 -x` | Wave 0 |
| BE-07 | POST /simulate/shock stores pending shock, 409 when not running | unit | `uv run pytest tests/test_web.py::test_simulate_shock_queued_and_409 -x` | Wave 0 |
| BE-07 | Second concurrent shock returns 409 | unit | `uv run pytest tests/test_web.py::test_simulate_shock_concurrent_409 -x` | Wave 0 |
| BE-08 | GET /replay/cycles returns 503 without Neo4j | unit | `uv run pytest tests/test_web.py::test_replay_cycles_503 -x` | Wave 0 |
| BE-09 | POST /replay/start/{cycle_id} returns correct stub schema | unit | `uv run pytest tests/test_web.py::test_replay_start_stub -x` | Wave 0 |
| BE-10 | POST /replay/advance returns correct stub schema | unit | `uv run pytest tests/test_web.py::test_replay_advance_stub -x` | Wave 0 |
| CTL-01 | ControlBar renders (manual verification) | manual | N/A | N/A |
| CTL-02 | ShockDrawer renders and submits (manual verification) | manual | N/A | N/A |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_web.py -x`
- **Per wave merge:** `uv run pytest tests/ -x`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_web.py` -- add new tests for stop, shock, replay endpoints (existing file, extend it)
- [ ] `tests/test_web.py` -- add SimulationManager task creation test
- [ ] `_make_test_app()` must register `replay_router` when it is created

## Open Questions

1. **`read_completed_cycles()` does not return `round_count`**
   - What we know: D-12 says the response includes `round_count`. The existing Cypher query returns `cycle_id`, `created_at`, `seed_rumor` but not `round_count`.
   - What's unclear: Whether to add a COUNT subquery to the Cypher or hard-code `3` (all completed cycles by definition have 3 rounds).
   - Recommendation: Hard-code `round_count: 3` in the response model. All completed cycles (those with Round 3 decisions) always have exactly 3 rounds. This avoids modifying the graph query for a constant.

2. **`ensure_schema()` before `run_simulation()`**
   - What we know: The TUI calls `graph_manager.ensure_schema()` before `run_simulation()`. The CLI does not (it assumes schema exists from prior runs).
   - What's unclear: Whether the web SimulationManager should call `ensure_schema()` before each simulation.
   - Recommendation: Call `ensure_schema()` once in the lifespan startup (not per-simulation). This is safer for the web server since it runs continuously.

3. **Direct REST calls vs event emission from ControlBar**
   - What we know: D-04 says ControlBar reads snapshot via inject. Claude's discretion includes whether it calls REST directly or emits events to App.vue.
   - Recommendation: Direct `fetch()` calls from ControlBar. The control bar is the only consumer of these endpoints, and routing through App.vue adds indirection with no benefit. The snapshot already flows via inject for state reading.

## Project Constraints (from CLAUDE.md)

- **Concurrency:** 100% async (`asyncio`). No blocking I/O on the main event loop. All new endpoints must be `async def`.
- **Strict typing:** Python 3.11+ with strict typing. All Pydantic models must have type annotations.
- **structlog:** All route files use `structlog.get_logger(component="web.{domain}")`.
- **pytest-asyncio:** Tests use `asyncio_mode = "auto"` from pyproject.toml. Async test functions are auto-detected.
- **uv:** Package manager. `uv run pytest` for test execution.
- **GSD Workflow:** All changes through GSD commands.

## Sources

### Primary (HIGH confidence)
- `src/alphaswarm/web/app.py` -- current app factory, lifespan, router registration
- `src/alphaswarm/web/simulation_manager.py` -- current SimulationManager scaffold
- `src/alphaswarm/web/routes/simulation.py` -- existing start endpoint pattern
- `src/alphaswarm/web/routes/edges.py` -- 503 Neo4j fallback pattern
- `src/alphaswarm/simulation.py` -- `run_simulation()` signature and parameters
- `src/alphaswarm/app.py` -- `AppState` dataclass fields, `create_app_state()` factory
- `src/alphaswarm/graph.py` -- `read_completed_cycles()` return shape and Cypher query
- `src/alphaswarm/tui.py` -- `run_simulation()` call site with brackets and state_store
- `frontend/src/App.vue` -- current layout, provide/inject setup
- `frontend/src/types.ts` -- `StateSnapshot.phase` union type
- `frontend/src/assets/variables.css` -- design tokens
- `frontend/vite.config.ts` -- Vite proxy for `/api` and `/ws`
- `tests/test_web.py` -- existing test patterns and helpers

### Secondary (MEDIUM confidence)
- `32-CONTEXT.md` -- user decisions D-01 through D-15

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all libraries already installed and proven in prior phases
- Architecture: HIGH -- all patterns exist in the codebase; Phase 32 follows established conventions
- Pitfalls: HIGH -- identified from direct codebase inspection (missing brackets, lock release, phase transitions)

**Research date:** 2026-04-14
**Valid until:** 2026-05-14 (stable -- internal project patterns, no external API changes)
