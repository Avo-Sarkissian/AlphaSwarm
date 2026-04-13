# Phase 30: WebSocket State Stream - Context

**Gathered:** 2026-04-12
**Status:** Ready for planning

<domain>
## Phase Boundary

Wire the 5Hz WebSocket broadcaster: add a `/ws/state` endpoint that registers clients with the Phase 29 `ConnectionManager`, launch an always-on `asyncio.Task` in the lifespan that calls `state_store.snapshot()` + `drain_rationales(5)` every 200ms and calls `connection_manager.broadcast()`, and serialize the full `StateSnapshot` payload as JSON. The Phase 29 ConnectionManager (per-client bounded queues, drop-oldest policy, writer tasks, clean disconnect) is already built — this phase wires the broadcast loop and the endpoint.

The Vue frontend (Phase 31), REST controls (Phase 32), and monitoring panels (Phase 33) are out of scope.

</domain>

<decisions>
## Implementation Decisions

### Broadcaster lifecycle
- **D-01:** The broadcaster runs as an always-on `asyncio.Task` started inside the FastAPI lifespan. It ticks at 200ms (5Hz) from server start, even during `SimulationPhase.IDLE`. IDLE snapshots are cheap (empty `agent_states`, no rationale entries) and let the Vue frontend show a "waiting" state without extra logic.
- **D-02:** The broadcaster task is cancelled in the lifespan teardown (alongside graph_manager close). No start/stop wiring with `SimulationManager`.

### Snapshot payload
- **D-03:** Each broadcast includes the **full `StateSnapshot`**: `phase`, `round_num`, `elapsed_seconds`, `agent_states` (all 100 agents), `bracket_summaries` (10 brackets), `governor_metrics`, `tps`, and `rationale_entries`. This ensures Phases 31–33 have everything they need from the stream without additional REST polling.
- **D-04:** Rationale entries are included — the broadcaster calls `drain_rationales(5)` each tick and injects the result into the payload. The WebSocket broadcaster owns the rationale drain from this phase forward; the TUI's `drain_rationales()` call site remains but will be rendered moot as the TUI is phased out in v5.0.

### JSON serialization
- **D-05:** `json.dumps(dataclasses.asdict(snapshot_with_rationales))` — no new Pydantic wire model needed this phase. `SignalType` is `str, Enum` so Python's JSON encoder serializes it as its string value. Explicit Pydantic schema deferred to Phase 31 when the Vue frontend exercises the contract.
- **D-06:** A helper `snapshot_to_json(state_store: StateStore) -> str` in `web/broadcaster.py` encapsulates the `snapshot()` + `drain_rationales()` + `asdict()` + `json.dumps()` pipeline. The broadcaster loop calls this helper.

### Broadcast loop location
- **D-07:** New module `web/broadcaster.py` exports `start_broadcaster(state_store, connection_manager) -> asyncio.Task`. The lifespan calls this and stores the task on `app.state.broadcaster_task` for cancellation on shutdown.
- **D-08:** New router `web/routes/websocket.py` with a single `@router.websocket("/ws/state")` endpoint. Registered in `create_app()` without a prefix (WebSocket routes use full paths).

### WebSocket endpoint behavior
- **D-09:** The `/ws/state` handler calls `connection_manager.connect(ws)` then enters a receive loop (`await ws.receive_text()` or `receive_bytes()`) to detect client disconnects. On `WebSocketDisconnect` or any exception, calls `connection_manager.disconnect(ws)` in a `finally` block. This is the FastAPI standard pattern and satisfies SC-3 (clean disconnect, no error logs).
- **D-10:** The endpoint is unauthenticated — local dev only, no auth headers needed.

### Claude's Discretion
- Exact `asyncio.sleep(0.2)` vs `asyncio.wait_for` timing in the broadcast loop
- Whether the receive loop uses `receive_text()` or `receive_bytes()` (both detect disconnect)
- Error handling for serialization failures (log + skip tick)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 30 requirements
- `.planning/ROADMAP.md` §"Phase 30: WebSocket State Stream" — goal, success criteria SC-1/SC-2/SC-3, BE-04 requirement tag

### Existing Phase 29 infrastructure (must read before implementing)
- `src/alphaswarm/web/connection_manager.py` — `ConnectionManager.connect()`, `disconnect()`, `broadcast()`, `_writer()` — all already implemented, do NOT re-implement
- `src/alphaswarm/web/app.py` — `lifespan()` function — broadcaster task must be started here and stored on `app.state`; teardown must cancel it
- `src/alphaswarm/state.py` — `StateStore.snapshot()` (non-destructive) and `drain_rationales(limit)` — the two methods the broadcaster calls each tick
- `src/alphaswarm/web/routes/health.py` — pattern for router file structure and registration in `create_app()`
- `src/alphaswarm/web/routes/simulation.py` — pattern for route file with Pydantic request/response models

### Types for serialization
- `src/alphaswarm/state.py` — `StateSnapshot`, `AgentState`, `BracketSummary`, `RationaleEntry`, `GovernorMetrics` dataclasses — these are what `dataclasses.asdict()` will flatten

### Test patterns
- `tests/test_web.py` — `_make_test_app()` helper and Phase 29 test structure — new tests for Phase 30 extend this file

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `ConnectionManager.broadcast(message: str)` — already implemented with drop-oldest queue policy; Phase 30 only needs to call it with the serialized JSON string
- `ConnectionManager.connect(ws)` / `disconnect(ws)` — full lifecycle already implemented; WebSocket endpoint just calls these
- `StateStore.snapshot()` + `drain_rationales(5)` — Phase 29 D-06 explicitly designed these for the broadcaster to call; no changes to `state.py` needed
- `_make_test_app()` in `tests/test_web.py` — reusable for Phase 30 tests (add WebSocket route to the test app factory)

### Established Patterns
- **Router-per-domain (D-02 from Phase 29):** New `routes/websocket.py` with `APIRouter()`, registered in `create_app()` — do not add WebSocket to existing route files
- **Lifespan owns all stateful objects:** Broadcaster task stored on `app.state.broadcaster_task`, cancelled in teardown — same pattern as `graph_manager.close()` in teardown
- **structlog component naming:** `structlog.get_logger(component="web.broadcaster")` and `component="web.ws_state"`
- **asyncio.Queue + drop-oldest:** Already in ConnectionManager; broadcaster does not need its own queue

### Integration Points
- `web/app.py` lifespan — add `broadcaster_task = start_broadcaster(app_state.state_store, connection_manager)` after `connection_manager` creation; cancel in teardown
- `web/app.py` `create_app()` — `app.include_router(ws_router)` without prefix (WebSocket paths are absolute)
- `tests/test_web.py` `_make_test_app()` — import and include `ws_router` so WebSocket tests can use `TestClient`'s WebSocket support

</code_context>

<specifics>
## Specific Ideas

- Phase 29 D-06 explicitly states: broadcaster calls `drain_rationales()` — this is the confirmed design, not an open question.
- The "5Hz" rate in the roadmap goal means `asyncio.sleep(0.2)` in the broadcast loop.
- The success criteria phrase "approximately 200ms intervals" gives tolerance — exact timing is up to the asyncio scheduler.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 30-websocket-state-stream*
*Context gathered: 2026-04-12*
