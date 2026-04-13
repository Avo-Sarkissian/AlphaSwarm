# Phase 29: FastAPI Skeleton and Event Loop Foundation - Research

**Researched:** 2026-04-12
**Domain:** FastAPI lifespan, asyncio event loop ownership, WebSocket per-client queues, StateStore refactor
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** New `src/alphaswarm/web/` package with `app.py` (FastAPI factory + Uvicorn lifespan) and `routes/health.py` for GET /api/health.
- **D-02:** Sub-router pattern from the start: each domain gets its own `routes/*.py` file. Phase 30+ add route files without touching `app.py`.
- **D-03:** `web/__init__.py` exports `create_app` only.
- **D-04:** Uvicorn owns the asyncio event loop. All stateful objects (StateStore, ResourceGovernor, Neo4j driver, SimulationManager) are instantiated inside the FastAPI `@asynccontextmanager` lifespan function — never at module import time.
- **D-05:** AppState is reused as the central dependency container. The lifespan calls `create_app_state(with_ollama=True, with_neo4j=True)` and stores the result in `app.state`. Route handlers access it via `request.app.state.app_state`.
- **D-06:** `StateStore.snapshot()` becomes non-destructive. New `drain_rationales(limit: int = 5) -> tuple[RationaleEntry, ...]` method added. Called explicitly by TUI tick and later by WebSocket broadcaster.
- **D-07:** TUI `snapshot()` call site in `tui.py` updated to call `snapshot()` + `drain_rationales(5)` together.
- **D-08:** New class `web/simulation_manager.py` — thin wrapper with `async start(seed: str)`, `stop()`, `is_running: bool`. Uses `asyncio.Lock` guard; raises `SimulationAlreadyRunningError` if `is_running` is True on entry to `start()`.
- **D-09:** `SimulationManager` created inside lifespan and stored on `app.state`.
- **D-10:** Each connected WebSocket client gets its own `asyncio.Queue[str]` with `maxsize=100`. A dedicated `asyncio.Task` per client drains its queue and sends to the socket. Drop-oldest policy on overflow.
- **D-11:** `ConnectionManager` class in `web/connection_manager.py` manages client registry, connect/disconnect lifecycle, and broadcast. Phase 30 wires the broadcaster.
- **D-12:** Add `web` subparser to `cli.py` with `--host` (default `127.0.0.1`) and `--port` (default `8000`) only. No `--reload`.
- **D-13:** The handler calls `uvicorn.run(create_app(), host=args.host, port=args.port)` directly — no `asyncio.run()` wrapper.
- **D-14:** Add `fastapi>=0.115` and `uvicorn[standard]>=0.34` to `pyproject.toml` dependencies.
- **D-15:** GET /api/health returns 200 with JSON: `{"status": "ok", "simulation_phase": ..., "memory_percent": ..., "is_simulation_running": ...}`.

### Claude's Discretion

- Exact Pydantic response model field names (snake_case, as above)
- `asyncio.Task` cancellation cleanup in `ConnectionManager.disconnect()`
- Error handling shape for lifespan startup failures (Neo4j unreachable, etc.)

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope.
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| BE-01 | FastAPI app factory with Uvicorn lifespan owning the asyncio event loop (StateStore, Governor, Neo4j driver all created inside lifespan context) | Lifespan pattern, uvicorn.run() CLI call, asyncio.Queue timing constraint on ResourceGovernor |
| BE-02 | StateStore.snapshot() refactored to non-destructive so WebSocket broadcast does not drain the rationale queue | StateStore code audit, TUI call-site analysis, ReplayStore as non-destructive pattern reference |
| BE-03 | Per-client WebSocket queue — bounded asyncio queue + dedicated writer task per client; slow clients cannot stall the simulation | ConnectionManager pattern, asyncio.Queue drop-oldest, Task cleanup on disconnect |
</phase_requirements>

---

## Summary

Phase 29 builds the server scaffold that all v5.0 phases depend on. The primary constraint is **event loop ownership**: `ResourceGovernor` creates `asyncio.Queue` instances in its `TokenPool.__init__`, which means any `ResourceGovernor` constructed before an event loop is running will bind to the wrong loop. This is the same class of bug documented in the governor deadlock memory entry. The FastAPI `@asynccontextmanager` lifespan is the correct construction site for all stateful objects — `create_app_state()` must be called there, not at module import time.

The `uvicorn[standard]` package activates `uvloop` automatically via `auto_loop_factory` when `uvloop` is importable. The project venv does **not** currently have uvloop installed (confirmed via `uv run python -c "import uvloop"`). Adding `uvicorn[standard]` will pull in `uvloop` as a transitive dependency. The neo4j driver `5.28.3` (already installed) is safe with uvloop **provided** the driver is created inside the lifespan — the "different loop" issue (GitHub #868) was fixed in the driver's 5.x line by updating `AsyncCondition` to use Python 3.11 patterns. Creating the driver inside the lifespan context (where the uvloop-backed event loop is already running) is the correct pattern.

The `StateStore.snapshot()` refactor is surgical: five TUI call sites use `snapshot()`, but only one — `_poll_snapshot` at line 1308 — consumes `rationale_entries`. The other four only read `.phase` (and related scalar fields) and are unaffected by whether the drain happens or not. After the refactor, `snapshot()` returns a `StateSnapshot` with `rationale_entries=()` always; the TUI `_poll_snapshot` must call `drain_rationales(5)` separately and inject the result. The `StateSnapshot` dataclass retains the `rationale_entries` field so downstream WebSocket consumers (Phase 30) can include entries in the broadcasted JSON.

**Primary recommendation:** Create `create_app_state()` call inside the lifespan body, use `uvicorn.run(create_app(), ...)` directly from the CLI handler (synchronous call — Uvicorn manages the loop), and pass `loop="none"` only if the neo4j driver develops issues with uvloop (not expected given the driver version in use).

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| fastapi | >=0.115 (latest: 0.135.3) | ASGI web framework, routing, lifespan, WebSocket, Pydantic response models | Standard async Python web framework; Pydantic v2 native; lifespan via `@asynccontextmanager` since 0.93 |
| uvicorn[standard] | >=0.34 (latest: 0.44.0) | ASGI server, event loop owner, HTTP/1.1 + WebSocket upgrade, uvloop activation | Default FastAPI deployment server; `[standard]` pulls uvloop + websockets |
| starlette | (transitive via fastapi) | ASGI foundation, WebSocket primitives, `app.state` container | FastAPI is built on Starlette; `WebSocket`, `WebSocketDisconnect` imported from `fastapi` re-exports |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| uvloop | 0.22.1 (pulled transitively) | Fast asyncio event loop replacement | Activated automatically by uvicorn `auto_loop_factory` when importable |
| websockets | 15.0.1 (in project venv, pulled by uvicorn[standard]) | WebSocket protocol implementation | Pulled transitively; no direct import needed |
| psutil | >=7.2.2 (already in project) | `virtual_memory().percent` for health endpoint | Already used in `memory_monitor.py` — reuse, no new import |
| pydantic | >=2.12.5 (already in project) | Response models for health endpoint JSON | Already in project; use `BaseModel` for `HealthResponse` |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `uvicorn[standard]` (auto-uvloop) | `uvicorn` (no extras) + `loop="asyncio"` | Skip uvloop if neo4j driver issues emerge; pure asyncio has no compatibility risk |
| `app.state` for dependency access | FastAPI `Depends()` injection | `Depends()` creates per-request overhead; `request.app.state` is zero-overhead for singleton objects |
| `asyncio.Queue` per client | Single shared queue with fan-out | Per-client queue isolates slow consumers and prevents head-of-line blocking |

**Installation (to add to pyproject.toml):**
```
fastapi>=0.115
uvicorn[standard]>=0.34
```

**Version verification (confirmed 2026-04-12):**
- `fastapi` latest: 0.135.3 (PyPI confirmed)
- `uvicorn` latest: 0.44.0 (PyPI confirmed)
- `uvicorn[standard]` in project venv: 0.42.0 with uvloop 0.22.1
- `neo4j` in project venv: 5.28.3 (already installed)

---

## Architecture Patterns

### Recommended Project Structure

```
src/alphaswarm/
├── web/
│   ├── __init__.py          # exports create_app only
│   ├── app.py               # FastAPI factory + @asynccontextmanager lifespan
│   ├── simulation_manager.py  # SimulationManager + SimulationAlreadyRunningError
│   ├── connection_manager.py  # ConnectionManager per-client queue registry
│   └── routes/
│       └── health.py        # GET /api/health router
```

### Pattern 1: FastAPI Lifespan with app.state

**What:** Use `@asynccontextmanager` to manage object lifecycle. Store the dependency container on `app.state` before yielding.

**When to use:** All server-side singletons that need to be created inside a running event loop (ResourceGovernor, StateStore, SimulationManager, Neo4j driver).

**Example:**
```python
# Source: https://fastapi.tiangolo.com/advanced/events/
from contextlib import asynccontextmanager
from fastapi import FastAPI

@asynccontextmanager
async def lifespan(app: FastAPI):
    # All construction happens here — event loop is running
    app_state = create_app_state(settings, personas, with_ollama=True, with_neo4j=True)
    app.state.app_state = app_state
    app.state.sim_manager = SimulationManager(app_state)
    app.state.connection_manager = ConnectionManager()
    yield
    # Shutdown cleanup
    await app_state.graph_manager.close()  # if applicable

def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)
    app.include_router(health_router, prefix="/api")
    return app
```

**Route access pattern:**
```python
# Source: FastAPI docs — app.state vs request.state
from fastapi import Request

@router.get("/health")
async def health(request: Request):
    app_state = request.app.state.app_state
    sim_manager = request.app.state.sim_manager
    ...
```

### Pattern 2: uvicorn.run() from CLI (synchronous)

**What:** `uvicorn.run()` is a blocking synchronous call that creates and owns the event loop internally. Do not wrap with `asyncio.run()`.

**When to use:** CLI handler for the `web` subcommand.

**Example:**
```python
# D-13: uvicorn.run() is synchronous — it creates and manages the loop
import uvicorn
from alphaswarm.web import create_app

def _handle_web(host: str, port: int) -> None:
    uvicorn.run(create_app(), host=host, port=port)
    # loop="auto" is the default — activates uvloop when available
```

**Critical:** Do NOT call `asyncio.run(_handle_web(...))`. The handler is synchronous; Uvicorn manages the loop.

### Pattern 3: Per-Client WebSocket Queue

**What:** Each connected WebSocket gets an `asyncio.Queue[str]` (bounded) and a dedicated `asyncio.Task` that drains the queue and sends to the socket. The broadcaster puts to each queue without awaiting sends.

**When to use:** Any broadcast scenario where you cannot afford slow clients blocking the producer.

**Example:**
```python
# Source: FastAPI WebSocket docs + asyncio.Queue pattern
import asyncio
from fastapi import WebSocket

class ConnectionManager:
    def __init__(self) -> None:
        self._clients: dict[WebSocket, asyncio.Queue[str]] = {}
        self._tasks: dict[WebSocket, asyncio.Task[None]] = {}

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=100)
        self._clients[ws] = queue
        self._tasks[ws] = asyncio.create_task(self._writer(ws, queue))

    async def disconnect(self, ws: WebSocket) -> None:
        task = self._tasks.pop(ws, None)
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._clients.pop(ws, None)

    async def _writer(self, ws: WebSocket, queue: asyncio.Queue[str]) -> None:
        try:
            while True:
                data = await queue.get()
                await ws.send_text(data)
        except Exception:
            pass  # Connection dropped — task exits naturally

    def broadcast(self, message: str) -> None:
        """Non-blocking put to all client queues. Drop-oldest on overflow."""
        for queue in self._clients.values():
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()  # Drop oldest
                except asyncio.QueueEmpty:
                    pass
                queue.put_nowait(message)
```

**Critical:** `broadcast()` is synchronous (non-awaited). It puts to queues immediately without awaiting any sends. This prevents slow WebSocket clients from stalling the simulation.

### Pattern 4: SimulationManager with asyncio.Lock 409 Guard

**What:** A thin wrapper around the existing simulation entrypoint. An `asyncio.Lock` used as a try-acquire guard: if already locked, `is_running` is True and `start()` raises immediately.

**When to use:** Any endpoint that must enforce single-concurrency on a long-running async operation.

**Example:**
```python
import asyncio

class SimulationAlreadyRunningError(Exception):
    pass

class SimulationManager:
    def __init__(self, app_state: AppState) -> None:
        self._app_state = app_state
        self._lock = asyncio.Lock()
        self._is_running = False

    @property
    def is_running(self) -> bool:
        return self._is_running

    async def start(self, seed: str) -> None:
        if self._lock.locked():
            raise SimulationAlreadyRunningError("Simulation already running")
        async with self._lock:
            self._is_running = True
            try:
                # Phase 32 wires actual simulation call here
                pass
            finally:
                self._is_running = False

    def stop(self) -> None:
        # Phase 32: cancel the running simulation task
        pass
```

**409 guard at route level (Phase 32):**
```python
from fastapi import HTTPException, status

@router.post("/simulate/start")
async def start_simulation(request: Request):
    sim_manager = request.app.state.sim_manager
    try:
        await sim_manager.start(seed=...)
    except SimulationAlreadyRunningError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="Simulation already running")
```

### Pattern 5: StateStore.snapshot() Non-Destructive Refactor

**What:** Remove the drain loop from `snapshot()`. Add `drain_rationales(limit: int = 5) -> tuple[RationaleEntry, ...]` as an explicit method. Update the single TUI call site that uses rationale entries.

**When to use:** Whenever multiple consumers need to independently read state (WebSocket broadcaster + TUI tick) without one consumer stealing entries from the other.

**Before (destructive — current):**
```python
def snapshot(self) -> StateSnapshot:
    entries: list[RationaleEntry] = []
    for _ in range(5):
        try:
            entries.append(self._rationale_queue.get_nowait())
        except asyncio.QueueEmpty:
            break
    return StateSnapshot(..., rationale_entries=tuple(entries))
```

**After (non-destructive + explicit drain):**
```python
def snapshot(self) -> StateSnapshot:
    """Return immutable snapshot. No side effects — rationale queue not touched."""
    return StateSnapshot(
        phase=self._phase,
        round_num=self._round_num,
        agent_count=100,
        agent_states=dict(self._agent_states),
        elapsed_seconds=(...),
        governor_metrics=self._latest_governor_metrics,
        tps=self._compute_tps(),
        rationale_entries=(),  # Always empty — call drain_rationales() explicitly
        bracket_summaries=self._bracket_summaries,
    )

def drain_rationales(self, limit: int = 5) -> tuple[RationaleEntry, ...]:
    """Drain up to `limit` entries from the rationale queue. Destructive read."""
    entries: list[RationaleEntry] = []
    for _ in range(limit):
        try:
            entries.append(self._rationale_queue.get_nowait())
        except asyncio.QueueEmpty:
            break
    return tuple(entries)
```

**TUI _poll_snapshot update (line 1308 area):**
```python
# Before:
snapshot = self.app_state.state_store.snapshot()
# ... later uses snapshot.rationale_entries

# After:
snapshot = self.app_state.state_store.snapshot()
rationale_entries = self.app_state.state_store.drain_rationales(5)
# Replace snapshot.rationale_entries with rationale_entries in sidebar update code
```

**Other TUI snapshot() call sites (lines 116, 945, 997, 1183, 1415) only read `.phase`, `.elapsed_seconds`, or `.agent_states` — they do NOT consume `rationale_entries` and require NO changes.**

### Anti-Patterns to Avoid

- **Creating asyncio objects at module import time:** `ResourceGovernor.__init__` creates `asyncio.Queue` via `TokenPool.__init__`. If constructed before the event loop starts, it binds to the pre-loop event loop and causes "Future attached to a different loop" at runtime. Always construct inside lifespan.
- **Wrapping `uvicorn.run()` with `asyncio.run()`:** `uvicorn.run()` is synchronous and creates its own event loop. Wrapping it creates a nested loop conflict. The CLI handler must be a plain `def`, not `async def`.
- **Creating the neo4j driver at module import time:** Same "different loop" class of bug. The existing `app.py` creates the driver inside `create_app_state()` (a function), which is called inside the lifespan — this is correct.
- **Direct `await websocket.send_text()` in the broadcaster:** This blocks the broadcaster coroutine on each slow client. Use the per-client queue pattern so the broadcaster is non-blocking.
- **Using `@app.on_event("startup")`:** Deprecated since FastAPI 0.93. Use `@asynccontextmanager` lifespan exclusively.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| ASGI WebSocket upgrade + HTTP/1.1 | Custom socket server | uvicorn + starlette WebSocket | Protocol negotiation, keep-alive, error handling are complex |
| Request routing with type validation | Custom dispatcher | FastAPI `APIRouter`, `include_router()` | Pydantic v2 validation, OpenAPI schema generation, dependency injection |
| Pydantic response serialization | `json.dumps(dataclass)` | FastAPI `response_model=HealthResponse` | Automatic serialization, validation, OpenAPI docs |
| Event loop lifecycle | `asyncio.run()` wrapper | `uvicorn.run()` | Uvicorn handles signal trapping, graceful shutdown, reload |

**Key insight:** FastAPI + Uvicorn already handle the entire HTTP/WebSocket/event-loop stack. Phase 29 only needs to wire them together correctly; no custom protocol code is needed.

---

## Runtime State Inventory

Step 2.5: SKIPPED — this is a greenfield phase (new package, no rename/refactor of existing identifiers). The `web/` package is entirely new. `StateStore.snapshot()` is refactored in-place but no stored data, OS registrations, or runtime state is renamed.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.11+ | uv-managed venv | Yes | 3.11.5 (uv venv) | — |
| fastapi | BE-01, BE-02, BE-03 | No (not yet in pyproject.toml) | — | Add to pyproject.toml |
| uvicorn[standard] | BE-01 (event loop owner) | No (not yet in pyproject.toml) | — | Add to pyproject.toml |
| uvloop | Auto-activated by uvicorn[standard] | No (not in venv) | — | Pulled transitively with uvicorn[standard] |
| neo4j | BE-01 (lifespan wiring) | Yes | 5.28.3 | — |
| psutil | Health endpoint memory% | Yes | 7.2.2 | — |
| pydantic | Health response model | Yes | 2.12.5 | — |
| websockets | WebSocket protocol | Yes (in venv as 15.0.1) | 15.0.1 | — |

**Missing dependencies with no fallback:**
- `fastapi>=0.115` and `uvicorn[standard]>=0.34` — must be added to `pyproject.toml` before any web code runs

**Missing dependencies with fallback:**
- None. All critical dependencies are either already present or trivially addable.

---

## Common Pitfalls

### Pitfall 1: asyncio Objects Created Before Event Loop

**What goes wrong:** `ResourceGovernor.__init__` calls `TokenPool.__init__` which calls `asyncio.Queue()`. If this happens before `uvicorn.run()` starts the event loop, the Queue binds to whatever loop `asyncio.get_event_loop()` returns at that moment. When Uvicorn creates its own loop (uvloop), all subsequent `await queue.get()` calls fail with "Future attached to a different loop."

**Why it happens:** `create_app_state()` is currently a synchronous function and could be called at module level or in `__init__` of a FastAPI dependency outside the lifespan.

**How to avoid:** Call `create_app_state()` only inside the `@asynccontextmanager lifespan(app)` body — never at module import time, never in `create_app()` outside the lifespan.

**Warning signs:** "Future attached to a different loop" at startup; Governor deadlock after the first round (the exact class of bug documented in `bug_governor_deadlock.md`).

### Pitfall 2: uvicorn.run() Inside asyncio.run()

**What goes wrong:** Calling `asyncio.run(uvicorn.run(...))` raises `RuntimeError: This event loop is already running` because `uvicorn.run()` calls `asyncio.run()` internally.

**Why it happens:** CLI handlers for other commands (inject, report) use `asyncio.run()`. If the `web` handler is written the same way, it conflicts.

**How to avoid:** The `_handle_web()` CLI function must be a plain `def`, not `async def`. Call `uvicorn.run(create_app(), host=host, port=port)` directly.

### Pitfall 3: TUI snapshot() Call Sites Not All Updated

**What goes wrong:** After making `snapshot()` non-destructive, code that previously relied on `snapshot()` populating `rationale_entries` now sees an empty tuple. If only `_poll_snapshot` is updated and the other 4 call sites are forgotten, the sidebar appears to work (those sites don't use `rationale_entries`) but the developer may be confused why the sidebar is blank.

**Why it happens:** There are 5 TUI call sites for `snapshot()`. Only one — `_poll_snapshot` at line 1308 — reads `snapshot.rationale_entries`. The other four (lines 116, 945, 997, 1183, 1415) only read `.phase` and scalar fields.

**How to avoid:** Only `_poll_snapshot` (line 1308) needs updating. Update it to call `drain_rationales(5)` after `snapshot()` and use the returned tuple for the sidebar. Leave the other 4 call sites unchanged.

### Pitfall 4: ConnectionManager Task Not Cancelled on Disconnect

**What goes wrong:** If `ConnectionManager.disconnect()` does not cancel and await the per-client writer task, the task continues to run after the WebSocket is closed. It will keep calling `await queue.get()` and then fail on `ws.send_text()` with a stale connection, leaking an orphaned asyncio.Task that never gets garbage-collected.

**Why it happens:** `asyncio.create_task()` tasks survive their creator's scope unless explicitly cancelled.

**How to avoid:** Always `task.cancel()` then `await task` (catching `asyncio.CancelledError`) inside `disconnect()`. Use a `finally` block in the endpoint handler to ensure disconnect is always called.

### Pitfall 5: neo4j Driver + uvloop "Different Loop" (Mitigated)

**What goes wrong:** If the neo4j `AsyncGraphDatabase.driver()` call happens before the uvloop event loop is installed (i.e., before `uvicorn.run()` is entered), the driver's async synchronization primitives may bind to the default asyncio loop. When uvloop replaces it, operations fail.

**Why it happens:** The `auto_loop_factory` in uvicorn installs uvloop via `uvloop.new_event_loop` only when the server starts. Any code that creates `asyncio` objects before that point uses the stdlib loop.

**How to avoid:** This is mitigated by D-04 (create everything inside lifespan). The neo4j driver fix in PR #879 (shipped in driver 5.x) also removed the dependency on `asyncio.get_event_loop()` at construction time, so the risk is LOW given `neo4j>=5.28.3`. Confirmed safe pattern: call `create_app_state(with_neo4j=True)` only inside the lifespan body.

**Fallback:** If issues surface at runtime, pass `loop="asyncio"` to `uvicorn.run()` to skip uvloop entirely. The performance difference at 100-agent simulation scale on localhost is negligible.

---

## Code Examples

### Health Endpoint Response Model

```python
# Source: FastAPI docs + pydantic v2 BaseModel
from pydantic import BaseModel

class HealthResponse(BaseModel):
    status: str
    simulation_phase: str      # SimulationPhase.value e.g. "idle"
    memory_percent: float      # psutil.virtual_memory().percent
    is_simulation_running: bool

@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    import psutil
    app_state = request.app.state.app_state
    sim_manager = request.app.state.sim_manager
    snap = app_state.state_store.snapshot()
    return HealthResponse(
        status="ok",
        simulation_phase=snap.phase.value,
        memory_percent=psutil.virtual_memory().percent,
        is_simulation_running=sim_manager.is_running,
    )
```

### CLI Web Subparser Addition

```python
# src/alphaswarm/cli.py — add to main() subparsers section
web_parser = subparsers.add_parser("web", help="Start web UI server")
web_parser.add_argument("--host", type=str, default="127.0.0.1")
web_parser.add_argument("--port", type=int, default=8000)

# In main() elif chain:
elif args.command == "web":
    try:
        _handle_web(args.host, args.port)
    except KeyboardInterrupt:
        print("\nAborted.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        logger.error("web_failed", error=str(e))
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

def _handle_web(host: str, port: int) -> None:
    """Start Uvicorn server. Synchronous — Uvicorn manages the event loop."""
    import uvicorn
    from alphaswarm.web import create_app
    uvicorn.run(create_app(), host=host, port=port)
```

### StateSnapshot field note

`StateSnapshot.rationale_entries` field is retained as `tuple[RationaleEntry, ...]` in the dataclass even after the refactor — it defaults to `()`. The WebSocket broadcaster (Phase 30) will populate it by calling `drain_rationales()` and then constructing a snapshot-like payload. The TUI call sites that only read `.phase` will naturally receive `()` for `rationale_entries` and are unaffected.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `@app.on_event("startup")` / `@app.on_event("shutdown")` | `@asynccontextmanager` lifespan passed to `FastAPI(lifespan=...)` | FastAPI 0.93 (2023) | Old approach still works but deprecated; lifespan is the standard |
| `asyncio.get_event_loop()` in driver init | Python 3.11 primitives (no `get_event_loop` at construction) | neo4j driver 5.x PR #879 | Resolves "different loop" error class; safe to create driver inside lifespan |
| `uvicorn --loop uvloop` CLI flag | `loop="auto"` default + `uvloop` installed | uvicorn 0.20+ | Auto-detection means no explicit flag needed; uvloop activated by presence in venv |

**Deprecated/outdated:**
- `@app.on_event("startup")`: Still functional but emits deprecation warning in FastAPI 0.115+. Do not use.
- `asyncio.get_event_loop()` in application code: Deprecated in Python 3.10+. All new code uses `asyncio.get_running_loop()` or constructs objects inside `async def`.

---

## Open Questions

1. **neo4j driver lifespan `async with` vs manual close**
   - What we know: `AsyncGraphDatabase.driver()` returns a driver that should be closed via `await driver.close()`. The existing `app.py` pattern does not use `async with` for the driver.
   - What's unclear: Whether `GraphStateManager` already wraps `driver.close()` in its own shutdown or whether the lifespan needs to call it explicitly.
   - Recommendation: Check `GraphStateManager` for a `close()` or `aclose()` method. If absent, add `await app_state.graph_manager.driver.close()` in the lifespan cleanup (after `yield`). This is a Claude's Discretion item.

2. **pyproject.toml scripts entry for `alphaswarm web`**
   - What we know: `[project.scripts]` currently has `start = "alphaswarm.cli:main_tui"`. The `alphaswarm` CLI entry point is `main()`.
   - What's unclear: Whether a separate `web` console script entry is needed or if `alphaswarm web` via the main entrypoint is sufficient.
   - Recommendation: No new script entry needed. `alphaswarm web` via `main()` subparser is the correct pattern (consistent with `alphaswarm tui`, `alphaswarm run`, etc.).

---

## Project Constraints (from CLAUDE.md)

- **100% async** (`asyncio`): All web route handlers must be `async def`. No blocking I/O on the main event loop. `uvicorn.run()` in the CLI handler is the only synchronous call.
- **Local First:** No external APIs. FastAPI serves only localhost per D-12 (default `127.0.0.1`).
- **Memory Safety:** `psutil.virtual_memory().percent` is already used in `memory_monitor.py`. Health endpoint reuses this without adding a new monitoring loop.
- **Miro API constraint:** Not applicable to this phase.
- **Python 3.11+ strict typing:** All new files must have `from __future__ import annotations` and complete type annotations. Use `str | None` not `Optional[str]`.
- **`uv` package manager:** Add dependencies to `pyproject.toml`, not via `pip install`. Run `uv sync` after updating `pyproject.toml`.
- **`structlog`:** Web layer logging uses `structlog.get_logger(component="web")`.
- **`pytest-asyncio`:** `asyncio_mode = "auto"` is set in `pyproject.toml`. All async test functions work without the `@pytest.mark.asyncio` decorator.
- **`ruff` linting:** `select = ["E", "F", "I", "N", "W", "UP", "B", "SIM"]`. New code must pass `uv run ruff check src/`.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.0 + pytest-asyncio 0.24 |
| Config file | `pyproject.toml` — `asyncio_mode = "auto"`, `testpaths = ["tests"]` |
| Quick run command | `uv run pytest tests/test_state.py tests/test_web.py -x -q` |
| Full suite command | `uv run pytest tests/ -x -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| BE-01 | `alphaswarm web` starts Uvicorn; GET /api/health returns 200 with simulation_phase, memory_percent, is_simulation_running | integration (FastAPI TestClient) | `uv run pytest tests/test_web.py::test_health_endpoint -x` | No — Wave 0 |
| BE-01 | All stateful objects (StateStore, ResourceGovernor, SimulationManager) are created inside lifespan, not at module import time | unit | `uv run pytest tests/test_web.py::test_lifespan_creates_objects_inside_loop -x` | No — Wave 0 |
| BE-02 | `StateStore.snapshot()` called twice in succession returns identical data (rationale_entries=() both times) | unit | `uv run pytest tests/test_state.py::test_snapshot_non_destructive -x` | No — Wave 0 |
| BE-02 | `StateStore.drain_rationales(5)` removes entries; second call returns fewer | unit | `uv run pytest tests/test_state.py::test_drain_rationales -x` | No — Wave 0 |
| BE-02 | TUI `_poll_snapshot` behavior preserved — rationale sidebar receives entries via `drain_rationales(5)` | unit | `uv run pytest tests/test_state.py::test_drain_rationales_tui_compat -x` | No — Wave 0 |
| BE-03 | Second WebSocket client connecting does not drain rationale entries the first client should receive | integration | `uv run pytest tests/test_web.py::test_websocket_queue_isolation -x` | No — Wave 0 |
| BE-03 | Slow client overflow: when queue is full, oldest entry dropped and newest entry survives | unit | `uv run pytest tests/test_web.py::test_connection_manager_drop_oldest -x` | No — Wave 0 |
| BE-03 | Client disconnect cancels the writer task cleanly (no orphaned tasks) | unit | `uv run pytest tests/test_web.py::test_connection_manager_disconnect_cancels_task -x` | No — Wave 0 |
| SC-4 | POST /api/simulate/start while already running returns HTTP 409 | integration | `uv run pytest tests/test_web.py::test_simulation_manager_409_guard -x` | No — Wave 0 |

### Existing Tests (must remain green)

```
uv run pytest tests/test_state.py -x -q   # 28 tests — must still pass after snapshot() refactor
```

All existing `test_state.py` tests that call `snapshot()` and assert on `rationale_entries` (e.g., `test_rationale_queue_drain`, `test_snapshot_drain_queue_twice`) will BREAK after the refactor. They must be updated in the same task that refactors `snapshot()`.

### Sampling Rate

- **Per task commit:** `uv run pytest tests/test_state.py -x -q` (existing state tests)
- **Per wave merge:** `uv run pytest tests/ -x -q` (full suite)
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_web.py` — all 6 web tests (health endpoint, lifespan, SimulationManager 409, ConnectionManager queue isolation and disconnect)
- [ ] `tests/test_state.py` — add `test_snapshot_non_destructive`, `test_drain_rationales`, `test_drain_rationales_tui_compat`; update `test_rationale_queue_drain` and `test_snapshot_drain_queue_twice` to use `drain_rationales()` instead of relying on `snapshot()` side effect
- [ ] Framework install: `uv add "fastapi>=0.115" "uvicorn[standard]>=0.34"` — must run before any web code is importable

---

## Sources

### Primary (HIGH confidence)

- FastAPI official docs — https://fastapi.tiangolo.com/advanced/events/ — lifespan pattern, `@asynccontextmanager`, `app.state` storage
- FastAPI official docs — https://fastapi.tiangolo.com/advanced/websockets/ — WebSocket endpoint, ConnectionManager, `WebSocketDisconnect`
- Uvicorn official docs — https://www.uvicorn.org/settings/ — `--loop auto` behavior, programmatic `uvicorn.run()`
- Uvicorn source code — `uvicorn.loops.auto.auto_loop_factory` — confirmed: uvloop activated if importable, falls back to asyncio if not
- Uvicorn source code — `uvicorn.loops.uvloop.uvloop_loop_factory` — confirmed: installs `uvloop.new_event_loop`
- neo4j/neo4j-python-driver GitHub issue #868 + PR #879 — "different loop" root cause and fix; confirmed resolved in 5.x
- Project source — `src/alphaswarm/state.py` — all StateStore methods, current `snapshot()` destructive drain, ReplayStore non-destructive pattern
- Project source — `src/alphaswarm/app.py` — `create_app_state()` factory, neo4j driver creation timing
- Project source — `src/alphaswarm/governor.py` — `TokenPool.__init__` creates `asyncio.Queue` — confirms objects must be in lifespan
- Project source — `src/alphaswarm/tui.py` — all 5 `snapshot()` call sites identified; only line 1308 (`_poll_snapshot`) consumes `rationale_entries`
- PyPI registry (2026-04-12) — fastapi 0.135.3, uvicorn 0.44.0 confirmed latest versions

### Secondary (MEDIUM confidence)

- WebSearch "FastAPI lifespan pattern app.state" — multiple sources confirm `app.state` object storage pattern
- WebSearch "uvicorn.run() synchronous CLI pattern" — confirmed: synchronous call without `asyncio.run()` wrapper is canonical

### Tertiary (LOW confidence)

- WebSearch "uvloop neo4j macOS M1 compatibility" — no specific uvloop+neo4j incompatibility found in official sources; absence of issue reports is weakly positive evidence

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — versions verified from PyPI and uv venv
- Architecture: HIGH — patterns verified from official FastAPI docs and project source code audit
- Pitfalls: HIGH — governor asyncio.Queue timing confirmed by source inspection; neo4j "different loop" confirmed fixed per GitHub PR #879
- uvloop + neo4j compatibility: MEDIUM — no documented incompatibility found; fix confirmed in 5.x; fallback (`loop="asyncio"`) available if needed

**Research date:** 2026-04-12
**Valid until:** 2026-07-12 (stable APIs — FastAPI, Uvicorn, neo4j 5.x are not fast-moving)
