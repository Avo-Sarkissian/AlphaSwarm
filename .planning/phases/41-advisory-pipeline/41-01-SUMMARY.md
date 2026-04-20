---
phase: 41-advisory-pipeline
plan: 01
subsystem: advisory

tags: [pydantic, ollama, structlog, neo4j, asyncio, advisory, ADVIS-01]

# Dependency graph
requires:
  - phase: 37-isolation-foundation-provider-scaffolding
    provides: importlinter contract gate allowing alphaswarm.advisory to import alphaswarm.holdings
  - phase: 39-holdings-loader
    provides: PortfolioSnapshot / Holding frozen dataclasses consumed by synthesize()
  - phase: 04-neo4j-graph-state
    provides: GraphStateManager.read_consensus_summary / read_round_timeline / read_bracket_narratives / read_entity_impact

provides:
  - alphaswarm.advisory package (Python library surface for ADVIS-01)
  - AdvisoryItem / AdvisoryReport frozen pydantic models (D-06 schema)
  - build_advisory_prompt pure function (system + user messages for orchestrator)
  - synthesize() coroutine with 4-way Neo4j prefetch, single LLM call, bounded retry, D-07 ranking
  - Fake-based unit test harness for ADVIS-01 behavior lock-in

affects: [41-02-advisory-route-wiring, 41-03-vue-advisory-panel]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - frozen pydantic BaseModel(frozen=True, extra='forbid') + tuple[...] for immutable boundary value graphs (mirrors alphaswarm.ingestion.types)
    - structlog event_dicts restricted to scalars when holdings data is in scope (Pitfall 1)
    - json.dumps(..., default=str) for any Decimal-bearing payload headed to an LLM (Pitfall 2)
    - bounded one-shot retry on pydantic ValidationError with error text fed back to the model (Pitfall 3)
    - asyncio.gather over four graph reads executed before the single LLM call (D-04)
    - Library module does NOT manage model lifecycle — load/unload is the caller's responsibility (D-08)

key-files:
  created:
    - src/alphaswarm/advisory/__init__.py
    - src/alphaswarm/advisory/types.py
    - src/alphaswarm/advisory/prompt.py
    - src/alphaswarm/advisory/engine.py
    - tests/unit/__init__.py
    - tests/unit/test_advisory.py
  modified: []

key-decisions:
  - "synthesize() does not call load_model/unload_model — that lifecycle belongs to the 41-02 FastAPI route (D-08 keeps the library infrastructure-free and unit-testable)."
  - "Seed rumor retrieval uses getattr(graph_manager, 'read_cycle_seed', None) with '' fallback so synthesize() works with graph managers that predate seed persistence."
  - "Ranking key = float(confidence) × (float(exposure) / float(total_cost_basis)) — Decimal precision is preserved in the displayed position_exposure, only the sort key floats (T-41-05 accepted)."
  - "Task 1 included a NotImplementedError placeholder in engine.py to keep the __init__ re-export surface importable before Task 2 wrote the real body — replaced in Task 2."

patterns-established:
  - "Advisory package = second whitelisted importer of alphaswarm.holdings (enforced by importlinter source_modules omission, not ignore_imports)."
  - "Library-style synthesis functions accept graph_manager and ollama_client as parameters (never module-level singletons) — enables Fakes in tests and easy swaps in routes."
  - "tests/unit/ introduced as a new test bucket for Fake-only pytest-socket-safe tests, complementing tests/ (mixed), tests/integration/ (live), tests/invariants/ (canary)."

requirements-completed: [ADVIS-01]

# Metrics
duration: 55min
completed: 2026-04-20
---

# Phase 41 Plan 01: Advisory Synthesis Library Summary

**alphaswarm.advisory package with frozen pydantic boundary types and the synthesize() coroutine that prefetches four Neo4j reads via asyncio.gather, issues a single orchestrator LLM call with one bounded retry on ValidationError, and reranks items by the D-07 confidence × exposure score.**

## Performance

- **Duration:** ~55 min
- **Started:** 2026-04-20T00:12:00Z
- **Completed:** 2026-04-20T01:07:04Z
- **Tasks:** 3
- **Files created:** 6 (4 source, 2 test)

## Accomplishments

- Shipped ADVIS-01 library surface: `synthesize(cycle_id, portfolio, graph_manager, ollama_client, orchestrator_model) -> AdvisoryReport` with the D-06 schema locked in at the type boundary.
- Locked in Pitfall 1/2/3 mitigations: no PortfolioSnapshot in logs, no raw Decimal in `json.dumps`, exactly one retry on `pydantic.ValidationError` before propagation.
- Locked in D-04 prefetch (four reads fired before any LLM call) and D-07 ranking (confidence × exposure / total_cost_basis, descending) with unit tests that fail if either invariant regresses.
- Introduced `tests/unit/` as the new pytest-socket-safe Fake-only bucket; 8 tests green in ~0.1s.
- Verified importlinter contract still holds: `alphaswarm.advisory` can import `alphaswarm.holdings` because it's intentionally absent from `source_modules` (no new `ignore_imports` entries needed).

## Task Commits

Each task was committed atomically on branch `worktree-agent-aebb0270`:

1. **Task 1: Create advisory types + prompt builder + package __init__** — `b64215d` (feat)
2. **Task 2: Implement synthesize() engine with prefetch, retry, ranking** — `bd90867` (feat)
3. **Task 3: Unit tests — schema, ranking, prefetch, retry, canary** — `2df0e1d` (test)

## Files Created/Modified

- `src/alphaswarm/advisory/__init__.py` — public re-exports: `synthesize`, `AdvisoryItem`, `AdvisoryReport`, `Signal`.
- `src/alphaswarm/advisory/types.py` — `AdvisoryItem`, `AdvisoryReport` frozen pydantic models; `Signal = Literal["BUY","SELL","HOLD"]`.
- `src/alphaswarm/advisory/prompt.py` — `build_advisory_prompt` pure function; system message embeds the AdvisoryReport schema + a worked JSON example (Pitfall 3 mitigation).
- `src/alphaswarm/advisory/engine.py` — `synthesize` coroutine + `_infer_with_retry` helper. Prefetches 4 graph reads via `asyncio.gather`, optional `read_cycle_seed` via `getattr`, minimal holdings dict serialization, single LLM call with `format="json"`, one retry on `ValidationError`, D-07 rerank via `model_copy(update=...)`.
- `tests/unit/__init__.py` — new test bucket package marker.
- `tests/unit/test_advisory.py` — 8 unit tests covering schema enforcement, ranking, LLM-driven omission, prefetch order, retry success, retry exhaustion, and a mini log-leak canary.

## Decisions Made

- **Library decoupled from model lifecycle (D-08).** `synthesize()` intentionally does not call `load_model`/`unload_model`. The 41-02 FastAPI route (`_run_advisory_synthesis`) owns that try/finally so unit tests can run the engine against pure Fakes without a ModelManager dependency.
- **Optional seed rumor retrieval.** The graph manager may or may not expose `read_cycle_seed` depending on prior phase shipping state. Using `getattr(..., None)` with an empty-string fallback and a `try/except` warning keeps synthesis working today and auto-lights up when seed persistence lands.
- **Decimal in display, float in sort key.** `position_exposure` stays `Decimal` through the public schema; only the sort key is floated. T-41-05 in the threat register accepts this precision loss because the float never becomes a displayed value.
- **Task 1 placeholder engine.** Task 1's acceptance criterion `from alphaswarm.advisory import synthesize` required `engine.py` to exist before Task 2. A 20-line `engine.py` stub with `raise NotImplementedError` was written in Task 1 and replaced in full by Task 2 — documented in the commit message and flagged as a deviation below.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Task 1 stub engine.py to satisfy cross-task import surface**
- **Found during:** Task 1 (verify step)
- **Issue:** Task 1's `<files>` list covers `__init__.py`, `types.py`, `prompt.py` only, but `__init__.py` re-exports `synthesize` from `engine` AND Task 1's acceptance criterion runs `from alphaswarm.advisory import ... synthesize`. Without `engine.py` existing, the import chain raises `ModuleNotFoundError` and Task 1 cannot individually verify.
- **Fix:** Wrote a minimal `engine.py` in Task 1 with the full `synthesize()` signature returning `raise NotImplementedError("synthesize() is implemented in plan 41-01 Task 2")`. Task 2 then overwrote the file with the real implementation.
- **Files modified:** `src/alphaswarm/advisory/engine.py` (Task 1 stub, Task 2 full body).
- **Verification:** Task 1 import check passes (`OK`); Task 2 replaces the stub entirely — `grep NotImplementedError src/alphaswarm/advisory/engine.py` returns empty.
- **Committed in:** `b64215d` (Task 1) and `bd90867` (Task 2 full replacement).

**2. [Rule 2 - Missing Critical] tests/unit/__init__.py added for pytest discovery convention**
- **Found during:** Task 3 (test discovery)
- **Issue:** The plan directed creating `tests/unit/test_advisory.py` but `tests/unit/` did not exist, and the existing test subdirectories (`tests/integration/`, `tests/invariants/`) both have `__init__.py` — the project convention. Without the init file, pytest still discovers the module but the subdir is not a proper package and tooling (e.g., future coverage configs, importlinter-like tests) may misbehave.
- **Fix:** Added `tests/unit/__init__.py` with a short docstring documenting the Fake-only / socket-free invariant of the bucket.
- **Files modified:** `tests/unit/__init__.py`.
- **Verification:** `pytest tests/unit/test_advisory.py -x -q` → `8 passed in 0.11s`.
- **Committed in:** `2df0e1d` (alongside Task 3 tests).

**3. [Rule 3 - Blocking] Worktree branch rebased onto Phase 41 base commit**
- **Found during:** Pre-execution worktree base check
- **Issue:** This worktree was created from commit `c0848e6` (post-Phase 36 / v5.0 ship) rather than the current Phase 41 base `538804b`. All phase 37-40 source and planning files were absent from the working tree.
- **Fix:** `git reset --hard 538804bb7e347662628b0068d70da13c81907537` per the worktree_branch_check instructions in the execution prompt.
- **Files modified:** None (reset pulled in the correct committed state).
- **Verification:** `git merge-base HEAD 538804b` == `538804b`; `.planning/phases/41-advisory-pipeline/41-01-PLAN.md` exists; `src/alphaswarm/holdings/types.py` exists.
- **Committed in:** No commit (metadata-only worktree state fix).

---

**Total deviations:** 3 auto-fixed (2 blocking, 1 missing convention)
**Impact on plan:** All three deviations were mechanical / ordering issues. No behaviour contract was changed. No new dependencies. importlinter and mypy strict remained green throughout.

## Issues Encountered

- None beyond the deviations above.

## Verification Results

```
uv run python -c "from alphaswarm.advisory import AdvisoryItem, AdvisoryReport, synthesize; print('OK')"
  → OK

uv run mypy src/alphaswarm/advisory/
  → Success: no issues found in 4 source files

uv run lint-imports
  → Holdings isolation — only advisory and web.routes.holdings may import
     alphaswarm.holdings KEPT
     Contracts: 1 kept, 0 broken.

uv run pytest tests/unit/test_advisory.py -x -q
  → 8 passed in 0.11s
```

Negative greps (T-41-01 + D-08 enforcement):

- `grep -n 'log\.(info|warning|error)\([^)]*portfolio=' src/alphaswarm/advisory/` → no matches
- `grep -n 'log\.(info|warning|error)\([^)]*\(snapshot=\|holdings=\)' src/alphaswarm/advisory/` → no matches
- `grep -n 'load_model\|unload_model' src/alphaswarm/advisory/` → no matches
- `grep -c 'format="json"' src/alphaswarm/advisory/engine.py` → 2 (initial + retry)
- `grep -c 'model_validate_json' src/alphaswarm/advisory/engine.py` → 2 (initial + retry)

## User Setup Required

None — no external service configuration required. Advisory synthesis uses local Ollama and the existing Neo4j driver via graph_manager.

## Next Phase Readiness

- **Plan 41-02 can start.** The route `_run_advisory_synthesis` will import `from alphaswarm.advisory import synthesize` and wrap it with:
  1. `try`/`finally` `load_model("alphaswarm-orchestrator")` + `unload_model(...)` (D-08).
  2. Writing the `AdvisoryReport` to `advisory/{cycle_id}_advisory.json` via aiofiles.
  3. Recording generation errors onto `app.state.advisory_generation_error`.
- **Plan 41-03 (Vue panel) can reference the schema.** `AdvisoryReport.model_json_schema()` is now a stable contract Vue can type against.
- **ISOL-07 mini-canary is in place** (`test_synthesize_never_logs_portfolio_fields`). The full four-surface canary (log + WS + Neo4j + Jinja) still belongs to 41-02.

## Self-Check: PASSED

Files verified on disk:
- `src/alphaswarm/advisory/__init__.py` → FOUND
- `src/alphaswarm/advisory/types.py` → FOUND
- `src/alphaswarm/advisory/prompt.py` → FOUND
- `src/alphaswarm/advisory/engine.py` → FOUND
- `tests/unit/__init__.py` → FOUND
- `tests/unit/test_advisory.py` → FOUND

Commits verified in git log:
- `b64215d` (Task 1) → FOUND
- `bd90867` (Task 2) → FOUND
- `2df0e1d` (Task 3) → FOUND

---
*Phase: 41-advisory-pipeline*
*Plan: 01*
*Completed: 2026-04-20*
