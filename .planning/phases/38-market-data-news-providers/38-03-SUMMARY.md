---
phase: 38
plan: 03
subsystem: ingestion
tags: [integration-tests, real-network, yfinance, rss, feedparser, enable-socket, path-invariant]
dependency_graph:
  requires:
    - alphaswarm.ingestion.YFinanceMarketDataProvider (Phase 38-01)
    - alphaswarm.ingestion.RSSNewsProvider (Phase 38-02)
    - tests/integration/conftest.py enable_socket auto-marker (Phase 37-06)
    - pytest-socket --disable-socket global gate (Phase 37)
  provides:
    - tests/integration/test_yfinance_provider_live.py (6 real-network tests covering INGEST-01 end-to-end)
    - tests/integration/test_rss_provider_live.py (6 real-network tests covering INGEST-02 end-to-end)
  affects:
    - tests/integration/ directory (grows from 1 to 3 test modules; 1 smoke test -> 13 tests total)
tech_stack:
  added:
    - pytest-socket enable_socket escape hatch exercised against real Yahoo + Google News (no new production dependencies)
  patterns:
    - "Real-network integration tests live under tests/integration/ so the path-based conftest auto-applies enable_socket — no decorators per test"
    - "Loose shape assertions (staleness='fresh', price > 0, len >= 1) instead of exact-content — survive real-network variability"
    - "Tolerant assertion for delisted ticker: accept EITHER fetch_failed OR structurally valid empty slice — survives yfinance error-semantic drift (Codex HIGH)"
    - "Path-invariant self-check per test module — fails loud if module is relocated outside tests/integration/ (Codex MEDIUM)"
key_files:
  created:
    - tests/integration/test_yfinance_provider_live.py
    - tests/integration/test_rss_provider_live.py
    - .planning/phases/38-market-data-news-providers/38-03-SUMMARY.md
    - .planning/phases/38-market-data-news-providers/deferred-items.md
  modified: []
decisions:
  - "D-12 integration location honored: both test modules live under tests/integration/ so the Phase 37 conftest hook auto-applies enable_socket without any per-test decorators"
  - "Codex HIGH (flake tolerance) — delisted ticker assertion accepts EITHER staleness='fetch_failed' (current yfinance behavior: raises KeyError('currentTradingPeriod')) OR staleness='fresh' with price is None (hypothetical future yfinance release that returns empty slice). The D-19 never-raise contract is the invariant under test, not a specific error class."
  - "Codex MEDIUM (path invariant) — every new integration test module includes test_test_module_lives_under_tests_integration that asserts __file__ resolves inside tests/integration/. If the module is ever relocated, this assertion fires immediately rather than the enable_socket auto-marker silently ceasing to apply."
  - "No explicit @pytest.mark.enable_socket decorators — the conftest auto-marker is the single source of truth (verified by acceptance-criterion negative grep `! grep -q 'pytest.mark.enable_socket'`)."
  - "Content assertions limited to staleness + shape (Decimal type, price > 0, len >= 1); NEVER exact price or headline text — live-data tests must not be brittle against daily market movement"
  - "Yahoo RSS ticker (Open Question 2): 0 entries on HTTP 200 is a successful fetch (staleness='fresh'), not a failure. The topic test (EV battery via Google News) is the aggregation-depth test; the ticker test is the success-path-even-if-empty test."
  - "Pitfall 4 real-world regression guard: Yahoo 429 without UA is an upstream behavior we rely on; test_rss_real_user_agent_prevents_yahoo_429 proves the installed UA works against the real backend (not just unit-mocked httpx)"
metrics:
  started_at: "2026-04-18T22:44:00Z"
  completed_at: "2026-04-18T22:50:39Z"
  duration_minutes: 7
  tasks_completed: 2
  tests_added: 12
  integration_suite_total: 13
---

# Phase 38 Plan 03: Integration Tests Summary

## One-liner

Real-network integration tests for `YFinanceMarketDataProvider` and `RSSNewsProvider` — 12 new tests under `tests/integration/` exercise live Yahoo Finance (price + fundamentals), live Yahoo Finance RSS, and live Google News RSS, with loose shape assertions (staleness='fresh', type/positivity) tolerant of yfinance semantic drift and 0-entry Yahoo responses; each module includes a path-invariant self-check (Codex MEDIUM) that fails loud if relocated outside `tests/integration/`.

## What Shipped

### Tests (created)
- `tests/integration/test_yfinance_provider_live.py` (146 lines, 6 tests)
  - `test_yfinance_real_fetch_aapl_returns_fresh_slice` — INGEST-01 end-to-end success path
  - `test_yfinance_real_fetch_unknown_ticker_returns_fetch_failed` — Pitfall 1 / D-19 regression guard with **tolerant outcome** (accepts either `fetch_failed` or structurally valid empty slice; documents ZZZZNOTREAL literal choice)
  - `test_yfinance_real_batch_with_good_and_bad_ticker_returns_both_slices` — D-05 per-ticker error isolation against live backend
  - `test_yfinance_real_fetch_fundamentals_returns_at_least_one_field` — D-06 `.info` mapping path (AAPL has trailingPE / marketCap)
  - `test_yfinance_real_empty_list_returns_empty_dict` — Pitfall 9 short-circuit confirmed under enable_socket
  - `test_test_module_lives_under_tests_integration` — Codex MEDIUM path-invariant self-check

- `tests/integration/test_rss_provider_live.py` (129 lines, 6 tests)
  - `test_rss_real_fetch_ticker_entity_returns_fresh_slice` — Yahoo RSS routing (AAPL) — **staleness='fresh' only** per Research Open Q 2 (0 entries can be legitimate)
  - `test_rss_real_fetch_topic_entity_returns_fresh_slice_with_headlines` — Google News routing (EV battery) — fresh + ≥1 headline + case-insensitive entity filter match on every headline (D-03)
  - `test_rss_real_fetch_geopolitical_entity_returns_fresh_slice` — `quote_plus` handles hyphen-shaped realistic seed-rumor entities
  - `test_rss_real_user_agent_prevents_yahoo_429` — Pitfall 4 real-world regression guard
  - `test_rss_real_mixed_batch_returns_fresh_for_all_entities` — Dual-source routing through shared `httpx.AsyncClient` in one `asyncio.gather`
  - `test_test_module_lives_under_tests_integration` — Codex MEDIUM path-invariant self-check

### Production code
**Zero modifications to production code.** No changes to `src/`, no changes to `tests/integration/conftest.py` (Phase 37 set it up), no changes to `pyproject.toml`, no new dependencies.

## Decisions Implemented

| Decision | Realization |
|----------|-------------|
| D-12 integration tests under `tests/integration/` | Both files placed under `tests/integration/`; conftest auto-applies `enable_socket`; no `@pytest.mark.enable_socket` decorators in either file |
| D-05 real-environment error isolation | `test_yfinance_real_batch_with_good_and_bad_ticker_returns_both_slices` confirms one bad ticker does not fail the batch against real Yahoo |
| D-19 real-environment never-raise | `test_yfinance_real_fetch_unknown_ticker_returns_fetch_failed` uses a TOLERANT assertion (`fetch_failed` OR structurally valid empty slice) — the contract under test is "never raises", not "raises a specific class" |
| D-06 `.info` mapping path | `test_yfinance_real_fetch_fundamentals_returns_at_least_one_field` asserts at least one of (pe_ratio, eps, market_cap) is a populated Decimal for AAPL |
| D-03 case-insensitive substring filter | `test_rss_real_fetch_topic_entity_returns_fresh_slice_with_headlines` asserts every returned headline contains `"ev battery"` (case-insensitive) |
| Research Open Q 2 (Yahoo 0-entries is fresh) | `test_rss_real_fetch_ticker_entity_returns_fresh_slice` asserts staleness='fresh' only — does NOT assert `len(headlines) > 0` |

## Review Fixes Applied (38-REVIEWS)

| Review | Severity | Fix |
|--------|----------|-----|
| **Codex HIGH — flake tolerance on delisted ticker** | HIGH | `test_yfinance_real_fetch_unknown_ticker_returns_fetch_failed` accepts BOTH outcomes: (a) current behavior (`fetch_failed`, price is None — yfinance raises KeyError) and (b) hypothetical future behavior (`fresh`, price is None — yfinance returns empty slice instead). The failure mode is only "slice claims fresh AND price is populated", which would itself be a regression. In-test comment documents the `ZZZZNOTREAL` literal choice and swap instructions if it ever becomes real. |
| **Codex MEDIUM — enable_socket path dependency is silent** | MEDIUM | Each test module contains `test_test_module_lives_under_tests_integration` which resolves `__file__` and asserts `"tests/integration"` is in the path. If someone moves the module outside that directory, the self-check fires immediately. Each module's docstring also explicitly documents the path dependency (see PATH DEPENDENCY section in each docstring). The Codex-suggested "explicit integration marker" was NOT adopted because it would duplicate the conftest's auto-marker logic; we document + self-assert instead. |

## Threat Mitigations Confirmed in Production Environment

| Threat | Confirmed By |
|--------|--------------|
| T-38-01 (URL injection) | `test_rss_real_fetch_geopolitical_entity_returns_fresh_slice` — hyphen-containing entity routes through `quote_plus(entity)` without breaking the Google News URL |
| T-38-03 (DoS via unknown-ticker fetch) | `test_yfinance_real_fetch_unknown_ticker_returns_fetch_failed` — real yfinance does not crash the provider on delisted symbol |
| T-38-11 (Yahoo 429) | `test_rss_real_user_agent_prevents_yahoo_429` — real Yahoo accepts `Mozilla/5.0 AlphaSwarm/6.0` and returns 200 |
| T-38-16 (CI flakiness) | Accepted + mitigated: tolerant assertions, loose shape checks, helpful error messages pointing at probable cause |
| T-38-17 (integration test silently placed outside `tests/integration/`) | Path-invariant self-check per module asserts file location |

## Pitfalls Validated End-to-End

| Pitfall | Validated By |
|---------|-------------|
| 1 — `KeyError('currentTradingPeriod')` on delisted tickers | `test_yfinance_real_fetch_unknown_ticker_returns_fetch_failed` — real yfinance raised the KeyError; D-19 caught it; slice is `fetch_failed` |
| 2 — feedparser sync internal fetcher | `test_rss_real_*` tests all pass — `feedparser.parse(r.text)` only; no URL-to-feedparser path reached |
| 4 — Yahoo 429 without UA | `test_rss_real_user_agent_prevents_yahoo_429` — first-attempt real Yahoo fetch returns 200 with the installed UA |
| 9 — `asyncio.gather(*empty)` | `test_yfinance_real_empty_list_returns_empty_dict` confirms `{}` without touching the network |

## Requirements Satisfied

- **INGEST-01** — end-to-end closed: `YFinanceMarketDataProvider` validated against live Yahoo Finance for success path (AAPL fresh slice), failure path (delisted ticker tolerance), batch isolation (mixed good+bad), fundamentals mapping (real `.info` dict), and empty-input guard.
- **INGEST-02** — end-to-end closed: `RSSNewsProvider` validated against live Yahoo Finance RSS (ticker routing) and live Google News RSS (topic + geopolitical routing + entity substring filter), UA regression guard, and mixed-batch dual-source routing.

## How to Verify

```bash
uv run pytest tests/integration/test_yfinance_provider_live.py -v  # 6 PASSED in ~14s
uv run pytest tests/integration/test_rss_provider_live.py -v       # 6 PASSED in ~3s
uv run pytest tests/integration/ -v                                 # 13 PASSED (new 12 + Phase 37 socket smoke)
uv run pytest tests/test_rss_provider.py tests/test_yfinance_provider.py \
              tests/test_providers.py tests/test_ingestion_types.py \
              tests/invariants/ tests/integration/ -q               # 116 PASSED (ingestion subset)
uv run mypy src/alphaswarm/ingestion/ tests/integration/test_yfinance_provider_live.py \
             tests/integration/test_rss_provider_live.py            # Success
uv run ruff check tests/integration/test_yfinance_provider_live.py \
                  tests/integration/test_rss_provider_live.py       # All checks passed
uv run lint-imports                                                  # Contracts: 1 kept, 0 broken
```

## Deferred Issues (out of scope — NOT caused by Phase 38)

See `.planning/phases/38-market-data-news-providers/deferred-items.md`:
- `tests/test_report.py` — 19 pre-existing failures (ReportAssembler.assemble_html attribute removed; test file not updated). Last touched 2026-04-14 (commit 8acbb91), before Phase 38 planning.
- `tests/test_graph_integration.py` — 1 pre-existing `RuntimeError: Task ... got Future attached to a different loop` (Neo4j integration test; flaky event-loop behavior not caused by Phase 38).

Both are unrelated to Phase 38 changes and are recorded for a future /gsd:quick.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 — Blocking] Plan-provided docstring content conflicted with a plan acceptance criterion**
- **Found during:** Task 1 verification (initial `! grep -q "pytest.mark.enable_socket"` check failed)
- **Issue:** The plan's `<action>` block for Task 1 provided a module docstring containing the literal string ``@pytest.mark.enable_socket`` (as a backticked reference to the conftest auto-marker). But one of the plan's own `<acceptance_criteria>` says `! grep -q "pytest.mark.enable_socket"` — the negative grep cannot distinguish docstring references from code decorators.
- **Fix:** Reworded the docstring intro to say "auto-marked (enable_socket)" instead of "auto-marked \`@pytest.mark.enable_socket\`". Semantics preserved: both files still document the enable_socket dependency (in a full PATH DEPENDENCY paragraph, plus the self-check `test_test_module_lives_under_tests_integration`). The negative grep now passes.
- **Files modified:** `tests/integration/test_yfinance_provider_live.py`, `tests/integration/test_rss_provider_live.py`
- **Commits:** 7b9fb9e (Task 1), c90e1f3 (Task 2)

**2. [Scope boundary] Pre-existing failures discovered during verification**
- **Found during:** Final suite verification (`uv run pytest -x -q`)
- **Issue:** `tests/test_report.py` has 19 pre-existing failures (`ReportAssembler.assemble_html` attribute removed at some prior point; test file not updated). `tests/test_graph_integration.py` has 1 pre-existing flaky Neo4j event-loop failure.
- **Disposition:** Out of scope per executor scope-boundary rule. Neither is caused by Phase 38 changes (Phase 38 added no code in `alphaswarm.report` or `alphaswarm.graph`). Recorded in `.planning/phases/38-market-data-news-providers/deferred-items.md` for a future /gsd:quick.
- **Files modified:** None.

No architectural deviations (Rule 4). No changes to the plan's test semantics.

## Unblocks

- **Phase 38 complete** — INGEST-01 and INGEST-02 are fully validated at both unit and integration levels.
- **Phase 40 (ContextPacket assembly)** — can now wire `YFinanceMarketDataProvider()` and `RSSNewsProvider()` into `ContextPacket.market` and `ContextPacket.news` with confidence that the providers work against real upstreams.

## Self-Check: PASSED

- `tests/integration/test_yfinance_provider_live.py` — FOUND
- `tests/integration/test_rss_provider_live.py` — FOUND
- `.planning/phases/38-market-data-news-providers/38-03-SUMMARY.md` — FOUND (this file)
- `.planning/phases/38-market-data-news-providers/deferred-items.md` — FOUND
- Commit 7b9fb9e (Task 1) — FOUND in `git log`
- Commit c90e1f3 (Task 2) — FOUND in `git log`
- 6/6 `test_yfinance_provider_live.py` tests PASSED against real Yahoo Finance
- 6/6 `test_rss_provider_live.py` tests PASSED against real Yahoo RSS + Google News RSS
- 13/13 `tests/integration/` subset PASSED (new 12 + Phase 37 socket-escape smoke)
- 116/116 ingestion+integration regression subset PASSED
- mypy strict on both new modules + `src/alphaswarm/ingestion/` — Success (6 source files)
- ruff on both new modules — All checks passed
- `lint-imports` — Contracts: 1 kept, 0 broken
- Path-invariant self-check passes in both modules (asserts `"tests/integration"` in `__file__`)
- Negative acceptance criterion `! grep -q "pytest.mark.enable_socket"` PASSES for both modules
- Negative acceptance criterion `! grep -qE "asyncio\.sleep|time\.sleep"` PASSES for both modules
