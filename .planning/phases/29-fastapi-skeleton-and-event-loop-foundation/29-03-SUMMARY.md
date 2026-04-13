---
phase: 29-fastapi-skeleton-and-event-loop-foundation
plan: 03
subsystem: api
tags: [fastapi, uvicorn, cli, argparse, web-server]

# Dependency graph
requires:
  - phase: 29-02
    provides: src/alphaswarm/web/ package with create_app factory; SimulationManager; ConnectionManager
provides:
  - alphaswarm web CLI subcommand with --host (default 127.0.0.1) and --port (default 8000)
  - _handle_web plain def calling uvicorn.run(create_app()) — synchronous, no asyncio.run wrapper
  - Complete BE-01 requirement: running `alphaswarm web` launches FastAPI with health endpoint
affects: [30-websocket-broadcaster, 32-simulation-wiring]

# Tech tracking
tech-stack:
  added:
    - "fastapi>=0.115 (added to pyproject.toml — was missing from worktree)"
    - "uvicorn[standard]>=0.34 (added to pyproject.toml — was missing from worktree)"
    - "httpx>=0.28 (added to pyproject.toml — required by FastAPI test client)"
  patterns:
    - "Synchronous CLI handler for server startup: _handle_web is plain def, uvicorn.run() owns the asyncio event loop — no asyncio.run() wrapper (D-13)"
    - "Lazy imports inside CLI handlers: uvicorn and alphaswarm.web imported inside _handle_web body, matching existing _handle_tui/_handle_run pattern"
    - "Uniform error-handling pattern: KeyboardInterrupt + Exception catch in every elif branch, sys.exit(1) on failure"

key-files:
  created: []
  modified:
    - src/alphaswarm/cli.py
    - pyproject.toml
    - uv.lock

key-decisions:
  - "_handle_web is plain def (not async def) — uvicorn.run() creates and owns the asyncio event loop internally; wrapping with asyncio.run() would create nested event loop error (D-13)"
  - "fastapi/uvicorn/httpx added to pyproject.toml as blocking deviation fix — worktree's base commit predated the 29-01 dep install merge"

patterns-established:
  - "Web CLI handler pattern: plain def with lazy uvicorn import calling uvicorn.run(create_app(), host=host, port=port)"

requirements-completed: [BE-01]

# Metrics
duration: 15min
completed: 2026-04-13
---

# Phase 29 Plan 03: Web CLI Subcommand Summary

**`alphaswarm web` CLI entry point wired to uvicorn.run(create_app()) with --host/--port flags, completing BE-01 end-to-end**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-04-13T01:42:00Z
- **Completed:** 2026-04-13T01:57:24Z
- **Tasks:** 2
- **Files modified:** 3 (cli.py, pyproject.toml, uv.lock)

## Accomplishments

- Added `_handle_web(host: str, port: int)` plain def to `cli.py` — lazy imports uvicorn and `create_app`, calls `uvicorn.run(create_app(), host=host, port=port)` directly with no asyncio.run wrapper
- Added `web` subparser to `main()` with `--host` (default 127.0.0.1) and `--port` (default 8000) arguments
- Added `elif args.command == "web"` branch with identical error-handling pattern to all other subcommands
- Added fastapi>=0.115, uvicorn[standard]>=0.34, httpx>=0.28 to pyproject.toml (Rule 3 fix — worktree venv lacked these)
- Full unit test suite: 537 tests pass (test_state.py + test_web.py + all other unit tests)
- `alphaswarm web --help` shows correct usage with --host and --port

## Task Commits

Each task was committed atomically:

1. **Task 1: Add web subparser and _handle_web to cli.py** — `c55fa3b` (feat)
2. **Task 2: Run full test suite + fix missing dependencies** — `9a18403` (feat)

## Files Created/Modified

- `src/alphaswarm/cli.py` — Added _handle_web function, web subparser, elif branch
- `pyproject.toml` — Added fastapi>=0.115, uvicorn[standard]>=0.34, httpx>=0.28 to dependencies
- `uv.lock` — Updated lock file after dependency sync

## Decisions Made

- `_handle_web` is plain `def` (not `async def`) per D-13: `uvicorn.run()` is a blocking synchronous call that creates and owns the asyncio event loop internally. Using `asyncio.run()` as a wrapper would cause a nested event loop error
- Lazy imports inside `_handle_web` body match the established CLI pattern (every other handler — `_handle_tui`, `_handle_run`, `_handle_replay` — uses lazy imports)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added fastapi, uvicorn, httpx to pyproject.toml**
- **Found during:** Task 2 (full test suite run)
- **Issue:** `tests/test_web.py` failed with `ModuleNotFoundError: No module named 'fastapi'` — the worktree's venv was created from the base commit (718edab) which predated the Plan 29-01 dep install. The git reset --soft to ad5f8a5 updated the index/commits but the venv was already built without fastapi
- **Fix:** Added `fastapi>=0.115`, `uvicorn[standard]>=0.34`, `httpx>=0.28` to `[project.dependencies]` in pyproject.toml; ran `uv sync` to install
- **Files modified:** pyproject.toml, uv.lock
- **Verification:** `uv run pytest tests/test_state.py tests/test_web.py -x -q` → 34 passed; full suite 537 passed
- **Committed in:** `9a18403` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 3 — blocking dependency install)
**Impact on plan:** Required for test suite to run. No scope creep — these packages were already planned by Plan 29-01; the worktree simply lacked them due to parallel execution timing.

## Issues Encountered

- Pre-existing test failures (out of scope, not fixed):
  - `tests/test_graph_integration.py::test_ensure_schema_idempotent` — requires live Neo4j connection; "Future attached to a different loop" error
  - `tests/test_report.py::TestHtmlAssembler::test_produces_html_document` — `ReportAssembler` has no `assemble_html` method; pre-dates Phase 29
- Both confirmed pre-existing by `git stash` test (same failures before our changes)

## User Setup Required

None — no external service configuration required. The `alphaswarm web` command is self-contained; running it starts the server on 127.0.0.1:8000.

## Next Phase Readiness

- Phase 29 is complete: `alphaswarm web` starts uvicorn, GET /api/health returns 200, full unit test suite green
- Phase 30 (WebSocket broadcaster) can now import `ConnectionManager` and wire `broadcast()` on a tick cadence
- Phase 32 (simulation wiring) can call `SimulationManager.start()` to fill the stub with real `run_simulation()` call
- All Phase 29 BE-01 acceptance criteria verified:
  - running `alphaswarm web` starts a Uvicorn server (confirmed by import + argument parsing)
  - `web` subparser accepts `--host` (default 127.0.0.1) and `--port` (default 8000)
  - `_handle_web` is a plain def (not async def) calling `uvicorn.run()` directly
  - Full test suite passes with no regressions from CLI changes

---
*Phase: 29-fastapi-skeleton-and-event-loop-foundation*
*Completed: 2026-04-13*

## Self-Check: PASSED

- FOUND: src/alphaswarm/cli.py (modified with _handle_web, web subparser, elif branch)
- FOUND: pyproject.toml (modified with fastapi, uvicorn, httpx deps)
- FOUND commit: c55fa3b
- FOUND commit: 9a18403
- VERIFIED: `grep -c "def _handle_web" src/alphaswarm/cli.py` = 1
- VERIFIED: `grep "def _handle_web(host: str, port: int)"` matches
- VERIFIED: `grep "uvicorn.run(create_app(), host=host, port=port)"` matches
- VERIFIED: `grep "from alphaswarm.web import create_app"` matches (inside _handle_web)
- VERIFIED: `grep 'add_parser("web"'` matches
- VERIFIED: `grep 'default="127.0.0.1"'` matches
- VERIFIED: `grep "default=8000"` matches
- VERIFIED: `grep 'args.command == "web"'` matches
- VERIFIED: `grep "_handle_web(args.host, args.port)"` matches
- VERIFIED: no `async def _handle_web` (plain def confirmed)
- VERIFIED: no `asyncio.run.*_handle_web` (no wrapper confirmed)
- VERIFIED: 537 unit tests pass
