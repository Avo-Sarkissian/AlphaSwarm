---
phase: 37
plan: 04
subsystem: importlinter-canary
tags: [importlinter, pre-commit, canary, sentinel, pii, isolation, isol-03, isol-07]

requires:
  - phase: 37-01
    provides: PortfolioSnapshot, Holding frozen dataclasses + sha256_first8 hasher
  - phase: 37-02
    provides: FakeMarketDataProvider for sentinel ContextPacket construction
  - phase: 37-03
    provides: pii_redaction_processor in structlog chain; pytest-socket global gate

provides:
  - pyproject.toml [tool.importlinter] forbidden contract with whitelist-only source_modules
  - .pre-commit-config.yaml with local lint-imports hook (D-02)
  - tests/invariants/__init__.py + conftest.py + three test files (D-16)
  - tests/integration/__init__.py + conftest.py + socket escape hatch smoke test (D-12)

affects:
  - Phase 38+ (all future tests): drift-resistant coverage test catches new packages missing from source_modules
  - Phase 41 (advisory pipeline): canary scaffolded and ready; flip from SCAFFOLDED to ACTIVE by replacing _minimal_simulation_body with real synthesize() call
  - Phase 39 (holdings-loader): auto-marker in tests/integration/ applies enable_socket to all real-network tests

tech-stack:
  added: []
  patterns:
    - importlinter forbidden contract (whitelist-inversion): source_modules enumerates ALL non-whitelisted packages; allowlist is {alphaswarm.advisory, alphaswarm.web.routes.holdings}
    - drift-resistant coverage test: filesystem walk + tomllib parse reconciled at test time — new packages trip the test until listed
    - Four-surface canary with representation variants: raw/Decimal-str/JSON-quoted/sha256_first8 forms all searched
    - Positive controls per surface (Pitfall 6): capture machinery is self-validating
    - SCAFFOLDED label + Phase 41 activation checklist in canary docstring (Codex REVIEW MEDIUM)
    - Integration auto-marker: conftest pytest_collection_modifyitems applies enable_socket by path match (D-12)

key-files:
  created:
    - .pre-commit-config.yaml
    - tests/invariants/__init__.py
    - tests/invariants/conftest.py
    - tests/invariants/test_importlinter_contract.py
    - tests/invariants/test_importlinter_coverage.py
    - tests/invariants/test_holdings_isolation.py
    - tests/integration/__init__.py
    - tests/integration/conftest.py
    - tests/integration/test_socket_escape_hatch.py
  modified:
    - pyproject.toml (appended [tool.importlinter] stanza)

key-decisions:
  - "D-01 implemented: [tool.importlinter] forbidden contract with root_package=alphaswarm"
  - "D-02 implemented: .pre-commit-config.yaml local lint-imports hook; CI invariant documented (wiring deferred to ops)"
  - "D-03 implemented: programmatic test via subprocess+explicit PYTHONPATH+tmpdir config (REVIEW HIGH — Codex reliability)"
  - "D-04 implemented: whitelist-only source_modules — advisory + web.routes.holdings excluded; drift-resistant coverage test catches new packages"
  - "D-12 implemented: tests/integration/conftest.py auto-marker via pytest_collection_modifyitems"
  - "D-13 implemented: SENTINEL_TICKER=SNTL_CANARY_TICKER, SENTINEL_ACCT=SNTL_CANARY_ACCT_000, SENTINEL_COST_BASIS=Decimal('999999.99'), SENTINEL_QTY=Decimal('77.7777')"
  - "D-14/D-15 implemented: SCAFFOLDED four-surface canary with all_sentinel_representations() iterating raw/Decimal-str/JSON-quoted/sha256 forms"
  - "D-16 implemented: tests/invariants/ directory with __init__.py, conftest.py, and three test files"

requirements-completed: [ISOL-03, ISOL-07]

metrics:
  duration: ~30min
  completed: "2026-04-18"
  tasks: 2
  files_created: 9
  files_modified: 1
---

# Phase 37 Plan 04: importlinter Contract + Four-Surface Canary + Integration Auto-Marker Summary

**importlinter whitelist-only forbidden contract with drift-resistant coverage test; four-surface holdings isolation canary (SCAFFOLDED, representation-variant aware, with positive controls); and tests/integration conftest auto-applying enable_socket**

## Performance

- **Duration:** ~30 min
- **Started:** 2026-04-18
- **Completed:** 2026-04-18
- **Tasks:** 2 (Task 1: importlinter contract + coverage tests; Task 2: canary + integration conftest)
- **Files modified:** 9 new files, 1 modified (pyproject.toml)

## Accomplishments

### Task 1: importlinter Contract + Coverage Tests (ISOL-03)

- Appended `[tool.importlinter]` stanza to `pyproject.toml` with whitelist-only forbidden contract (D-01, D-04)
- `source_modules` enumerates all 35 non-whitelisted `alphaswarm.*` packages and sub-modules; `forbidden_modules = ["alphaswarm.holdings"]`
- `alphaswarm.advisory` and `alphaswarm.web.routes.holdings` deliberately excluded (D-04 whitelist) — these are the two future-allowed importers
- Created `.pre-commit-config.yaml` with local `lint-imports` hook (D-02); CI invariant documented in plan
- Created `tests/invariants/__init__.py` subpackage marker (D-16)
- Created `test_importlinter_contract.py`: three tests — clean-tree baseline, synthetic violation via subprocess+PYTHONPATH (REVIEW HIGH — Codex reliability), pyproject.toml meta-guard
- Created `test_importlinter_coverage.py`: three tests — dynamic filesystem enumeration vs source_modules + `_KNOWN_NON_SOURCE` allowlist; inverse whitelist check; forbidden_modules exactness check (REVIEW HIGH — Codex drift resistance)

### Task 2: Four-Surface Canary + Integration Auto-Marker (ISOL-07)

- Created `tests/invariants/conftest.py`: SENTINEL constants at module level; `all_sentinel_representations()` returning 7 forms (raw, Decimal-str, JSON-quoted x2, sha256_first8); four in-memory capture fixtures with no socket activity (REVIEW LOW — Codex)
- Created `test_holdings_isolation.py`: SCAFFOLDED four-surface canary with 4 negative assertions (iterating ALL representation variants), 4 positive controls (Pitfall 6), 2 meta tests; Phase 41 activation-point checklist in docstring (REVIEW MEDIUM — Codex)
- Created `tests/integration/__init__.py` with future-phase guidance
- Created `tests/integration/conftest.py`: `pytest_collection_modifyitems` hook auto-applying `enable_socket` by path match (D-12, Pitfall 4)
- Created `tests/integration/test_socket_escape_hatch.py`: smoke test proving auto-marker allows socket creation

## Review Concerns Closed

| Concern | Source | Resolution |
|---------|--------|------------|
| Brittle source_modules enumeration | Codex HIGH | `test_importlinter_coverage.py` _enumerate_actual_packages() does filesystem walk + tomllib parse; new packages trip the test |
| D-04 coverage completeness | Codex HIGH | Same coverage test + `_KNOWN_NON_SOURCE = {advisory, web.routes.holdings, holdings}` allowlist asserted |
| Synthetic violation reliability | Codex HIGH | subprocess with explicit PYTHONPATH+tmpdir config, not import_linter internal API |
| Canary realism | Codex MEDIUM | SCAFFOLDED label in docstring + Phase 41 activation checklist with 3-step procedure |
| Sentinel representation variants | Codex MEDIUM | `all_sentinel_representations()` returns 7 forms; `test_all_sentinel_representations_covers_expected_forms` pins the set |
| Neo4j/WS socket-free | Codex LOW | `capture_ws_frames`, `capture_neo4j_writes`, `capture_jinja_renders` are pure `list[str]`; zero drivers |
| Decimal serialization | Gemini LOW | `json.dumps(..., default=str)` in `_minimal_simulation_body` |
| CI lint-imports | Codex LOW | Invariant documented in plan; wiring to CI pipeline deferred to ops |

## Files Created/Modified

- `pyproject.toml` — appended `[tool.importlinter]` stanza with 35-entry source_modules whitelist-inversion contract
- `.pre-commit-config.yaml` — local `lint-imports` hook for pre-commit enforcement (D-02)
- `tests/invariants/__init__.py` — subpackage marker (D-16)
- `tests/invariants/conftest.py` — sentinel constants + `all_sentinel_representations()` + 4 surface capture fixtures (ISOL-07)
- `tests/invariants/test_importlinter_contract.py` — ISOL-03 programmatic contract test (3 tests)
- `tests/invariants/test_importlinter_coverage.py` — REVIEW HIGH drift-resistant coverage test (3 tests)
- `tests/invariants/test_holdings_isolation.py` — ISOL-07 SCAFFOLDED canary (10 tests: 4 negative + 4 positive + 2 meta)
- `tests/integration/__init__.py` — integration subpackage marker
- `tests/integration/conftest.py` — D-12 auto-marker hook
- `tests/integration/test_socket_escape_hatch.py` — D-12 smoke test

## Decisions Made

- **source_modules includes sub-modules (ingestion.providers, ingestion.types, security.hashing, web, web.routes):** The `_enumerate_actual_packages()` function walks all `.py` files and sub-packages, not just top-level packages. The `source_modules` list must therefore include every path the walker finds — otherwise the coverage test fails. This is the correct behavior: importlinter's forbidden contract applies per-module, so sub-modules that aren't listed are not covered.
- **All canary fakes are pure in-memory lists:** No real Neo4j driver or ConnectionManager is instantiated in the canary. This keeps the invariant tests compatible with Plan 03's `--disable-socket` gate. The tests are marked `pytestmark = pytest.mark.enable_socket` defensively for Phase 41 when real advisory synthesis calls may need it.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] source_modules list missing sub-module entries**
- **Found during:** Task 1 GREEN phase (first coverage test run)
- **Issue:** `test_source_modules_covers_every_actual_package` failed because `_enumerate_actual_packages()` also finds `.py` file modules (not just `__init__.py` packages), plus `alphaswarm.web` and `alphaswarm.web.routes` intermediate packages. These were not in the initial source_modules list.
- **Fix:** Added `alphaswarm.ingestion.providers`, `alphaswarm.ingestion.types`, `alphaswarm.security.hashing`, `alphaswarm.web`, `alphaswarm.web.routes` to source_modules in pyproject.toml. `uv run lint-imports` still exits 0 with the expanded list.
- **Files modified:** `pyproject.toml`

## Known Stubs

The four-surface canary (`test_holdings_isolation.py`) is explicitly labeled **SCAFFOLDED**. The `_minimal_simulation_body` is a stand-in that does not consume `sentinel_portfolio` — it logs generic events, appends generic frames, and renders nothing. This is intentional at Phase 37 because `alphaswarm.advisory.pipeline` does not exist yet.

The canary becomes load-bearing at Phase 41. Activation procedure documented in the test file's docstring.

## Threat Flags

None — no new network endpoints, auth paths, or file access patterns. All surfaces are process-internal test infrastructure.

## Verification

```
uv run lint-imports
# Contracts: 1 kept, 0 broken.

uv run pytest tests/invariants/ tests/integration/ -v
# 17 passed in 0.38s

uv run pytest -q --ignore=tests/test_graph_integration.py
# 736 passed (graph_integration excluded: Neo4j server not running — pre-existing)
```

## Self-Check: PASSED

Files confirmed to exist:
- `.pre-commit-config.yaml` — FOUND
- `tests/invariants/__init__.py` — FOUND
- `tests/invariants/conftest.py` — FOUND
- `tests/invariants/test_importlinter_contract.py` — FOUND
- `tests/invariants/test_importlinter_coverage.py` — FOUND
- `tests/invariants/test_holdings_isolation.py` — FOUND
- `tests/integration/__init__.py` — FOUND
- `tests/integration/conftest.py` — FOUND
- `tests/integration/test_socket_escape_hatch.py` — FOUND
- `pyproject.toml` (modified) — FOUND

Commits confirmed:
- `b4be46a` (Task 1: importlinter contract) — FOUND
- `f32a5dc` (Task 2: canary + integration conftest) — FOUND

## Next Phase Readiness

- Phase 38 (market data providers): yfinance/RSS real providers can go into `tests/integration/` and will automatically receive `enable_socket` from the auto-marker
- Phase 41 (advisory pipeline): canary is scaffolded and ready — flip from SCAFFOLDED to ACTIVE by replacing `_minimal_simulation_body` with the real `synthesize()` call wired to the capture fixtures
- All Phase 37 ISOL requirements (ISOL-01 through ISOL-07) are now landed across Plans 01-04

---
*Phase: 37-isolation-foundation-provider-scaffolding*
*Completed: 2026-04-18*
