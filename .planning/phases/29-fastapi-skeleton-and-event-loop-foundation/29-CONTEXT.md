# Phase 29: FastAPI Skeleton and Event Loop Foundation - Context

**Gathered:** 2026-04-12
**Status:** Ready for planning

<domain>
## Phase Boundary

Stand up the FastAPI server scaffold so all downstream v5.0 phases have a correct single-loop foundation. Uvicorn owns the asyncio event loop; all simulation infrastructure (StateStore, Governor, Neo4j driver) is created inside the FastAPI lifespan context. Deliver: `alphaswarm web` CLI subcommand, GET /api/health, non-destructive StateStore.snapshot(), per-client WebSocket queue skeleton, and SimulationManager singleton with 409 guard.

The Vue frontend, WebSocket broadcast, REST control endpoints, and all monitoring panels are out of scope — those are Phases 30-36.

</domain>

<decisions>
## Implementation Decisions

### Web Module Structure
- **D-01:** New `src/alphaswarm/web/` package with `app.py` (FastAPI factory + Uvicorn lifespan) and `routes/health.py` for GET /api/health.
- **D-02:** Sub-router pattern from the start: each domain gets its own `routes/*.py` file. Phase 30+ add route files without touching `app.py`.
- **D-03:** `web/__init__.py` exports `create_app` only — nothing else leaks to the package surface.

### Event Loop Ownership
- **D-04:** Uvicorn owns the asyncio event loop. All stateful objects (StateStore, ResourceGovernor, Neo4j driver, SimulationManager) are instantiated inside the FastAPI `@asynccontextmanager` lifespan function — never at module import time.
- **D-05:** AppState (`src/alphaswarm/app.py`) is reused as the central dependency container. The lifespan calls `create_app_state(with_ollama=True, with_neo4j=True)` and stores the result in `app.state`. FastAPI route handlers access it via `request.app.state.app_state`.

### StateStore Refactor (BE-02)
- **D-06:** `StateStore.snapshot()` becomes non-destructive — it no longer drains the rationale queue. A new `drain_rationales(limit: int = 5) -> tuple[RationaleEntry, ...]` method is added and called explicitly by the TUI tick (existing call site) and later by the WebSocket broadcaster (Phase 30).
- **D-07:** The TUI's existing `snapshot()` call site in `tui.py` is updated to call `snapshot()` + `drain_rationales(5)` together, preserving identical behavior.

### SimulationManager (BE-03 prerequisite + 409 guard)
- **D-08:** New class `web/simulation_manager.py` — thin wrapper with `async start(seed: str)`, `stop()`, `is_running: bool`. Uses an `asyncio.Lock` guard; raises `SimulationAlreadyRunningError` if `is_running` is True on entry to `start()`.
- **D-09:** `SimulationManager` is created inside the lifespan and stored on `app.state`. POST /api/simulate/start (Phase 32) will call it; this phase only wires up the class + 409 guard plumbing so success criterion SC-4 is testable.

### Per-Client WebSocket Queue Architecture (BE-03)
- **D-10:** Each connected WebSocket client gets its own `asyncio.Queue[str]` with `maxsize=100`. A dedicated `asyncio.Task` per client drains its queue and sends to the socket. Drop-oldest policy on overflow (put → catch QueueFull → get_nowait discard → put).
- **D-11:** `ConnectionManager` class in `web/connection_manager.py` manages the client registry (`dict[WebSocket, asyncio.Queue]`), connect/disconnect lifecycle, and broadcast (puts snapshot JSON into each client queue without awaiting send). Phase 30 wires the broadcaster into the queue.

### `alphaswarm web` CLI Subcommand
- **D-12:** Add `web` subparser to `cli.py` with `--host` (default `127.0.0.1`) and `--port` (default `8000`) only. No `--reload` — Uvicorn reload is an IDE/dev concern, not a production CLI arg.
- **D-13:** The handler calls `uvicorn.run(create_app(), host=args.host, port=args.port)` directly — no `asyncio.run()` wrapper (Uvicorn manages the loop itself).

### FastAPI / Uvicorn Dependencies
- **D-14:** Add `fastapi>=0.115` and `uvicorn[standard]>=0.34` to `pyproject.toml` dependencies. `websockets` is pulled in transitively by `uvicorn[standard]`.

### Health Endpoint Response
- **D-15:** GET /api/health returns 200 with JSON: `{"status": "ok", "simulation_phase": "<SimulationPhase.value>", "memory_percent": <float>, "is_simulation_running": <bool>}`. Memory percent sourced from `psutil.virtual_memory().percent` (already used by MemoryMonitor).

### Claude's Discretion
- Exact Pydantic response model field names (snake_case, as above)
- asyncio.Task cancellation cleanup in ConnectionManager.disconnect()
- Error handling shape for lifespan startup failures (Neo4j unreachable, etc.)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements
- `.planning/REQUIREMENTS.md` — BE-01, BE-02, BE-03 full acceptance text; traceability table

### Existing state infrastructure
- `src/alphaswarm/state.py` — StateStore.snapshot() (lines ~191-230): the destructive drain to remove; ReplayStore for non-destructive pattern reference
- `src/alphaswarm/app.py` — AppState dataclass + create_app_state() factory: lifespan will call this
- `src/alphaswarm/governor.py` — ResourceGovernor: must be created inside lifespan (asyncio.Queue init)

### CLI integration point
- `src/alphaswarm/cli.py` — argparse subparsers (lines ~825-900): add `web` subparser here

### Project config
- `pyproject.toml` — add fastapi + uvicorn[standard] to `[project] dependencies`

### Research flag
- **uvloop + neo4j async driver on M1:** `uvicorn[standard]` activates `uvloop` automatically on macOS. Some neo4j async driver versions have loop-compatibility constraints. Researcher must verify whether `uvloop` is safe with `neo4j>=5.28` on Darwin — if not, pin `uvicorn` without `[standard]` or set `loop="none"` in `uvicorn.run()`.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `AppState` + `create_app_state()` in `app.py` — lifespan calls this factory; no change needed to AppState itself, just call it inside the context manager
- `psutil.virtual_memory().percent` — already used in `memory_monitor.py`; reuse for health endpoint memory stat
- `SimulationPhase` enum in `types.py` — health endpoint serializes `.value`

### Established Patterns
- **Async-only, no blocking I/O** — all new coroutines follow this; `uvicorn.run()` is the only sync call and lives in the CLI handler, not inside async code
- **asyncio.Queue with drop-oldest** — StateStore._rationale_queue already uses this pattern (see push_rationale()); ConnectionManager client queues use the same idiom
- **Centralized AppState** — all subsystems receive AppState rather than constructing their own dependencies; web routes follow the same pattern via `request.app.state`
- **structlog** — use `structlog.get_logger(component="web")` for web-layer logging

### Integration Points
- `state.py` StateStore — needs `drain_rationales(limit)` added and `snapshot()` side effect removed; TUI call site in `tui.py` updated
- `cli.py` main() — add `web` subparser + elif branch (lines ~860-910 range)
- `pyproject.toml` — dependency addition only

</code_context>

<specifics>
## Specific Ideas

- No specific UI/UX references for this phase — it's pure plumbing.
- The `web/` package structure mirrors the pattern used in many FastAPI production projects (router-per-domain) and was explicitly chosen to scale cleanly through Phase 36.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 29-fastapi-skeleton-and-event-loop-foundation*
*Context gathered: 2026-04-12*
