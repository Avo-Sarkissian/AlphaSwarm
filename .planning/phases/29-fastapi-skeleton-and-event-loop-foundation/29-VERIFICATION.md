---
phase: 29-fastapi-skeleton-and-event-loop-foundation
verified: 2026-04-13T02:30:00Z
status: gaps_found
score: 2/4 must-haves verified
re_verification: false
gaps:
  - truth: "StateStore.snapshot() can be called multiple times without losing rationale entries (non-destructive reads verified by test)"
    status: failed
    reason: "state.py still has OLD destructive snapshot() that drains up to 5 entries per call. drain_rationales() method does not exist. Confirmed by direct Python execution: snap1 drains the entry, snap2 is empty."
    artifacts:
      - path: "src/alphaswarm/state.py"
        issue: "snapshot() at line 191 still contains the _rationale_queue.get_nowait() drain loop (lines 200-205). rationale_entries=tuple(entries) is returned with drained data, not ()."
      - path: "tests/test_state.py"
        issue: "test_rationale_queue_drain (line 125) still asserts snap1 returns 5 entries and snap2 returns 2 (old destructive behavior). test_snapshot_non_destructive and test_drain_rationales do not exist. test_push_top_rationales_sorts_by_influence (line 279) and test_push_top_rationales_skips_parse_errors (line 299) still call store.snapshot() and assert rationale_entries has entries."
      - path: "src/alphaswarm/tui.py"
        issue: "_poll_snapshot at line 1366 still reads 'snapshot.rationale_entries' — not drain_rationales(5). No call to drain_rationales anywhere in tui.py."
    missing:
      - "Refactor StateStore.snapshot() in state.py to set rationale_entries=() (remove drain loop at lines 200-205)"
      - "Add drain_rationales(limit=5) method to StateStore in state.py after snapshot()"
      - "Update tui.py _poll_snapshot (line 1366) to call state_store.drain_rationales(5) instead of snapshot.rationale_entries"
      - "Update test_state.py: rewrite test_rationale_queue_drain and test_snapshot_drain_queue_twice to use drain_rationales(); add test_snapshot_non_destructive, test_drain_rationales, test_drain_rationales_tui_compat; fix test_push_top_rationales tests to use drain_rationales()"

  - truth: "POST /api/simulate/start while a simulation is already running returns HTTP 409"
    status: failed
    reason: "No POST /api/simulate/start HTTP endpoint exists anywhere in the web package. SimulationManager has the 409 guard logic (SimulationAlreadyRunningError), but no route exposes it via HTTP. The HTTP 409 response is the stated success criterion, not just the Python exception."
    artifacts:
      - path: "src/alphaswarm/web/routes/"
        issue: "Only health.py exists. No simulation routes file. No POST /api/simulate/start endpoint registered."
    missing:
      - "Create src/alphaswarm/web/routes/simulation.py with POST /api/simulate/start route that catches SimulationAlreadyRunningError and returns HTTP 409"
      - "Register simulation router in app.py: app.include_router(simulation_router, prefix='/api')"
      - "Add test asserting HTTP 409 response when start called while running"

human_verification:
  - test: "Run alphaswarm web, then send POST /api/simulate/start twice in rapid succession"
    expected: "Second request receives HTTP 409 with meaningful error body"
    why_human: "Server must be running; POST /api/simulate/start endpoint does not exist yet"
---

# Phase 29: FastAPI Skeleton and Event Loop Foundation — Verification Report

**Phase Goal:** Uvicorn owns the asyncio event loop and all simulation infrastructure (StateStore, Governor, Neo4j driver) is created inside the FastAPI lifespan context so downstream phases have a correct single-loop foundation

**Verified:** 2026-04-13T02:30:00Z
**Status:** gaps_found
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths (from ROADMAP.md Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|---------|
| 1 | Running `alphaswarm web` starts a Uvicorn server and GET /api/health returns 200 with simulation phase and memory stats | VERIFIED | `alphaswarm web --help` shows --host/--port. TestClient GET /api/health returns 200 with `{"status":"ok","simulation_phase":"idle","memory_percent":53.6,"is_simulation_running":false}`. CLI wired at cli.py:824. |
| 2 | StateStore.snapshot() can be called multiple times without losing rationale entries (non-destructive reads verified by test) | FAILED | state.py snapshot() still has destructive drain loop (lines 200-205). Direct test: push 1 entry, snap1.rationale_entries=(entry,), snap2.rationale_entries=(). drain_rationales() method does not exist. Tests in test_state.py still assert old destructive behavior. |
| 3 | A second WebSocket client connecting does not drain rationale entries that the first client should have received (per-client queue isolation) | VERIFIED | ConnectionManager._clients uses per-client asyncio.Queue. broadcast() iterates all queues with put_nowait. Verified: q1 drained, q2 unaffected. test_websocket_queue_isolation passes. |
| 4 | POST /api/simulate/start while a simulation is already running returns HTTP 409 | FAILED | No POST /api/simulate/start HTTP endpoint exists. Only src/alphaswarm/web/routes/health.py exists. SimulationManager has SimulationAlreadyRunningError guard logic but it is not exposed via any HTTP route. |

**Score:** 2/4 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/alphaswarm/web/__init__.py` | Package init exporting create_app | VERIFIED | Exists, exports create_app, __all__ correct |
| `src/alphaswarm/web/app.py` | FastAPI factory + lifespan | VERIFIED | lifespan creates all objects inside event loop; all stored on app.state; include_router wired |
| `src/alphaswarm/web/routes/health.py` | GET /api/health endpoint | VERIFIED | HealthResponse model with 4 required fields; request.app.state.app_state and sim_manager accessed correctly |
| `src/alphaswarm/web/simulation_manager.py` | SimulationManager + 409 guard | VERIFIED (class only) | SimulationAlreadyRunningError exists; asyncio.Lock guard in start(); is_running property present |
| `src/alphaswarm/web/connection_manager.py` | Per-client queue ConnectionManager | VERIFIED | asyncio.Queue(maxsize=100) per client; drop-oldest broadcast; disconnect() cancels task |
| `tests/test_web.py` | 6 tests | VERIFIED | 6 tests pass; covers health, lifespan, 409 guard (Python level), queue isolation, overflow, disconnect |
| `src/alphaswarm/state.py` | Non-destructive snapshot() + drain_rationales() | FAILED | snapshot() still destructive; drain_rationales() does not exist |
| `tests/test_state.py` | Updated drain tests + 3 new non-destructive snapshot tests | FAILED | test_rationale_queue_drain still asserts old destructive behavior; test_snapshot_non_destructive absent; test_drain_rationales absent |
| `src/alphaswarm/tui.py` | _poll_snapshot calls drain_rationales(5) | FAILED | Line 1366 reads snapshot.rationale_entries; no drain_rationales call anywhere in tui.py |
| `src/alphaswarm/web/routes/simulation.py` | POST /api/simulate/start | MISSING | File does not exist; no simulation route registered |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `src/alphaswarm/web/app.py` | `src/alphaswarm/app.py` | create_app_state() in lifespan | WIRED | Line 32: `app_state = create_app_state(settings, personas, with_ollama=True, with_neo4j=True)` |
| `src/alphaswarm/web/app.py` | `src/alphaswarm/web/routes/health.py` | app.include_router(health_router) | WIRED | Line 58: `app.include_router(health_router, prefix="/api")` |
| `src/alphaswarm/web/routes/health.py` | `src/alphaswarm/web/app.py` | request.app.state.app_state | WIRED | Lines 27-28: accesses app_state and sim_manager from request.app.state |
| `src/alphaswarm/web/app.py` | `src/alphaswarm/web/simulation_manager.py` | SimulationManager in lifespan | WIRED | Line 33: `sim_manager = SimulationManager(app_state)` stored on app.state |
| `src/alphaswarm/web/app.py` | `src/alphaswarm/web/connection_manager.py` | ConnectionManager in lifespan | WIRED | Line 34: `connection_manager = ConnectionManager()` stored on app.state |
| `src/alphaswarm/cli.py` | `src/alphaswarm/web/__init__.py` | _handle_web imports create_app | WIRED | Line 833: `from alphaswarm.web import create_app` inside _handle_web |
| `src/alphaswarm/cli.py` | `uvicorn` | uvicorn.run(create_app()) | WIRED | Line 835: `uvicorn.run(create_app(), host=host, port=port)` |
| `src/alphaswarm/tui.py` | `src/alphaswarm/state.py` | drain_rationales(5) in _poll_snapshot | NOT_WIRED | tui.py still reads snapshot.rationale_entries at line 1366; drain_rationales never called |

---

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `routes/health.py` | simulation_phase | state_store.snapshot().phase | Yes — StateStore._phase set by simulation | FLOWING |
| `routes/health.py` | memory_percent | psutil.virtual_memory().percent | Yes — live system call | FLOWING |
| `routes/health.py` | is_simulation_running | sim_manager.is_running | Yes — reflects SimulationManager._is_running | FLOWING |

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| alphaswarm web --help shows correct flags | `uv run python -m alphaswarm web --help` | Shows --host (default 127.0.0.1) and --port (default 8000) | PASS |
| GET /api/health returns 200 with 4 required fields | TestClient get /api/health | `{"status":"ok","simulation_phase":"idle","memory_percent":53.6,"is_simulation_running":false}` | PASS |
| StateStore.snapshot() is non-destructive | Push 1 entry, call snapshot() twice | snap1 has 1 entry, snap2 empty — DESTRUCTIVE behavior confirmed | FAIL |
| drain_rationales() method exists | `hasattr(StateStore(), 'drain_rationales')` | False | FAIL |
| SimulationManager 409 guard (Python level) | Acquire lock, call start() | SimulationAlreadyRunningError raised | PASS |
| Per-client queue isolation | broadcast() to 2 queues, drain 1 | q2 unaffected | PASS |
| POST /api/simulate/start exists | grep for endpoint in web/routes/ | No endpoint found | FAIL |
| All state tests pass | `uv run pytest tests/test_state.py` | 28 passed (but tests still assert OLD destructive behavior) | NOTE: Tests pass because state.py was NOT refactored |
| All web tests pass | `uv run pytest tests/test_web.py` | 6 passed | PASS |

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|---------|
| BE-01 | 29-02, 29-03 | FastAPI app factory with Uvicorn lifespan owning event loop; CLI web subcommand | SATISFIED | app.py lifespan wired; cli.py _handle_web; health endpoint returns 200 |
| BE-02 | 29-01 | Non-destructive StateStore.snapshot() | NOT SATISFIED | state.py snapshot() still destructive; drain_rationales() absent; tests still test old behavior |
| BE-03 | 29-02 | Per-client WebSocket queue with bounded drop-oldest policy | PARTIALLY SATISFIED | ConnectionManager architecture is correct and tested; but HTTP endpoint exposing 409 is missing |

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `src/alphaswarm/web/simulation_manager.py` | 49-50 | `# Phase 32: wire actual simulation call here; pass` | Warning | Acknowledged stub for Phase 32; does not block SC-1, SC-3 |
| `src/alphaswarm/web/simulation_manager.py` | 54-56 | `def stop(self) -> None: pass` | Warning | Acknowledged stub for Phase 32 |
| `src/alphaswarm/state.py` | 196-198 | Docstring still describes old drain side-effect ("Side effect: drains up to 5 rationale entries") | Blocker | Confirms snapshot() was NOT refactored — docstring is accurate to the still-destructive implementation |
| `tests/test_state.py` | 125-135 | test_rationale_queue_drain asserts snap1 has 5 entries, snap2 has 2 — old destructive semantics | Blocker | Tests pass because state.py was not refactored, but they contradict Plan 01's stated goal |

---

### Human Verification Required

#### 1. POST /api/simulate/start HTTP 409

**Test:** Start the server with `alphaswarm web`, send two rapid POST /api/simulate/start requests
**Expected:** Second request receives HTTP 409 with a meaningful error body
**Why human:** Server must be running; this endpoint does not exist so it would return 404 currently

---

## Gaps Summary

Phase 29 delivered SC-1 (health endpoint + CLI) and SC-3 (per-client WebSocket queue isolation) fully and correctly. The web package scaffold, ConnectionManager, SimulationManager, and CLI entry point are all well-implemented and tested.

**Two success criteria were not achieved:**

**SC-2 (non-destructive snapshot):** The Plan 01 SUMMARY claims `StateStore.snapshot()` was refactored to be non-destructive and `drain_rationales()` was added — but the actual `state.py` still contains the old destructive drain loop (lines 200-205). `drain_rationales()` does not exist. `tui.py` still reads `snapshot.rationale_entries` at line 1366. The test file still tests the old destructive behavior. The SUMMARY documents what was INTENDED but the code changes were never committed (or were lost/overwritten). 28 state tests pass only because the old code is still present.

**SC-4 (HTTP 409):** The ROADMAP Success Criterion specifies "POST /api/simulate/start... returns HTTP 409" as an HTTP-level behavior. The `SimulationManager` class has the correct guard logic, and the test validates the Python exception, but no HTTP route (`POST /api/simulate/start`) exists. The endpoint is deferred to Phase 32 per the SUMMARY's "Known Stubs" section — but the ROADMAP assigns this criterion to Phase 29, not Phase 32.

**Root cause for SC-2:** The commits b643470, 4399652, 0a8774d are listed in the SUMMARY but a merge from the worktree (commit ca7a75c "merge executor worktree") likely overwrote or lost the state.py and tui.py and test_state.py changes from the Plan 01 work. The pyproject.toml fastapi/uvicorn deps (from Plan 01 and Plan 03 both claim credit) are present, suggesting a partial merge.

---

_Verified: 2026-04-13T02:30:00Z_
_Verifier: Claude (gsd-verifier)_
