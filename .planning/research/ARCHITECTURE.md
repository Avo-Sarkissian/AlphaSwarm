# Architecture Research: v5.0 Web UI

**Domain:** Vue 3 + FastAPI web dashboard replacing Textual TUI for local multi-agent simulation engine
**Researched:** 2026-04-12
**Confidence:** HIGH

This document maps the architecture for replacing the Textual TUI with a Vue 3 + FastAPI web dashboard. It defines integration points with the existing asyncio simulation engine, component boundaries, data flow patterns, and a dependency-aware build order.

---

## Existing Architecture Baseline

```
CLI Entry (cli.py)
    |
    v
AppState (DI container: settings, governor, state_store, ollama_client, model_manager, graph_manager)
    |
    v
SeedInjector (inject_seed) --> Orchestrator LLM --> Neo4j (Cycle + Entity nodes)
    |
    v
SimulationEngine (run_simulation) --> 3x dispatch_wave() --> Neo4j (Decision + INFLUENCED_BY)
    |                                       |
    v                                       v
StateStore (mutable) <--- per-agent writes  ResourceGovernor (TokenPool, 5-state machine)
    |
    v (200ms poll via set_interval)
TUI (Textual App, snapshot-based rendering) <-- BEING REMOVED
```

**Critical integration points from existing code:**

| Component | File | Integration Surface | Modification Required |
|-----------|------|--------------------|-----------------------|
| `StateStore` | `state.py` | `.snapshot()` returns `StateSnapshot` (frozen dataclass). TUI polls at 200ms. Has destructive drain on `rationale_queue`. | Add `asyncio.Event` notification. Keep `snapshot()` unchanged. |
| `ReplayStore` | `state.py` | `.snapshot()` is non-destructive (no queue drain). Set round, brackets, rationale entries manually. | No modification needed. Bridge via same WebSocket. |
| `run_simulation()` | `simulation.py` | Accepts `state_store: StateStore` parameter. Calls `set_phase()`, `set_round()`, `update_agent_state()`, `push_rationale()`, `set_bracket_summaries()`. | No modification needed. |
| `AppState` | `app.py` | Central DI container. `create_app_state()` factory. | No modification -- FastAPI app accesses same `AppState` instance. |
| `ResourceGovernor` | `governor.py` | `suspend()`/`resume()` for shock injection window. `_resume_event` asyncio.Event for backpressure. | No modification needed. |
| `GraphStateManager` | `graph.py` | Session-per-method async pattern. All read methods return dicts/dataclasses. | No modification -- FastAPI endpoints call existing methods directly. |
| `InterviewEngine` | `interview.py` | Stateful conversation with message history. Uses `OllamaClient.chat()` directly. | No modification -- wrap in WebSocket endpoint. |
| `create_app_state()` | `app.py` | Synchronous factory. Neo4j driver created before event loop. | Call BEFORE `uvicorn.run()` starts event loop, same as TUI pattern. |

---

## Target Architecture: v5.0 Web Dashboard

```
                    +----------------------------------+
                    |  Browser (Vue 3 SPA / Vite)      |
                    |                                  |
                    |  ForceGraph (d3-force + Canvas)  |
                    |  ControlPanel (REST actions)     |
                    |  BracketPanel, RationalePanel    |
                    |  InterviewPanel (WS conversation)|
                    |  ReplayControls                  |
                    |  TelemetryFooter                 |
                    +--------+-------+---------+-------+
                             |       |         |
                       WebSocket   REST     WebSocket
                       (state)   (actions)  (interview)
                             |       |         |
                    +--------+-------+---------+-------+
                    |  FastAPI Server (Uvicorn)         |
                    |                                   |
                    |  ws:/state     -- StateRelay      |  NEW
                    |  ws:/interview -- InterviewRelay  |  NEW
                    |  POST /sim/start                  |  NEW
                    |  POST /sim/shock                  |  NEW
                    |  POST /replay/start               |  NEW
                    |  POST /replay/advance             |  NEW
                    |  GET  /report/{cycle_id}          |  NEW
                    |  GET  /cycles                     |  NEW
                    |  Static files: Vue dist/          |
                    +--------+-------------------------+
                             |
                    +--------+---------+
                    |  AppState        |  EXISTING (no modification)
                    |  StateStore      |  EXISTING (add event notification)
                    |  ReplayStore     |  EXISTING (no modification)
                    |  run_simulation()|  EXISTING (no modification)
                    |  GraphManager    |  EXISTING (no modification)
                    |  InterviewEngine |  EXISTING (no modification)
                    |  Governor        |  EXISTING (no modification)
                    +------------------+
```

---

## Component Boundaries

### NEW Components (to build)

| Component | File | Responsibility | Communicates With |
|-----------|------|---------------|-------------------|
| `WebApp` | `src/alphaswarm/web/app.py` | FastAPI application factory. Lifespan context manager. Holds `AppState` reference. | All web components, `AppState` |
| `StateRelay` | `src/alphaswarm/web/state_relay.py` | Bridges `StateStore.snapshot()` to WebSocket broadcast. Manages connected clients. | `StateStore`, WebSocket clients |
| `InterviewRelay` | `src/alphaswarm/web/interview_relay.py` | Wraps `InterviewEngine` in a per-client WebSocket session. | `InterviewEngine`, `GraphStateManager`, `OllamaClient` |
| `SimRouter` | `src/alphaswarm/web/routes/sim.py` | REST endpoints: start simulation, inject shock. | `run_simulation()`, `GraphStateManager`, `ResourceGovernor` |
| `ReplayRouter` | `src/alphaswarm/web/routes/replay.py` | REST endpoints: start replay, advance round, list cycles. | `ReplayStore`, `GraphStateManager` |
| `ReportRouter` | `src/alphaswarm/web/routes/report.py` | REST endpoint: generate/fetch report. | `ReportEngine`, `GraphStateManager` |
| `Vue SPA` | `web/` (separate dir) | Force-directed graph, panels, controls. Vite dev server in development. | FastAPI via WebSocket + REST |

### MODIFIED Components (minimal changes)

| Component | Change | Reason |
|-----------|--------|--------|
| `StateStore` | Add `_change_event: asyncio.Event` field. Call `_change_event.set()` after every mutation. | StateRelay needs push notification instead of polling. |
| `cli.py` | Add `web` subcommand routing to `main()`. | Entry point for launching web server instead of TUI. |

### REMOVED Components

| Component | When |
|-----------|------|
| `tui.py` | After web UI is feature-complete and tested. Final phase. |
| `textual` dependency | Same time as tui.py removal. |

---

## Data Flow Patterns

### Pattern 1: StateStore to WebSocket Broadcast (THE Critical Bridge)

This is the single most important architectural decision. The existing `StateStore` is mutated by `run_simulation()` on the same asyncio event loop. The TUI polls `snapshot()` on a 200ms timer. The web UI needs push, not poll.

**Recommended approach: asyncio.Event + dedicated broadcast task**

```
Simulation Task                    StateRelay Task                   Browser
     |                                  |                               |
     | update_agent_state()             |                               |
     | --> sets _change_event           |                               |
     |                                  | awaits _change_event.wait()   |
     |                                  | _change_event.clear()         |
     |                                  | calls snapshot()              |
     |                                  | serializes to JSON            |
     |                                  | broadcasts to all clients     |-------->
     |                                  | throttle: max 5 pushes/sec    |
     |                                  |                               |
```

**Why this works:**

1. `run_simulation()` already writes to `StateStore` via `await state_store.update_agent_state()`. These are awaited calls on the main event loop. No modification needed.
2. Adding `self._change_event.set()` inside `update_agent_state()`, `set_phase()`, `set_round()`, `push_rationale()`, and `set_bracket_summaries()` is a 5-line change to `state.py`.
3. The `StateRelay` runs as an `asyncio.create_task()` launched during FastAPI lifespan. It shares the same event loop as `run_simulation()`.
4. Throttling at 5 pushes/sec (200ms interval) matches the TUI's existing 200ms polling cadence. This prevents flooding the WebSocket when 100 agents fire in rapid succession.

**Why NOT polling from FastAPI:**
- A polling loop in FastAPI wastes CPU cycles checking unchanged state.
- The existing `snapshot()` drains the rationale queue as a side effect. Polling from two consumers would lose rationale entries. With one relay task, only one consumer exists.

**Why NOT an event bus / pub-sub:**
- Overkill for single-process, single-user, localhost-only architecture. An `asyncio.Event` is the lightest possible notification primitive.

**Serialization format: JSON (not MessagePack)**
- The `StateSnapshot` contains 100 agent states (signal enum + float confidence), phase enum, round int, elapsed float, governor metrics, TPS float, rationale entries (agent_id + signal + text + round), and bracket summaries (10 brackets x 7 fields). This serializes to approximately 8-12KB JSON per snapshot.
- At 5 pushes/sec over localhost, this is ~50-60KB/sec -- negligible bandwidth.
- JSON is debuggable in browser DevTools. MessagePack adds complexity for zero practical gain at this scale.

**StateSnapshot serialization contract:**

```python
# New method on StateSnapshot or standalone serializer
def serialize_snapshot(snap: StateSnapshot) -> dict:
    return {
        "phase": snap.phase.value,
        "round": snap.round_num,
        "elapsed": snap.elapsed_seconds,
        "tps": snap.tps,
        "agents": {
            aid: {"signal": s.signal.value if s.signal else None, "confidence": s.confidence}
            for aid, s in snap.agent_states.items()
        },
        "governor": {
            "slots": snap.governor_metrics.current_slots,
            "active": snap.governor_metrics.active_count,
            "pressure": snap.governor_metrics.pressure_level,
            "memory_pct": snap.governor_metrics.memory_percent,
            "state": snap.governor_metrics.governor_state,
        } if snap.governor_metrics else None,
        "rationale": [
            {"agent_id": r.agent_id, "signal": r.signal.value, "text": r.rationale, "round": r.round_num}
            for r in snap.rationale_entries
        ],
        "brackets": [
            {
                "bracket": b.bracket,
                "name": b.display_name,
                "buy": b.buy_count, "sell": b.sell_count, "hold": b.hold_count,
                "total": b.total, "avg_conf": b.avg_confidence, "avg_sent": b.avg_sentiment,
            }
            for b in snap.bracket_summaries
        ],
    }
```

### Pattern 2: REST for Control Actions (Not WebSocket)

**Decision: Use REST POST for all control actions (start sim, inject shock, advance replay).**

Rationale:
- Control actions are request-response: client sends command, server responds with success/error.
- WebSocket is fire-and-forget -- no built-in request-response correlation. You would need to invent a message ID protocol.
- REST gives you HTTP status codes, JSON error bodies, and automatic OpenAPI documentation from FastAPI.
- The state consequences of control actions (e.g., phase changing to SEEDING after start) are already pushed via the state WebSocket stream.

| Endpoint | Method | Request Body | Response | Side Effect |
|----------|--------|-------------|----------|-------------|
| `/api/sim/start` | POST | `{"rumor": "string"}` | `{"cycle_id": "uuid", "status": "started"}` | Launches `run_simulation()` as background task |
| `/api/sim/shock` | POST | `{"shock_text": "string"}` | `{"status": "injected"}` | Governor suspend, write ShockEvent to Neo4j, governor resume |
| `/api/replay/start` | POST | `{"cycle_id": "string"}` | `{"status": "started", "rounds": [1,2,3]}` | Creates `ReplayStore`, switches StateRelay source |
| `/api/replay/advance` | POST | `{}` | `{"round": N, "status": "advanced" \| "complete"}` | Calls `ReplayStore.set_round()` |
| `/api/replay/stop` | POST | `{}` | `{"status": "stopped"}` | Clears ReplayStore, restores live mode |
| `/api/cycles` | GET | -- | `[{"cycle_id": "...", "created_at": "..."}]` | Read from Neo4j |
| `/api/report/{cycle_id}` | GET | -- | `{"content": "markdown"}` | Generate or return cached report |

### Pattern 3: Interview WebSocket (Stateful Conversation)

Agent interviews are stateful multi-turn conversations. They do NOT fit the REST pattern because:
- Each message requires the full conversation history (maintained in `InterviewEngine._messages`).
- Responses stream token-by-token from Ollama (future enhancement).
- Session state must persist across turns.

**Protocol:**

```
Browser                    FastAPI ws:/api/interview/{agent_id}
   |                                  |
   | connect                          |
   |                                  | Load InterviewContext from Neo4j
   |                                  | Create InterviewEngine
   | <--- {"type": "context",         |
   |        "agent_name": "...",      |
   |        "bracket": "...",         |
   |        "decisions": [...]}       |
   |                                  |
   | ---> {"type": "message",         |
   |        "text": "Why did you..."}|
   |                                  | engine.send(text) -> OllamaClient.chat()
   | <--- {"type": "response",        |
   |        "text": "Because I..."}  |
   |                                  |
   | ---> {"type": "message", ...}   |
   | <--- {"type": "response", ...}  |
   |                                  |
   | disconnect                       |
   |                                  | Cleanup engine
```

### Pattern 4: Simulation Lifecycle Management

**Critical constraint:** Only one simulation can run at a time. The governor and Ollama models are shared resources. Two concurrent simulations would cause resource contention and corrupt StateStore.

```python
# In web/app.py -- singleton guard
class SimulationManager:
    def __init__(self, app_state: AppState):
        self._app_state = app_state
        self._running_task: asyncio.Task | None = None
        self._current_cycle_id: str | None = None
        self._lock = asyncio.Lock()

    async def start(self, rumor: str, ...) -> str:
        async with self._lock:
            if self._running_task and not self._running_task.done():
                raise SimulationAlreadyRunning()
            self._running_task = asyncio.create_task(
                self._run(rumor, ...)
            )
        return cycle_id

    async def _run(self, rumor: str, ...):
        """Wraps run_simulation() with proper lifecycle."""
        try:
            result = await run_simulation(
                rumor=rumor,
                state_store=self._app_state.state_store,
                ...  # same parameters as TUI's _run_simulation
            )
            self._current_cycle_id = result.cycle_id
        except Exception:
            # Error state is visible via StateStore phase
            raise
```

### Pattern 5: Event Loop Sharing (THE Key Technical Decision)

**FastAPI (Uvicorn) and the simulation MUST share the same asyncio event loop.**

This is non-negotiable because:
1. `StateStore` uses `asyncio.Lock` and `asyncio.Queue` -- these are bound to the event loop that creates them.
2. `ResourceGovernor` uses `asyncio.Event` (`_resume_event`) -- same constraint.
3. `Neo4j AsyncDriver` creates connections on the running event loop.
4. Running simulation in a separate thread/process would require cross-loop synchronization, defeating the entire async architecture.

**How it works:**
- `uvicorn.run(app, ...)` starts a single event loop.
- FastAPI's lifespan context manager creates `AppState` before the first request.
- `run_simulation()` is launched as `asyncio.create_task()` on the same loop.
- WebSocket handlers, REST handlers, and the simulation all share the event loop.
- This is exactly how the Textual TUI works today: `App.run()` owns the event loop, `self.run_worker(self._run_simulation())` creates a task on it.

**Important: `create_app_state()` must be called carefully.**

The existing pattern in `cli.py` calls `create_app_state()` synchronously BEFORE `asyncio.run()` starts the loop. This works because Neo4j `AsyncGraphDatabase.driver()` creates the driver synchronously.

For FastAPI, the equivalent is:
```python
# In web/app.py
app_state: AppState | None = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global app_state
    settings = AppSettings()
    brackets = load_bracket_configs()
    personas = generate_personas(brackets)
    app_state = create_app_state(settings, personas, with_ollama=True, with_neo4j=True)
    # Start StateRelay background task
    relay_task = asyncio.create_task(state_relay.run())
    yield
    # Cleanup
    relay_task.cancel()
    if app_state.graph_manager:
        await app_state.graph_manager.close()
```

---

## Vue 3 SPA Architecture

### Project Structure

```
web/
  package.json
  vite.config.ts
  tsconfig.json
  src/
    main.ts
    App.vue
    router/
      index.ts                  # Vue Router (single dashboard route + potential future routes)
    stores/
      simulation.ts             # Pinia store: simulation state from WebSocket
      interview.ts              # Pinia store: interview session state
    composables/
      useWebSocket.ts           # Generic reconnecting WebSocket composable
      useForceGraph.ts          # D3 force simulation + Canvas rendering composable
      useSimulationApi.ts       # REST API calls (start sim, inject shock, etc.)
    components/
      ForceGraph.vue            # Hero component: 100-node force-directed graph (Canvas)
      AgentTooltip.vue          # Hover/click tooltip for agent details
      BracketPanel.vue          # Signal distribution by bracket
      RationalePanel.vue        # Live rationale feed
      ControlBar.vue            # Start sim, inject shock, replay controls
      TelemetryFooter.vue       # TPS, elapsed, governor state, memory pressure
      InterviewPanel.vue        # Slide-out panel for agent Q&A
      ReplayControls.vue        # Round picker, auto-advance, play/pause
    types/
      snapshot.ts               # TypeScript interfaces matching StateSnapshot JSON
  dist/                         # Vite build output, served by FastAPI in production
```

### Force-Directed Graph: D3-force on Canvas (Not Cytoscape)

**Decision: Use `d3-force` with HTML5 Canvas rendering, NOT Cytoscape.js.**

Rationale:
1. **100 nodes is small.** Cytoscape.js optimizes for large graphs (1000+ nodes). At 100 nodes, d3-force is equally performant and gives finer-grained control over layout and animation.
2. **Canvas, not SVG.** The graph updates at up to 5 Hz with 100 nodes + edges animating. Canvas immediate-mode rendering avoids 200+ DOM elements that SVG would create. Canvas repaints the entire frame in one pass -- perfect for animation loops.
3. **Vue 3 composable pattern.** Wrap d3-force simulation in a `useForceGraph(canvasRef, nodesRef, edgesRef)` composable. Initialize in `onMounted()`, update reactively when Pinia store changes, clean up in `onUnmounted()`.
4. **d3-force is widely documented with Vue 3.** Multiple working examples exist (DEV Community articles, CodePen demos, GitHub gists). Cytoscape.js Vue 3 integration has historical compatibility gaps.

**Graph data model:**

```typescript
interface GraphNode {
  id: string;           // agent_id: "quants_01"
  bracket: string;      // "quants"
  signal: "buy" | "sell" | "hold" | null;
  confidence: number;   // 0-1
  x?: number;           // d3-force computed
  y?: number;
  fx?: number | null;   // fixed position (for clicked/pinned nodes)
  fy?: number | null;
}

interface GraphEdge {
  source: string;       // agent_id
  target: string;       // agent_id
  weight: number;       // influence weight
  round: number;        // which round created this edge
}
```

**Layout forces:**
- `forceCenter()`: Center the graph in the canvas.
- `forceManyBody().strength(-150)`: Repulsion between nodes.
- `forceCollide(nodeRadius + 2)`: Prevent overlap.
- `forceLink(edges).distance(d => 100 / d.weight)`: Edges pull connected nodes together. Higher weight = closer.
- Bracket clustering via `forceX`/`forceY` with bracket-specific target coordinates: group nodes by bracket into soft clusters.

**Color scheme (matching TUI):**
- BUY: HSL(120, 60%, 20-50%) -- green, brightness scales with confidence
- SELL: HSL(0, 70%, 20-50%) -- red, brightness scales with confidence
- HOLD: #555555 -- gray
- Pending: #333333 -- dim gray
- Edge opacity scales with influence weight

### WebSocket State Management

```typescript
// stores/simulation.ts (Pinia)
export const useSimulationStore = defineStore('simulation', () => {
  const phase = ref<string>('idle')
  const round = ref(0)
  const elapsed = ref(0)
  const tps = ref(0)
  const agents = ref<Record<string, AgentState>>({})
  const brackets = ref<BracketSummary[]>([])
  const rationale = ref<RationaleEntry[]>([])  // rolling window, append on receive
  const governor = ref<GovernorMetrics | null>(null)

  function applySnapshot(snap: SnapshotPayload) {
    phase.value = snap.phase
    round.value = snap.round
    elapsed.value = snap.elapsed
    tps.value = snap.tps
    agents.value = snap.agents
    brackets.value = snap.brackets
    governor.value = snap.governor
    // Append rationale entries (keep last 50)
    rationale.value = [...rationale.value, ...snap.rationale].slice(-50)
  }

  return { phase, round, elapsed, tps, agents, brackets, rationale, governor, applySnapshot }
})
```

### Vite + FastAPI Development Workflow

**Development:**
- Vite dev server on `localhost:5173` with HMR.
- FastAPI on `localhost:8000`.
- Vite `vite.config.ts` proxies `/api/*` and `/ws/*` to FastAPI:
  ```typescript
  export default defineConfig({
    server: {
      proxy: {
        '/api': 'http://localhost:8000',
        '/ws': { target: 'ws://localhost:8000', ws: true },
      }
    }
  })
  ```
- Run both concurrently: `npm run dev` in `web/` + `python -m alphaswarm web --dev` (uvicorn with reload).

**Production:**
- `npm run build` outputs to `web/dist/`.
- FastAPI mounts `StaticFiles(directory="web/dist", html=True)` as catch-all.
- Single process: `python -m alphaswarm web` serves both API and SPA.

---

## Replay Mode Architecture

The existing `ReplayStore` has clean semantics for the web UI:

1. `ReplayStore.snapshot()` is non-destructive (unlike `StateStore` which drains rationale queue).
2. Round transitions are explicit via `set_round()`, `set_bracket_summaries()`, `set_rationale_entries()`.

**Web replay flow:**

```
POST /api/replay/start {cycle_id}
  --> GraphManager.read_full_cycle_signals(cycle_id) -> signals dict
  --> GraphManager.read_completed_cycles() to validate cycle_id exists
  --> Create ReplayStore(cycle_id, signals)
  --> StateRelay switches source from StateStore to ReplayStore
  --> Return {status: "started", max_round: 3}

POST /api/replay/advance
  --> ReplayStore.set_round(current + 1)
  --> GraphManager.read_bracket_narratives_for_round(cycle_id, round)
  --> GraphManager.read_rationale_entries_for_round(cycle_id, round)
  --> ReplayStore.set_bracket_summaries(...)
  --> ReplayStore.set_rationale_entries(...)
  --> StateRelay pushes updated snapshot
  --> Return {round: N, status: "advanced" | "complete"}

POST /api/replay/stop
  --> StateRelay switches back to StateStore
  --> Clear ReplayStore reference
  --> Return {status: "stopped"}
```

**StateRelay dual-source:**

```python
class StateRelay:
    def __init__(self, state_store: StateStore):
        self._live_store = state_store
        self._replay_store: ReplayStore | None = None
        self._clients: set[WebSocket] = set()

    @property
    def _active_store(self):
        return self._replay_store if self._replay_store else self._live_store

    async def run(self):
        while True:
            await self._live_store._change_event.wait()
            self._live_store._change_event.clear()
            snap = self._active_store.snapshot()
            await self._broadcast(snap)
```

For replay, since `ReplayStore` doesn't have a `_change_event`, the replay endpoints manually trigger a broadcast after each `set_round()` call by setting the `_change_event` on the live store (as a notification signal). Alternative: add a separate `_notify()` method on `StateRelay` that replay endpoints call directly.

---

## Shock Injection Architecture

The shock injection flow in the web UI follows the same pattern as the TUI:

1. User clicks "Inject Shock" button (only enabled during ROUND_1 or ROUND_2 phase).
2. Frontend sends `POST /api/sim/shock {"shock_text": "..."}`.
3. Backend:
   a. Governor `suspend()` -- pauses all inference.
   b. Write `ShockEvent` node to Neo4j via `GraphStateManager`.
   c. Governor `resume()` -- inference continues with shock context.
4. Simulation picks up shock context in next round's peer reads.
5. After simulation completes, frontend can request shock impact analysis via `GET /api/report/{cycle_id}`.

---

## Anti-Patterns to Avoid

### Anti-Pattern 1: Running Simulation in a Separate Thread
**What:** Using `threading.Thread` or `concurrent.futures` to run `run_simulation()` outside the main event loop.
**Why bad:** StateStore's `asyncio.Lock`, `asyncio.Queue`, Governor's `asyncio.Event`, and Neo4j's `AsyncDriver` are all bound to the creating event loop. Cross-thread access causes "attached to a different loop" errors.
**Instead:** `asyncio.create_task()` on the same event loop that Uvicorn runs.

### Anti-Pattern 2: Multiple Snapshot Consumers
**What:** Having both a polling loop AND an event-driven relay consuming `StateStore.snapshot()`.
**Why bad:** `snapshot()` has a destructive side effect: it drains up to 5 rationale entries from the queue per call. Two consumers would each get partial rationale streams.
**Instead:** Single consumer (StateRelay). All clients get the same broadcast.

### Anti-Pattern 3: WebSocket for Request-Response Actions
**What:** Sending control commands (start sim, inject shock) over WebSocket and inventing a correlation ID protocol.
**Why bad:** Adds complexity, loses HTTP status codes and error handling, no OpenAPI docs.
**Instead:** REST POST for all control actions. WebSocket only for server-to-client push.

### Anti-Pattern 4: SSE Instead of WebSocket
**What:** Using Server-Sent Events for the state stream.
**Why bad:** SSE is unidirectional (server to client only). The interview feature requires bidirectional WebSocket. Using SSE for state + WebSocket for interviews means two different transport protocols to maintain. WebSocket for both is simpler.
**Instead:** WebSocket for state stream and interviews. REST for control actions.

### Anti-Pattern 5: SVG for the Force Graph
**What:** Rendering 100 nodes + edges as SVG elements.
**Why bad:** At 5 Hz update rate with 100+ elements, SVG DOM manipulation creates visible frame drops. Each node update triggers layout recalculation.
**Instead:** Canvas immediate-mode rendering. One `requestAnimationFrame` loop redraws everything.

### Anti-Pattern 6: Separate Backend Process for Simulation
**What:** Running FastAPI and the simulation engine as separate processes communicating via IPC/Redis.
**Why bad:** The entire codebase is designed for single-process, single-loop async. Neo4j driver, Governor, StateStore -- none of these are designed for multi-process. Redis/IPC adds infrastructure for a single-user local tool.
**Instead:** Everything in one process, one event loop.

---

## Scalability Considerations

| Concern | Current (1 user) | At 5 users (hypothetical) |
|---------|-------------------|---------------------------|
| WebSocket broadcast | Loop over set of clients, ~12KB/msg | Still fine. 60KB/sec total. |
| State consistency | Single StateStore, single simulation | Need simulation queue. One active at a time. |
| Neo4j connections | Single driver, pool of 50 | Pool handles it. No change needed. |
| Ollama inference | 2 models max, 16 parallel baseline | Hard M1 Max constraint. Cannot scale. |
| Memory (64GB) | Simulation + FastAPI + browser | Same as TUI. Negligible overhead from FastAPI. |

This is intentionally a single-operator, local-first system. Multi-user is out of scope per PROJECT.md.

---

## File Layout Plan

```
src/alphaswarm/
  web/                          # NEW package
    __init__.py
    app.py                      # FastAPI app factory, lifespan, CORS, static mount
    state_relay.py              # StateStore -> WebSocket broadcast bridge
    interview_relay.py          # InterviewEngine -> WebSocket session bridge
    simulation_manager.py       # Singleton guard, asyncio.create_task wrapper
    serializers.py              # StateSnapshot -> JSON dict serialization
    routes/
      __init__.py
      sim.py                    # POST /api/sim/start, /api/sim/shock
      replay.py                 # POST /api/replay/start, /advance, /stop
      report.py                 # GET /api/report/{cycle_id}
      cycles.py                 # GET /api/cycles
    ws/
      __init__.py
      state.py                  # WebSocket /ws/state endpoint
      interview.py              # WebSocket /ws/interview/{agent_id} endpoint
  state.py                      # MODIFIED: add _change_event
  cli.py                        # MODIFIED: add 'web' subcommand

web/                            # NEW: Vue 3 SPA (separate from Python package)
  package.json
  vite.config.ts
  tsconfig.json
  index.html
  src/
    main.ts
    App.vue
    router/index.ts
    stores/
      simulation.ts
      interview.ts
    composables/
      useWebSocket.ts
      useForceGraph.ts
      useSimulationApi.ts
    components/
      ForceGraph.vue
      AgentTooltip.vue
      BracketPanel.vue
      RationalePanel.vue
      ControlBar.vue
      TelemetryFooter.vue
      InterviewPanel.vue
      ReplayControls.vue
    types/
      snapshot.ts
```

---

## Suggested Phase Build Order

The build order is driven by dependency chains. Each phase unlocks testing of the next.

### Phase 1: FastAPI Skeleton + StateStore Event Bridge
**Build:** FastAPI app factory, lifespan, `web` CLI subcommand, `_change_event` on StateStore.
**Why first:** Everything else depends on the server existing and state notification working.
**Test:** `uvicorn` starts, `/api/health` responds, `_change_event` fires on StateStore mutations.
**Depends on:** Nothing new.

### Phase 2: WebSocket State Stream
**Build:** `StateRelay`, `/ws/state` endpoint, `serializers.py`.
**Why second:** The force graph and all panels need state data. This is the data pipe.
**Test:** Connect WebSocket client (wscat), start simulation via existing CLI in separate terminal, observe JSON snapshots streaming.
**Depends on:** Phase 1 (FastAPI + StateStore event).

### Phase 3: Vue 3 SPA Scaffold + ForceGraph
**Build:** Vite project, Pinia store, WebSocket composable, ForceGraph component with d3-force on Canvas.
**Why third:** The hero feature. Needs WebSocket state stream (Phase 2) to display anything meaningful.
**Test:** Browser shows 100 nodes updating in real-time during simulation.
**Depends on:** Phase 2 (WebSocket state stream).

### Phase 4: REST Control Endpoints + ControlBar
**Build:** `POST /api/sim/start`, `POST /api/sim/shock`, `SimulationManager` singleton, Vue `ControlBar`.
**Why fourth:** Now the web UI can both observe AND control simulations.
**Test:** Start simulation from browser, inject shock mid-simulation, observe state changes.
**Depends on:** Phase 3 (Vue SPA exists to host controls).

### Phase 5: Panels (Bracket, Rationale, Telemetry)
**Build:** `BracketPanel.vue`, `RationalePanel.vue`, `TelemetryFooter.vue`, `AgentTooltip.vue`.
**Why fifth:** Polish the observation experience. All data is already flowing from Phase 2.
**Test:** All panels update in sync with force graph during simulation.
**Depends on:** Phase 3 (Vue SPA + Pinia store).

### Phase 6: Replay Mode
**Build:** `/api/replay/*` endpoints, `ReplayRouter`, `ReplayControls.vue`, StateRelay dual-source.
**Why sixth:** Replay needs the full panel suite (Phase 5) to be meaningful.
**Test:** List cycles, start replay, advance rounds, observe graph animating historical data.
**Depends on:** Phase 5 (panels) + Phase 2 (WebSocket).

### Phase 7: Interview WebSocket
**Build:** `InterviewRelay`, `/ws/interview/{agent_id}`, `InterviewPanel.vue`.
**Why seventh:** Isolated feature. Needs simulation to complete first (agent context from Neo4j).
**Test:** Click agent node in graph, interview panel opens, conversational Q&A works.
**Depends on:** Phase 3 (Vue SPA) + existing `InterviewEngine`.

### Phase 8: Report Generation + Kill TUI
**Build:** `/api/report/{cycle_id}`, report view/download in Vue. Remove `tui.py` and `textual` dependency.
**Why last:** Report is the least interactive feature. TUI removal is the final cleanup after all functionality is verified in web UI.
**Test:** Generate report from browser, download as markdown/HTML. Verify `textual` is gone from dependencies.
**Depends on:** All previous phases.

---

## Key Decision Log

| Decision | Rationale |
|----------|-----------|
| asyncio.Event bridge (not polling) | Zero-cost notification. One consumer avoids rationale drain race. |
| REST for control, WebSocket for state push | Request-response needs HTTP semantics. State push needs server-initiated broadcast. |
| d3-force + Canvas (not Cytoscape.js SVG) | 100 nodes is small. Canvas avoids DOM overhead at 5Hz. Better Vue 3 integration story. |
| JSON serialization (not MessagePack) | ~12KB per snapshot at 5Hz over localhost. Debuggable in DevTools. |
| Single process, shared event loop | Entire codebase depends on same-loop asyncio primitives. No cross-process communication needed. |
| Vite proxy in dev, StaticFiles in prod | Standard pattern. Zero-config for developer. Single binary deployment. |
| Pinia store as single source of truth in Vue | All components react to same store. WebSocket composable writes to store, components read from store. |
| Phase-by-phase build order | Each phase is independently testable. Data pipe (WebSocket) before consumers (Vue components). |

---

## Sources

- [FastAPI WebSocket documentation](https://fastapi.tiangolo.com/advanced/websockets/)
- [FastAPI Lifespan Events](https://fastapi.tiangolo.com/advanced/events/)
- [FastAPI Concurrency and async/await](https://fastapi.tiangolo.com/async/)
- [FastAPI Static Files](https://fastapi.tiangolo.com/tutorial/static-files/)
- [d3-force module documentation](https://d3js.org/d3-force)
- [Cytoscape.js](https://js.cytoscape.org/)
- [Vue 3 Composables documentation](https://vuejs.org/guide/reusability/composables.html)
- [Using Vue 3 Composition API with D3](https://dev.to/muratkemaldar/using-vue-3-with-d3-composition-api-3h1g)
- [Building Interactive Force-Directed Graphs with D3.js, Vue 3](https://medium.com/@jeashan999/building-interactive-force-directed-graphs-with-d3-js-vue-3-and-ruby-on-rails-193caea58e65)
- [Serve Vue from FastAPI](https://dimmaski.com/serve-vue-fastapi/)
- [FastAPI + Vue SPA integration](https://testdriven.io/blog/developing-a-single-page-app-with-fastapi-and-vuejs/)
- [Managing Multiple WebSocket Clients in FastAPI](https://hexshift.medium.com/managing-multiple-websocket-clients-in-fastapi-ce5b134568a2)
- [Building a Broadcast System with FastAPI WebSockets](https://hexshift.medium.com/building-a-broadcast-system-with-fastapi-websockets-04aaca6c20c3)
- [Advanced WebSocket Architectures in FastAPI](https://hexshift.medium.com/how-to-incorporate-advanced-websocket-architectures-in-fastapi-for-high-performance-real-time-b48ac992f401)
- [Implementing Background Tasks with WebSockets in FastAPI](https://hexshift.medium.com/implementing-background-tasks-with-websockets-in-fastapi-034cdf803430)
- [D3.js Force-Directed Graph Implementation Guide 2025](https://dev.to/nigelsilonero/how-to-implement-a-d3js-force-directed-graph-in-2025-5cl1)
- [vasturiano/force-graph: Canvas force-directed graph](https://github.com/vasturiano/force-graph)
- [Performance Analysis: JSON vs MessagePack for WebSockets](https://dev.to/nate10/performance-analysis-of-json-buffer-custom-binary-protocol-protobuf-and-messagepack-for-websockets-2apn)
