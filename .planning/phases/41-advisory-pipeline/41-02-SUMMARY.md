---
phase: 41
plan: "02"
status: complete
self_check: PASSED
completed: "2026-04-20"
---

# Plan 41-02 Summary — FastAPI Advisory Route + ISOL-07 Canary Flip

## What Was Built

POST/GET advisory REST endpoints mirroring the Phase 36 report endpoint, router registered in `app.py`, importlinter whitelist updated, route unit tests, and ISOL-07 canary flipped from SCAFFOLDED → ACTIVE.

## Key Files

### Created
- `src/alphaswarm/web/routes/advisory.py` — 281-line POST/GET route pair with 3x 409 guards, 2x 503 guards, `try/finally` unload_model, done-callback
- `tests/unit/test_advisory_route.py` — 12 tests covering 202/503/409/400 POST + 200/404/500 GET

### Modified
- `src/alphaswarm/web/app.py` — `advisory_router` registered, `advisory_task` and `advisory_generation_error` state initialized
- `pyproject.toml` — `alphaswarm.web.routes.advisory` added to importlinter `source_modules` with 2 narrow `ignore_imports` entries
- `tests/invariants/test_holdings_isolation.py` — ISOL-07 canary flipped: `_minimal_simulation_body` → real `synthesize()` harness
- `tests/invariants/conftest.py` — `_advisory_harness_body` fixture added

## Commits

| Hash | Message |
|------|---------|
| `badf721` | feat(41-02): add advisory route + register router + importlinter whitelist |
| `12ad57c` | test(41-02): add ADVIS-02 route unit tests — 202/503/409/400 POST + 200/404/500 GET |
| `0d1f08e` | test(41-02): flip ISOL-07 canary — real synthesize() harness replaces scaffold (D-20) |

## Verification

- `uv run python -c "from alphaswarm.web.routes.advisory import router; print('OK')"` → OK
- `uv run mypy src/alphaswarm/web/routes/advisory.py src/alphaswarm/web/app.py` → no issues in 2 files
- `uv run lint-imports` → 1 contract kept, 0 broken
- `uv run pytest tests/unit/test_advisory_route.py -q` → 12 passed
- `uv run pytest tests/invariants/test_holdings_isolation.py -q` → 10 passed (ISOL-07 ACTIVE)
- `uv run pytest tests/unit/ tests/invariants/ -q` → 36 passed

## Must-Haves Status

| Must-Have | Status |
|-----------|--------|
| POST /api/advisory/{cycle_id} triggers synthesis task | ✓ |
| GET /api/advisory/{cycle_id} returns status/result | ✓ |
| Router registered in app.py | ✓ |
| importlinter whitelist updated | ✓ |
| Route unit tests (202/503/409/400 POST + 200/404/500 GET) | ✓ |
| ISOL-07 canary flipped to ACTIVE | ✓ |

## Deviations

1. Two narrow `ignore_imports` entries required in `pyproject.toml` — importlinter traces transitive imports; the route TYPE_CHECKING-imports `PortfolioSnapshot` from holdings.types. Plan's Assumption A6 was incorrect.

## Requirements Closed

- ADVIS-02 (advisory REST endpoint + lifecycle)
- ADVIS-03 (partial — backend canary; Vue UI portion in Plan 41-03)
