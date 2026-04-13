# Phase 30: WebSocket State Stream - Research

**Researched:** 2026-04-12
**Domain:** WebSocket broadcast, asyncio background tasks, JSON serialization
**Confidence:** HIGH

## Summary

Phase 30 wires a 5Hz WebSocket broadcast loop that serializes `StateSnapshot` + drained rationales as JSON and pushes the result to all connected clients via the Phase 29 `ConnectionManager`. The infrastructure is almost entirely in place: `ConnectionManager` with per-client bounded queues and drop-oldest policy, `StateStore.snapshot()` (non-destructive) and `drain_rationales(limit)`, and the FastAPI lifespan pattern for task lifecycle. This phase adds two new files (`web/broadcaster.py` and `web/routes/websocket.py`), modifies two existing files (`web/app.py` lifespan/create_app and `tests/test_web.py`), and touches nothing else.

The JSON payload is ~7.3 KB per tick at full 100-agent capacity, yielding ~36.5 KB/s per client at 5Hz. The `str, Enum` base classes on `SignalType` and `SimulationPhase` ensure `json.dumps(dataclasses.asdict(snapshot))` works without a custom encoder. No new dependencies are needed.

**Primary recommendation:** Implement the broadcaster as a simple `asyncio.Task` with a `while True: snapshot + serialize + broadcast + sleep(0.2)` loop, and the WebSocket endpoint as a thin `connect -> receive_text loop -> disconnect` handler. The existing `ConnectionManager.broadcast()` is synchronous (non-blocking put_nowait to all queues), so the broadcaster tick cost is negligible.

## Project Constraints (from CLAUDE.md)

- **Concurrency:** 100% async (`asyncio`). No blocking I/O on the main event loop.
- **Local First:** All inference local via Ollama. No cloud APIs (except Miro). Max 2 models loaded simultaneously.
- **Memory Safety:** Monitor RAM via `psutil`. Dynamically throttle `asyncio` semaphores; pause task queue at 90% utilization.
- **Runtime:** Python 3.11+ (Strict typing), `uv` (Package manager), `pytest-asyncio`.
- **Logging/HTTP:** `structlog`, `httpx`.
- **Validation/Config:** `pydantic`, `pydantic-settings`.

Note: The project is running Python 3.10.14 (not 3.11+), FastAPI 0.135.1, Starlette 0.52.1, pytest 9.0.2, pytest-asyncio 1.3.0. All patterns verified against these versions.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** The broadcaster runs as an always-on `asyncio.Task` started inside the FastAPI lifespan. It ticks at 200ms (5Hz) from server start, even during `SimulationPhase.IDLE`. IDLE snapshots are cheap (empty `agent_states`, no rationale entries) and let the Vue frontend show a "waiting" state without extra logic.
- **D-02:** The broadcaster task is cancelled in the lifespan teardown (alongside graph_manager close). No start/stop wiring with `SimulationManager`.
- **D-03:** Each broadcast includes the **full `StateSnapshot`**: `phase`, `round_num`, `elapsed_seconds`, `agent_states` (all 100 agents), `bracket_summaries` (10 brackets), `governor_metrics`, `tps`, and `rationale_entries`.
- **D-04:** Rationale entries are included -- the broadcaster calls `drain_rationales(5)` each tick and injects the result into the payload. The WebSocket broadcaster owns the rationale drain from this phase forward.
- **D-05:** `json.dumps(dataclasses.asdict(snapshot_with_rationales))` -- no new Pydantic wire model needed this phase. `SignalType` is `str, Enum` so Python's JSON encoder serializes it as its string value. Explicit Pydantic schema deferred to Phase 31.
- **D-06:** A helper `snapshot_to_json(state_store: StateStore) -> str` in `web/broadcaster.py` encapsulates the `snapshot()` + `drain_rationales()` + `asdict()` + `json.dumps()` pipeline.
- **D-07:** New module `web/broadcaster.py` exports `start_broadcaster(state_store, connection_manager) -> asyncio.Task`. The lifespan calls this and stores the task on `app.state.broadcaster_task` for cancellation on shutdown.
- **D-08:** New router `web/routes/websocket.py` with a single `@router.websocket("/ws/state")` endpoint. Registered in `create_app()` without a prefix (WebSocket routes use full paths).
- **D-09:** The `/ws/state` handler calls `connection_manager.connect(ws)` then enters a receive loop (`await ws.receive_text()` or `receive_bytes()`) to detect client disconnects. On `WebSocketDisconnect` or any exception, calls `connection_manager.disconnect(ws)` in a `finally` block.
- **D-10:** The endpoint is unauthenticated -- local dev only, no auth headers needed.

### Claude's Discretion
- Exact `asyncio.sleep(0.2)` vs `asyncio.wait_for` timing in the broadcast loop
- Whether the receive loop uses `receive_text()` or `receive_bytes()` (both detect disconnect)
- Error handling for serialization failures (log + skip tick)

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| BE-04 | Real-time WebSocket broadcast of StateSnapshot JSON at 5Hz to all connected browser clients | `ConnectionManager.broadcast()` already handles per-client queue delivery with drop-oldest; `StateStore.snapshot()` + `drain_rationales()` provide the data source; `dataclasses.asdict()` + `json.dumps()` handles serialization (verified: all `str, Enum` types serialize cleanly) |
</phase_requirements>

## Standard Stack

### Core (Already Installed)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| fastapi | 0.135.1 | WebSocket endpoint + router | Already the web framework; native WebSocket support via Starlette |
| starlette | 0.52.1 | `WebSocketDisconnect` exception, TestClient WebSocket | Underlying ASGI toolkit; provides WebSocket primitives |
| structlog | (installed) | Component-scoped logging | Project convention per CLAUDE.md |

### Supporting (Already Installed)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| json (stdlib) | N/A | Snapshot serialization | `json.dumps(dataclasses.asdict(snapshot))` -- no external JSON lib needed |
| dataclasses (stdlib) | N/A | `asdict()` for snapshot flattening | Converts frozen dataclasses to dicts for JSON serialization |
| asyncio (stdlib) | N/A | Background task, sleep, CancelledError | Broadcaster loop lifecycle |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `json.dumps` | `orjson` / `msgspec` | Faster but adds dependency; 7.3KB payload at 5Hz is trivially fast with stdlib json |
| `dataclasses.asdict` | Pydantic model `.model_dump_json()` | Deferred to Phase 31 per D-05; current dataclass approach avoids new wire models |
| `asyncio.sleep(0.2)` | `asyncio.wait_for` with timeout | `sleep(0.2)` is simpler and sufficient for a fixed-rate tick; no adaptive rate needed |

**Installation:** No new packages required.

## Architecture Patterns

### Recommended Project Structure (additions only)
```
src/alphaswarm/web/
  broadcaster.py       # NEW: snapshot_to_json() + start_broadcaster()
  routes/
    websocket.py       # NEW: /ws/state endpoint
  app.py               # MODIFIED: lifespan starts broadcaster; create_app includes ws_router
tests/
  test_web.py          # MODIFIED: add Phase 30 WebSocket tests
```

### Pattern 1: Broadcaster Loop as Lifespan-Owned Task
**What:** An `asyncio.Task` started in the FastAPI lifespan that runs a `while True` loop: serialize snapshot, broadcast to all clients, sleep 200ms.
**When to use:** When you need a server-push pattern where the server determines the tick rate, not client requests.
**Example:**
```python
# Source: FastAPI lifespan pattern + project conventions
async def _broadcast_loop(
    state_store: StateStore,
    connection_manager: ConnectionManager,
) -> None:
    log = structlog.get_logger(component="web.broadcaster")
    while True:
        try:
            message = snapshot_to_json(state_store)
            connection_manager.broadcast(message)
        except Exception:
            log.exception("broadcast_tick_error")
        await asyncio.sleep(0.2)

def start_broadcaster(
    state_store: StateStore,
    connection_manager: ConnectionManager,
) -> asyncio.Task[None]:
    return asyncio.create_task(
        _broadcast_loop(state_store, connection_manager),
        name="broadcaster",
    )
```

### Pattern 2: WebSocket Endpoint with Receive-Loop Disconnect Detection
**What:** The WebSocket handler accepts the connection via `ConnectionManager.connect()`, then enters a blocking receive loop that exists solely to detect client disconnects. The actual data flow is server-to-client only (broadcast via ConnectionManager's per-client writer tasks).
**When to use:** Server-push WebSocket where the client never sends data but you need to detect disconnects.
**Example:**
```python
# Source: FastAPI official WebSocket docs + Starlette WebSocketDisconnect
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()

@router.websocket("/ws/state")
async def ws_state(websocket: WebSocket, request: Request) -> None:
    connection_manager = request.app.state.connection_manager
    await connection_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()  # blocks until client sends or disconnects
    except WebSocketDisconnect:
        pass
    finally:
        await connection_manager.disconnect(websocket)
```

### Pattern 3: Snapshot Serialization Helper
**What:** A pure function that calls `state_store.snapshot()`, `state_store.drain_rationales(5)`, merges rationale entries into the snapshot dict, and returns a JSON string.
**When to use:** Encapsulates the snapshot-to-wire pipeline so the broadcaster loop stays clean.
**Example:**
```python
# Source: CONTEXT.md D-06
import dataclasses
import json
from alphaswarm.state import StateStore

def snapshot_to_json(state_store: StateStore) -> str:
    snap = state_store.snapshot()
    rationales = state_store.drain_rationales(5)
    d = dataclasses.asdict(snap)
    d["rationale_entries"] = [dataclasses.asdict(r) for r in rationales]
    return json.dumps(d)
```

### Anti-Patterns to Avoid
- **Awaiting broadcast inside the loop:** `ConnectionManager.broadcast()` is synchronous (`put_nowait`). Do NOT make it async or await individual sends -- that would block the tick for slow clients.
- **Creating the broadcaster task at module import:** All asyncio objects must be created inside the event loop (lifespan). Module-level `create_task` causes "attached to a different loop" errors.
- **Using `asyncio.TaskGroup` for the broadcaster:** TaskGroup is for bounded fan-out that finishes. The broadcaster is an infinite loop -- use bare `create_task` with lifespan cancellation.
- **Catching `CancelledError` inside the broadcast loop:** Let `CancelledError` propagate so the lifespan teardown can cleanly stop the task. Only catch `Exception` (not `BaseException`) for tick-level error recovery.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Per-client queue management | Custom queue registry | `ConnectionManager` (Phase 29) | Already handles bounded queues, drop-oldest, writer tasks, disconnect cleanup |
| WebSocket accept/send | Raw ASGI WebSocket handling | FastAPI `@router.websocket` + Starlette `WebSocket` | Handles protocol negotiation, encoding, exception typing |
| JSON serialization of dataclasses | Custom encoder for enums/nested types | `dataclasses.asdict()` + `json.dumps()` | `str, Enum` subclasses serialize as string values natively (verified) |
| Background task lifecycle | Custom signal handling or atexit hooks | FastAPI lifespan + `asyncio.Task.cancel()` | Lifespan teardown is the canonical ASGI shutdown hook |

**Key insight:** Phase 29 did the heavy lifting (ConnectionManager, non-destructive snapshot, drain_rationales). Phase 30 is primarily wiring -- two new files, two file modifications, and tests.

## Common Pitfalls

### Pitfall 1: Blocking the Event Loop with json.dumps on Large Payloads
**What goes wrong:** If the snapshot payload grows very large, `json.dumps` on the main loop could introduce latency.
**Why it happens:** `json.dumps` is CPU-bound and runs synchronously.
**How to avoid:** At 7.3 KB per full snapshot, `json.dumps` takes microseconds. This is a non-issue at current scale. If payload ever exceeds ~1MB, move serialization to `loop.run_in_executor()`.
**Warning signs:** Broadcaster tick drift beyond 250ms.

### Pitfall 2: Catching CancelledError in the Broadcast Loop
**What goes wrong:** If `except BaseException` or `except asyncio.CancelledError` is caught inside the loop body, the lifespan teardown's `task.cancel()` silently fails and the task never stops.
**Why it happens:** `CancelledError` is a BaseException in Python 3.9+; catching it suppresses cancellation.
**How to avoid:** Use `except Exception` (not `BaseException`) inside the loop. Let `CancelledError` propagate naturally to the `await asyncio.sleep(0.2)` call, which will raise it.
**Warning signs:** Server hangs on shutdown; "Task was destroyed but it is pending" warnings.

### Pitfall 3: WebSocket Endpoint Not Detecting Disconnects
**What goes wrong:** Without a receive loop, the server has no way to detect that a client disconnected. The writer task keeps trying to send and eventually errors.
**Why it happens:** WebSocket disconnect is detected when the next `receive_*()` call raises `WebSocketDisconnect`.
**How to avoid:** Always include a `while True: await ws.receive_text()` loop in the endpoint, even for server-push-only patterns. The loop exists solely for disconnect detection.
**Warning signs:** Error logs about writing to closed WebSocket; resource leaks in ConnectionManager.

### Pitfall 4: Forgetting to Cancel Broadcaster in Lifespan Teardown
**What goes wrong:** The broadcaster task continues running after the app shuts down, holding references to closed resources.
**Why it happens:** `asyncio.create_task` tasks are fire-and-forget unless explicitly cancelled.
**How to avoid:** Store the task on `app.state.broadcaster_task` and cancel it in the lifespan teardown before closing other resources (like graph_manager).
**Warning signs:** "Event loop is closed" errors during shutdown.

### Pitfall 5: Race Between drain_rationales and Multiple Consumers
**What goes wrong:** If both the TUI and the WebSocket broadcaster call `drain_rationales()`, entries could be split between them non-deterministically.
**Why it happens:** `drain_rationales()` is destructive -- it pops from the queue.
**How to avoid:** Per CONTEXT.md D-04, the WebSocket broadcaster owns the rationale drain from this phase forward. The TUI's call site remains but becomes moot as the TUI is phased out. In practice both can coexist since the TUI is only active when the web server is not (different entry points: `alphaswarm tui` vs `alphaswarm web`).
**Warning signs:** Missing rationale entries in the WebSocket stream when TUI is also running (should not happen in normal usage).

## Code Examples

Verified patterns from official sources and project codebase:

### Lifespan Integration (app.py modification)
```python
# Source: existing app.py lifespan pattern
from alphaswarm.web.broadcaster import start_broadcaster

# Inside lifespan(), after connection_manager creation:
broadcaster_task = start_broadcaster(app_state.state_store, connection_manager)
app.state.broadcaster_task = broadcaster_task

# In teardown (before graph_manager.close()):
broadcaster_task.cancel()
try:
    await broadcaster_task
except asyncio.CancelledError:
    pass
```

### create_app Router Registration
```python
# Source: existing create_app() pattern; D-08 says no prefix for WebSocket routes
from alphaswarm.web.routes.websocket import router as ws_router

# In create_app():
app.include_router(ws_router)  # No prefix -- /ws/state is the full path
```

### TestClient WebSocket Test Pattern
```python
# Source: Starlette TestClient docs + existing test_web.py patterns
def test_ws_state_receives_snapshot() -> None:
    """Connecting to /ws/state receives JSON snapshot data."""
    app = _make_test_app()  # Must include ws_router
    with TestClient(app) as client:
        with client.websocket_connect("/ws/state") as ws:
            data = ws.receive_text()
            parsed = json.loads(data)
            assert "phase" in parsed
            assert "agent_states" in parsed
            assert "rationale_entries" in parsed
```

### WebSocket Endpoint with Request Access
```python
# Source: FastAPI docs -- WebSocket endpoints access app.state via websocket.app.state
# Note: FastAPI WebSocket handlers receive the WebSocket object, not Request
@router.websocket("/ws/state")
async def ws_state(websocket: WebSocket) -> None:
    connection_manager = websocket.app.state.connection_manager
    # ... rest of handler
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Server-Sent Events (SSE) | WebSocket for bidirectional capability | N/A (design decision) | WebSocket chosen for Phase 35 interview streaming compatibility |
| Pydantic `.model_dump_json()` | `dataclasses.asdict()` + `json.dumps()` | Phase 30 decision D-05 | Defers Pydantic wire models to Phase 31; simpler for now |
| Polling REST endpoint | WebSocket push at 5Hz | v5.0 architecture | Eliminates polling overhead; frontend gets consistent tick rate |

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 + pytest-asyncio 1.3.0 |
| Config file | `pyproject.toml` [tool.pytest.ini_options] |
| Quick run command | `uv run pytest tests/test_web.py -x -q` |
| Full suite command | `uv run pytest tests/ -x -q` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| BE-04 (SC-1) | /ws/state produces JSON snapshots at ~200ms intervals | integration | `uv run pytest tests/test_web.py::test_ws_state_receives_snapshot -x` | Wave 0 |
| BE-04 (SC-2) | Slow client does not block other clients (bounded queue + drop-oldest) | unit | `uv run pytest tests/test_web.py::test_websocket_queue_isolation -x` | Already exists (Phase 29) |
| BE-04 (SC-3) | Disconnect cleanly removes writer task, no error logs or leaks | unit | `uv run pytest tests/test_web.py::test_ws_state_disconnect_cleanup -x` | Wave 0 |
| BE-04 | snapshot_to_json returns valid JSON with all required fields | unit | `uv run pytest tests/test_web.py::test_snapshot_to_json -x` | Wave 0 |
| BE-04 | Broadcaster task cancellation in lifespan teardown | unit | `uv run pytest tests/test_web.py::test_broadcaster_cancellation -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_web.py -x -q`
- **Per wave merge:** `uv run pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_web.py::test_ws_state_receives_snapshot` -- covers SC-1 (WebSocket stream produces JSON)
- [ ] `tests/test_web.py::test_ws_state_disconnect_cleanup` -- covers SC-3 (clean disconnect)
- [ ] `tests/test_web.py::test_snapshot_to_json` -- covers snapshot serialization helper
- [ ] `tests/test_web.py::test_broadcaster_cancellation` -- covers lifespan teardown
- [ ] `_make_test_app()` update -- include `ws_router` in test app factory

## Open Questions

1. **WebSocket endpoint access to app.state**
   - What we know: In FastAPI, WebSocket endpoints access app state via `websocket.app.state`, not via a `Request` parameter. The `WebSocket` object has an `.app` attribute from Starlette's ASGI scope.
   - What's unclear: Nothing -- this is well-documented behavior.
   - Recommendation: Use `websocket.app.state.connection_manager` in the endpoint handler.

2. **TestClient WebSocket timing for broadcast receipt**
   - What we know: Starlette's `TestClient.websocket_connect()` is synchronous and blocking. The broadcaster task runs as a background coroutine inside the ASGI event loop.
   - What's unclear: Whether `ws.receive_text()` in the test will reliably receive the broadcast within a reasonable timeout, or if the TestClient's synchronous nature could cause timing issues.
   - Recommendation: The TestClient runs its own event loop internally. The broadcaster task will be created by the lifespan and will tick at 200ms. Calling `ws.receive_text()` should block the test thread until data arrives. If timing is flaky, add a small retry or increase the test timeout. Alternatively, test `snapshot_to_json()` as a pure unit test and test the WebSocket endpoint with a manually triggered broadcast (mock or direct `connection_manager.broadcast()` call).

## Sources

### Primary (HIGH confidence)
- `src/alphaswarm/web/connection_manager.py` -- full ConnectionManager implementation read and analyzed
- `src/alphaswarm/web/app.py` -- lifespan pattern, create_app router registration
- `src/alphaswarm/state.py` -- StateStore.snapshot(), drain_rationales(), all dataclass definitions
- `src/alphaswarm/types.py` -- SignalType(str, Enum), SimulationPhase(str, Enum)
- `tests/test_web.py` -- _make_test_app() helper, existing Phase 29 test patterns
- Runtime verification: `dataclasses.asdict()` + `json.dumps()` on full 100-agent snapshot produces 7.3 KB valid JSON

### Secondary (MEDIUM confidence)
- [FastAPI WebSocket docs](https://fastapi.tiangolo.com/advanced/websockets/) -- WebSocketDisconnect pattern, receive_text loop
- [Starlette TestClient docs](https://www.starlette.io/testclient/) -- websocket_connect() context manager, send/receive methods

### Tertiary (LOW confidence)
- None

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all libraries already installed and verified; no new dependencies
- Architecture: HIGH -- all decisions locked in CONTEXT.md; Phase 29 infrastructure fully read and understood
- Pitfalls: HIGH -- verified against actual codebase (CancelledError behavior, json.dumps performance, drain_rationales ownership)
- Serialization: HIGH -- verified via runtime test that full 100-agent snapshot serializes to valid 7.3 KB JSON

**Research date:** 2026-04-12
**Valid until:** 2026-05-12 (stable domain -- stdlib asyncio + FastAPI WebSocket patterns)
