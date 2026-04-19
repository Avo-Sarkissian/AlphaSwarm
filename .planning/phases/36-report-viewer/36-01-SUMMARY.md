---
phase: 36-report-viewer
plan: 01
subsystem: web-backend
tags: [report, react, fastapi, background-task, async-io, done-callback, security]
dependency-graph:
  requires:
    - "src/alphaswarm/report.py — Phase 15 ReportEngine/ReportAssembler/write_report/write_sentinel reused unmodified"
    - "src/alphaswarm/cli.py _handle_report — canonical generation sequence that the background task mirrors"
    - "src/alphaswarm/types.py SimulationPhase — COMPLETE guard (D-01)"
    - "src/alphaswarm/web/app.py lifespan — existing pattern for router registration and app.state init"
  provides:
    - "GET /api/report/{cycle_id} — polling target for Vue ReportViewer (Plan 02)"
    - "POST /api/report/{cycle_id}/generate — 202 Accepted spawn of ReACT pipeline"
    - "_run_report_generation async coroutine — CLI-parity background pipeline"
    - "_on_report_task_done done_callback — surfaces background failures to frontend via app.state.report_generation_error"
  affects:
    - "src/alphaswarm/web/app.py — lifespan now initializes app.state.report_task and app.state.report_generation_error"
    - "tests/test_web.py _make_test_app — report_router + lifespan dicts added so existing web tests co-exist with the new router"
tech-stack:
  added: []
  patterns:
    - "Regex-bound path parameter validation (T-36-01) before Path construction"
    - "asyncio.Task.add_done_callback to capture background failures (T-36-15)"
    - "aiofiles.os.path.exists / aiofiles.os.stat for non-blocking filesystem probes (T-36-14)"
    - "finally-block model unload that never raises (Common Pitfalls)"
    - "State-machine error surface (app.state.report_generation_error[cycle_id]) so GET can stop frontend polling on background failure"
key-files:
  created:
    - "src/alphaswarm/web/routes/report.py"
    - "tests/test_web_report.py"
  modified:
    - "src/alphaswarm/web/app.py"
    - "tests/test_web.py"
decisions:
  - "Mock helpers for the test app run INSIDE the TestClient context so app.state.app_state is available after lifespan startup (divergence from interview-test pattern, but required because our POST path reads app_state earlier)."
  - "aiofiles import-untyped errors suppressed with # type: ignore on the two new imports rather than adding types-aiofiles repo-wide — keeps the patch surface minimal; pre-existing untyped import in src/alphaswarm/report.py remains out-of-scope."
  - "Background task uses local `assert model_manager is not None` narrowing (safe: POST handler validates before scheduling) to keep mypy strict on the new module without sprinkling type ignores."
metrics:
  duration-minutes: 7
  duration-pretty: "~7 minutes"
  tasks: 2
  completed: "2026-04-17"
---

# Phase 36 Plan 01: report-viewer-backend Summary

One-liner: FastAPI report route with two endpoints — GET read-through with non-blocking aiofiles.os filesystem probes, and POST that spawns the CLI ReACT generation pipeline as an asyncio.Task with an add_done_callback that surfaces failures to the frontend via app.state.report_generation_error.

## What Was Built

### `src/alphaswarm/web/routes/report.py` (new)

- `GET /api/report/{cycle_id}` — returns 200 with `{cycle_id, content, generated_at}` when `reports/{cycle_id}_report.md` exists. Uses `await aiofiles.os.path.exists(...)` and `await aiofiles.os.stat(...)` so the async event loop is never blocked (CLAUDE.md Hard Constraint 1 / T-36-14). When the file is absent but a prior generation failed for the cycle, returns 500 with `error='report_generation_failed'` and the recorded message so the frontend can stop polling (T-36-15).
- `POST /api/report/{cycle_id}/generate` — 202 Accepted after spawning `asyncio.create_task(_run_report_generation(...))` and attaching `_on_report_task_done` as a `add_done_callback`. Clears any stale `app.state.report_generation_error[cycle_id]` on each successful spawn so prior failures do not poison a new run. Guards: 503 missing services, 409 wrong phase (D-01), 409 in-progress (D-02), 400 invalid cycle_id (T-36-01).
- `_run_report_generation(app_state, cycle_id)` — mirrors `cli.py _handle_report` verbatim. Loads orchestrator → builds the 8-tool registry → pre-seeds `shock_impact` observation when a `ShockEvent` exists (Phase 27) → runs `ReportEngine.run` → `ReportAssembler.assemble` → `write_report` → `write_sentinel`. Orchestrator unload lives in a `finally` block and is itself wrapped in try/except so a flaky unload never masks the original failure.
- `_on_report_task_done(task, cycle_id, app)` — records `{error, message}` into `app.state.report_generation_error[cycle_id]` on exception or cancellation; no-op on success. Defensive inner `except Exception: pass` prevents the callback itself from raising into asyncio's "Task exception was never retrieved" path.

### `src/alphaswarm/web/app.py` (modified)

- New import: `from alphaswarm.web.routes.report import router as report_router`.
- Lifespan adds `app.state.report_task = None` (D-02 in-progress handle) and `app.state.report_generation_error = {}` (T-36-15 error surface).
- `create_app()` registers `app.include_router(report_router, prefix="/api")` after the interview router.

### `tests/test_web_report.py` (new) — 13 tests

- GET: 200 hit, 404 miss, 400 invalid cycle_id, 500 surfaced-from-failure, static check that the GET handler uses `aiofiles.os` and never calls `Path.exists()`/`Path.stat()`.
- POST: 503 services, 409 wrong phase, 409 in-progress, 202 spawns task + clears stale error, 400 invalid cycle_id.
- Background task: canonical call order (`load_model → engine_run → assemble → write_report → write_sentinel → unload_model`) and orchestrator unload in finally even on error.
- done_callback: records exception into `app.state.report_generation_error[cycle_id]` on failure; leaves dict untouched on success.

### `tests/test_web.py` (modified)

- `_make_test_app` imports `report_router`, registers it at `/api`, and initializes both `app.state.report_task` and `app.state.report_generation_error` so the 46 existing web tests don't regress when the new router is attached.

## Verification Results

| Check | Result |
| --- | --- |
| `uv run pytest tests/test_web_report.py -x -q` | **13 passed** |
| `uv run pytest tests/test_web.py -x -q` | **46 passed** |
| `uv run pytest tests/ -q` (excluding 2 pre-existing-failure modules) | **617 of 618 pass**, 1 pre-existing failure in `test_replay_red.py::test_replay_module_exists` (Phase 34 red-phase test expecting 3 replay routes — repo has 4 since Phase 34, not touched by this plan) |
| `uv run mypy src/alphaswarm/web/routes/report.py` | **0 errors in the new module**; 1 error surfaces from a *pre-existing* untyped-import warning in `src/alphaswarm/report.py` (which this plan does not modify). See Deferred Issues. |
| Production `create_app()` registers `/api/report/{cycle_id}` and `/api/report/{cycle_id}/generate` | **Verified** via `python -c "from alphaswarm.web.app import create_app; ..."` |

## Key Decisions

1. **Test helpers run inside TestClient context.** The interview tests place mock-setup before `with TestClient(app) as client:` because their 503 case doesn't need `app.state.app_state` (it short-circuits on `graph_manager is None`). My POST 503/409 tests do touch `app.state.app_state`, which is created only during lifespan startup — so `_mock_complete_app_state(app)` and `_mock_all_services(app)` are called inside the context. This keeps the helper API identical while ensuring the backing state exists.

2. **Local narrowing over scattered `type: ignore`.** `_run_report_generation` starts by binding `model_manager = app_state.model_manager` and asserting non-None once, rather than repeating `# type: ignore[union-attr]` at every call site. The POST handler validates these services before scheduling the coroutine, so the assertions are never expected to fire in production.

3. **Pre-existing aiofiles stub concern not fixed in this plan.** `src/alphaswarm/report.py` imports `aiofiles` without a type stub and mypy already flags that error. I left the existing file alone and used `# type: ignore[import-untyped]` on my two new imports to follow the repo's current posture. Adding `types-aiofiles` to `pyproject.toml` is a repo-wide concern best handled as a separate quick task.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 — Blocking issue] Test helpers were called before TestClient lifespan startup**
- **Found during:** Task 2 GREEN run — the very first POST test failed with `AttributeError: 'State' object has no attribute 'app_state'`.
- **Issue:** The plan's test action wrote `_mock_complete_app_state(app)` before `with TestClient(app) as client:`, but FastAPI's lifespan only populates `app.state.app_state` after the context-manager enters. This is a real change from the interview-test pattern because my POST tests actually reach the `state_store.snapshot()` code path (interview-503 short-circuits earlier).
- **Fix:** Moved the mock helpers inside the `with TestClient(app) as client:` block in 5 POST tests.
- **Files modified:** `tests/test_web_report.py` (tests 503/409-phase/409-in-progress/202/400).
- **Commit:** `75c74d9` (folded into Task 2 GREEN because the tests had to pass before the commit).

**2. [Rule 3 — Blocking issue] Worktree branch was based on pre-Phase-36 commit**
- **Found during:** Pre-task branch verification.
- **Issue:** The worktree HEAD was at `718edab` (Phase 28) while the orchestrator expected `a8a1fbb` (Phase 36 plan revision R1). Running on the old base would have meant Phase 15's `report.py`/`cli.py` helpers that this plan relies on weren't present at the versions planned for.
- **Fix:** `git reset --soft a8a1fbb; git reset HEAD; git checkout a8a1fbb -- .` to adopt the correct tree state without losing planning artifacts. Removed a stray macOS Finder duplicate file that the reset surfaced (`.planning/phases/28-simulation-replay/28-02-SUMMARY 2.md`).
- **Files modified:** none of the plan's targets — only the worktree's base state.
- **Commit:** none (pre-task correction).

No other deviations. All plan tasks and acceptance criteria were satisfied as specified.

### Auth Gates

None.

## Deferred Issues

1. **`types-aiofiles` missing repo-wide.** `src/alphaswarm/report.py:12` (untouched) triggers `Library stubs not installed for "aiofiles"` under strict mypy. The same warning affected my new `aiofiles`/`aiofiles.os` imports until I added `# type: ignore[import-untyped]`. A proper fix is to add `types-aiofiles` to the dev dependency group — out of scope for this plan, recommend a `/gsd:quick` task.
2. **Pre-existing `test_replay_red.py::test_replay_module_exists` failure.** Expects `len(router.routes) == 3`; Phase 34 grew it to 4. Unrelated to Phase 36.
3. **Pre-existing `tests/test_report.py` HTML theme failures (multiple).** Unrelated to the web report route — they exercise `report.py`'s HTML/SVG output which isn't touched by this plan.
4. **Pre-existing `test_graph_integration.py::test_ensure_schema_idempotent` event-loop error.** Integration test hitting a real Neo4j; unrelated to this plan.

## Known Stubs

None — every response path has real behavior or real error signalling. The `TYPE_CHECKING` import of `AppState` is standard for forward references, not a stub.

## Threat Flags

None — every surface introduced here (GET + POST handlers, background task, done_callback) is already catalogued in the plan's `<threat_model>` (T-36-01, T-36-02, T-36-03, T-36-04, T-36-14, T-36-15, T-36-16). No new trust boundaries or authentication paths were added.

## Self-Check: PASSED

- File `src/alphaswarm/web/routes/report.py` exists — **FOUND**
- File `tests/test_web_report.py` exists — **FOUND**
- File `src/alphaswarm/web/app.py` modified with `report_router` + lifespan init — **FOUND**
- File `tests/test_web.py` modified with `report_router` + lifespan init — **FOUND**
- Commit `c84d489` (Task 1 — failing tests) — **FOUND**
- Commit `75c74d9` (Task 2 — route + app wiring + test fix) — **FOUND**
- All 13 report tests pass — **VERIFIED**
- All 46 test_web tests pass — **VERIFIED**
- GET handler contains `aiofiles.os.path.exists` and `aiofiles.os.stat` and contains neither `.exists()` nor `.stat()` on a Path — **VERIFIED**
- POST handler contains `task.add_done_callback` and `_on_report_task_done` — **VERIFIED**
- Production `create_app()` registers `/api/report/{cycle_id}` and `/api/report/{cycle_id}/generate` — **VERIFIED**
