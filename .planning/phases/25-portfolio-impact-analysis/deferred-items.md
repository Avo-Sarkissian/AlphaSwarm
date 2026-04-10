# Phase 25 Deferred Items

Pre-existing issues discovered during plan 25-01 execution that are out of scope.

## Pre-existing Test Failures (Out of Scope)

### tests/test_graph_integration.py::test_ensure_schema_idempotent

**Observed during:** Plan 25-01 Task 2 full-suite verification
**Error:** `RuntimeError: Task <Task pending ...> got Future <Future pending> attached to a different loop`
**Location:** `neo4j/_async_compat/shims/__init__.py:38` → `asyncio/streams.py:526`
**Root cause:** Pre-existing Neo4j async driver / pytest-asyncio event loop lifecycle issue in the integration test. Has no relationship to `src/alphaswarm/portfolio.py`, `src/alphaswarm/report.py`, `src/alphaswarm/templates/report/10_portfolio_impact.j2`, or `tests/test_portfolio.py`.
**Impact on plan:** None — excluded from Plan 01 verification. The plan's in-scope tests (`tests/test_portfolio.py` and `tests/test_report.py`) all pass.
**Proposed owner:** Future infrastructure phase or targeted debug session.
