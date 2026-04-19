---
phase: 35-agent-interviews-web-ui
plan: "01"
subsystem: web-api
tags: [fastapi, interview, websocket, neo4j, ollama, tdd]
dependency_graph:
  requires:
    - src/alphaswarm/interview.py (InterviewEngine, InterviewContext)
    - src/alphaswarm/graph.py (read_agent_interview_context, read_completed_cycles)
    - src/alphaswarm/types.py (SimulationPhase.COMPLETE)
    - src/alphaswarm/web/app.py (lifespan, create_app)
    - src/alphaswarm/web/simulation_manager.py (SimulationManager.start)
  provides:
    - POST /api/interview/{agent_id} REST endpoint
    - app.state.interview_sessions session store
    - SimulationManager.on_start hook for session cleanup
  affects:
    - src/alphaswarm/web/app.py (new import, lifespan init, router registration)
    - src/alphaswarm/web/simulation_manager.py (on_start callback param)
    - tests/test_web.py (interview_router added, interview_sessions in lifespan)
tech_stack:
  added: []
  patterns:
    - TDD (RED then GREEN): test scaffolds committed before implementation
    - Per-agent asyncio.Lock for concurrent request serialization
    - Lazy session creation with dict keyed by agent_id
    - on_start dependency-injection callback on SimulationManager
    - Approach A session cleanup (callable injection, not direct app.state access)
key_files:
  created:
    - src/alphaswarm/web/routes/interview.py
    - tests/test_web_interview.py
  modified:
    - src/alphaswarm/web/app.py
    - src/alphaswarm/web/simulation_manager.py
    - tests/test_web.py
decisions:
  - "Approach A (on_start callable injection) chosen over Approach B (direct app.state access) — cleaner, testable, avoids tight coupling between SimulationManager and FastAPI app internals"
  - "interview_sessions initialized before SimulationManager in lifespan so lambda closure captures the dict before first use"
  - "Per-agent asyncio.Lock stored alongside engine in sessions dict rather than a global lock — prevents serializing across different agents"
metrics:
  duration: "4 minutes"
  completed_date: "2026-04-15"
  tasks_completed: 2
  files_changed: 5
---

# Phase 35 Plan 01: Interview Backend REST Endpoint Summary

**One-liner:** FastAPI POST /api/interview/{agent_id} with phase guard (409), service guard (503), per-agent asyncio.Lock, lazy InterviewEngine session creation, and on_start session cleanup via SimulationManager callback.

## What Was Built

A new `src/alphaswarm/web/routes/interview.py` route file providing:

- `POST /api/interview/{agent_id}` — accepts `{"message": "..."}` (1–4000 chars), returns `{"response": "..."}` from the agent's InterviewEngine
- **Phase guard**: 409 `interview_unavailable` when `state_store.snapshot().phase != COMPLETE`
- **Service guard**: 503 `services_unavailable` when `graph_manager` or `ollama_client` is None
- **Session lifecycle**: First call per agent creates InterviewEngine from Neo4j context; subsequent calls reuse the cached engine from `app.state.interview_sessions`
- **Concurrency safety**: Per-agent `asyncio.Lock` wraps `engine.ask()` to prevent concurrent history mutation
- **Session cleanup**: `SimulationManager.on_start` callback (`lambda: app.state.interview_sessions.clear()`) fires before every new simulation run

## Tasks

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Wave 0 test scaffolds (RED) | c57f032 | tests/test_web_interview.py, tests/test_web.py |
| 2 | Interview route + wiring (GREEN) | 614c54e | src/alphaswarm/web/routes/interview.py, app.py, simulation_manager.py, tests/test_web_interview.py |

## Verification

All plan verification checks pass:

1. `uv run pytest tests/test_web_interview.py -x -q` — 13 passed
2. `uv run pytest tests/test_web.py -x -q` — 39 passed
3. `grep -c "^def test_\|^async def test_" tests/test_web_interview.py` — returns 13
4. `grep "interview_router" src/alphaswarm/web/app.py` — shows import and registration
5. `grep "interview_sessions" src/alphaswarm/web/app.py` — shows lifespan initialization
6. `grep -n "interview_sessions\|_on_start" src/alphaswarm/web/simulation_manager.py` — shows cleanup hook
7. `grep -n "asyncio.Lock\|async with lock" src/alphaswarm/web/routes/interview.py` — shows per-agent lock
8. `grep -n "SimulationPhase.COMPLETE\|interview_unavailable" src/alphaswarm/web/routes/interview.py` — shows phase guard
9. `grep -n "min_length=1, max_length=4000" src/alphaswarm/web/routes/interview.py` — shows request validation

## Deviations from Plan

### Auto-fixed Issues

None — plan executed exactly as written with the following implementation choice:

**Approach A selected** (per plan recommendation): `SimulationManager.__init__` accepts `on_start: Callable[[], None] | None = None`. The `app.py` lifespan passes `on_start=lambda: app.state.interview_sessions.clear()`. This required updating `_make_interview_test_app()` in `test_web_interview.py` to also pass the callback, making the test app's behavior match production.

The test file had 13 tests (plan specified 12 minimum — the production route registration test was written as the 13th, still within the `min_lines: 180` constraint).

## Known Stubs

None — all endpoint logic is fully implemented. The endpoint correctly delegates to the existing `InterviewEngine.ask()` and Neo4j graph reader methods. No hardcoded responses or placeholders.

## Self-Check: PASSED

Files exist:
- [x] `src/alphaswarm/web/routes/interview.py` — FOUND
- [x] `tests/test_web_interview.py` — FOUND

Commits exist:
- [x] `c57f032` — FOUND (test scaffolds)
- [x] `614c54e` — FOUND (implementation)
