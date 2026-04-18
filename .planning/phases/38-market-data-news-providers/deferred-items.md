# Phase 38 Deferred Items

Pre-existing failures NOT caused by Phase 38 changes — out of scope per
executor scope boundary. Recorded here so a future phase can pick them up.

## Pre-existing failures (not caused by Phase 38)

1. **tests/test_report.py — 19 failures** (pre-existing, last touched
   2026-04-14 in commit 8acbb91). All failures are of shape:
   `AttributeError: 'ReportAssembler' object has no attribute 'assemble_html'`
   Report module refactored out of test-visible surface; test file not
   updated. Discovered during Phase 38-03 verification. **Not caused by
   Phase 38** — 38-03 only added integration test files under
   tests/integration/ and did not touch alphaswarm.report or tests/test_report.
   Recommendation: dedicated /gsd:quick to align tests/test_report.py with
   the current ReportAssembler surface.

2. **tests/test_graph_integration.py — 1 error** (pre-existing, requires Neo4j
   container plus gets `RuntimeError: Task ... got Future attached to a
   different loop`). Flaky Neo4j event-loop test; not touched by Phase 38.
   Recommendation: revisit in a future Neo4j maintenance pass.

## Phase 38-03 test footprint

- Added: tests/integration/test_yfinance_provider_live.py (6 tests, PASSED)
- Added: tests/integration/test_rss_provider_live.py (6 tests, PASSED)
- Ingestion + invariant + integration subset regression: 116/116 PASSED
