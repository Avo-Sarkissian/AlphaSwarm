---
phase: quick-260611-rlx
plan: 01
subsystem: advisory + web routes + frontend
tags: [advisory, report, ollama, think-suppression, asyncio-chain, ui-copy]
requires:
  - advisory.synthesize (_infer_with_retry)
  - web.routes.report (POST /report/{cycle_id}/generate, bidirectional 409 guard)
  - web.simulation_manager (_auto_trigger_advisory pattern)
provides:
  - advisory._infer_with_retry with think=False on both chat calls
  - web.routes.advisory._auto_trigger_report (in-process report chain)
  - web.routes.advisory._report_chain_tasks (module-level strong-ref set)
  - ReportModal auto-generation copy
affects:
  - GET /api/advisory/{cycle_id} (no longer 500s on timeout)
  - report generation lifecycle (auto-fires after successful advisory)
tech-stack:
  added: []
  patterns:
    - think=False on every orchestrator chat call (consistency with seed/report/interview/worker)
    - ASGITransport in-process chaining + module-level strong-ref set for sync done-callbacks
key-files:
  created: []
  modified:
    - src/alphaswarm/advisory/engine.py
    - src/alphaswarm/web/routes/advisory.py
    - frontend/src/components/ReportModal.tsx
    - tests/unit/test_advisory.py
    - tests/unit/test_advisory_route.py
decisions:
  - "think=False on both _infer_with_retry chat calls — reasoning tokens at 11.3 t/s exceeded the 600s timeout"
  - "Report chain fires ONLY on advisory success; cancel/failure branches skip it (orchestrator may be wedged)"
  - "Strong-ref set lives at module level — the sync done-callback has no self to anchor task refs"
  - "Report route's bidirectional 409 guard stays authoritative; chain tolerates it as skipped_conflict"
metrics:
  duration_min: 10
  completed: 2026-06-11
  tasks: 3
  files: 5
---

# Phase quick-260611-rlx Plan 01: Advisory Synthesis Timeout Fix + Report Auto-Chain Summary

Suppressed qwen3.6 reasoning tokens in advisory synthesis (think=False) to eliminate the 600s-timeout-driven HTTP 500, and chained in-process report generation off the advisory success branch so both artifacts produce from one user action.

## What Was Built

**Bug fix (Task 1):** `_infer_with_retry` in `advisory/engine.py` now passes `think=False` on both the initial chat and the validation-retry chat. The MLX orchestrator (qwen3.6:27b-nvfp4) decodes at ~11.3 t/s; with thinking defaulting ON, reasoning tokens pushed the single advisory chat past the 600s client timeout, and the done-callback recorded that timeout into `app.state.advisory_generation_error[cycle_id]`, making `GET /api/advisory/{cycle_id}` return 500 permanently. This brings advisory into line with every other call path (seed.py:73, report.py:160, interview.py:140/174, worker.py — all pass `think=False`).

**Feature (Task 2):** Added module-level `_auto_trigger_report(app, cycle_id)` in `web/routes/advisory.py`, mirroring `_auto_trigger_advisory` in `simulation_manager.py` — an in-process `httpx.ASGITransport` POST to `/api/report/{cycle_id}/generate`. `_on_advisory_task_done` now schedules this chain on the SUCCESS branch only (`exc is None`), holding a strong reference in a module-level `_report_chain_tasks` set (the event loop keeps only weak refs to bare tasks, and the sync done-callback has no `self` to anchor refs). The cancel and exception branches do NOT chain — when the orchestrator may be wedged, we don't pile on. Outcomes are swallowed with scalar-only structlog (202 accepted, 409 skipped_conflict, 503 skipped_unavailable, else unexpected_status, Exception logged + swallowed).

**Copy (Task 3):** `ReportModal.tsx` empty-state paragraph now states reports auto-generate after the advisory, with the manual "Generate report" button retained as a fallback / regenerate path. Modal structure, conditional render guards, and `handleGenerate` are unchanged.

## Loop Safety

`report.py` contains no advisory *trigger* (its only advisory references are the bidirectional 409 guard reading `advisory_task` state). Therefore report → advisory recursion is impossible; the only chain is advisory-success → report. The report route's bidirectional orchestrator-serialization 409 guard is untouched and tolerated by the chain (logged as `auto_report_trigger_skipped_conflict`).

## Constraint Compliance

- 100% async: both new paths are `async def`; no blocking I/O introduced. The done-callback stays sync and non-raising (defensive try/except matches existing branches).
- Scalar-only logging: all new logs emit `cycle_id` / `status` scalars — no portfolio objects.
- Strict typing: `_report_chain_tasks: set[asyncio.Task[Any]]`; signatures annotated.

## Deviations from Plan

None — plan executed exactly as written.

Note: the plan's `<verify>` blocks specified `uv run pytest`. The sandbox has no network DNS, so `uv` could not resolve `hatchling` to build a fresh worktree venv. Tests were run with the established main-repo `.venv` interpreter (`pytest 9.0.2`) and `PYTHONPATH` pointed at the worktree's `src/`, which was verified to import the worktree source (`alphaswarm.__file__` resolves under the worktree). The frontend build was run by symlinking the worktree's `frontend/node_modules` to the main repo's (package.json verified byte-identical), then removed afterward. This is an execution-environment adaptation, not a plan deviation — the same test/build commands ran against the worktree's modified code.

## Test Results

- `tests/unit/test_advisory.py`: 14 passed (incl. new `test_infer_with_retry_passes_think_false` asserting `think_calls == [False, False]`)
- `tests/unit/test_advisory_route.py`: 11 passed (incl. 3 new chain tests: success schedules report, failure does not, cancel does not)
- `tests/unit/test_auto_advisory_trigger.py`: 9 passed (existing, regression-free)
- `tests/test_web_report.py`: 13 passed (report route bidirectional 409 guard regression-free)
- Frontend `npm run build` (tsc -b && vite build): green, 69 modules transformed

## Commits

- `2a87620` fix(quick-260611-rlx): suppress reasoning tokens in advisory synthesis
- `bbb12eb` feat(quick-260611-rlx): chain report auto-generation off advisory success
- `a10ce09` docs(quick-260611-rlx): ReportModal copy reflects report auto-generation

## Manual Verification Needed

Backend restart required to pick up Python changes (uvicorn does not hot-reload); browser hard-refresh for the frontend. End-to-end: run a simulation to COMPLETE, confirm the advisory finishes without 500, and confirm a report auto-generates for the same cycle without a second manual click.

## Self-Check: PASSED

- All 5 modified source/test files exist on disk + SUMMARY.md created.
- All 3 commits present in git history (2a87620, bbb12eb, a10ce09).
- `think=False` appears twice in engine.py (both chat calls); `_auto_trigger_report` and `_report_chain_tasks` present in advisory.py.
