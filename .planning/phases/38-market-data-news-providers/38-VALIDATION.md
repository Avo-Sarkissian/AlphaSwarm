---
phase: 38
slug: market-data-news-providers
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-18
---

# Phase 38 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x + pytest-asyncio (asyncio_mode=auto) |
| **Config file** | `pyproject.toml` §[tool.pytest.ini_options] |
| **Quick run command** | `uv run pytest tests/test_yfinance_provider.py tests/test_rss_provider.py -x -q` |
| **Full suite command** | `uv run pytest -x -q` |
| **Integration run command** | `uv run pytest tests/integration/test_market_data_integration.py tests/integration/test_rss_integration.py -x -q` |
| **Estimated runtime** | ~5s (unit), ~15s (integration, network-dependent) |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_yfinance_provider.py tests/test_rss_provider.py -x -q`
- **After every plan wave:** Run `uv run pytest -x -q`
- **Before `/gsd-verify-work`:** Full suite must be green; `uv run lint-imports` must exit 0
- **Max feedback latency:** ~5 seconds (unit only)

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 38-01-01 | 01 | 0 | INGEST-01 | — | N/A | lint | `uv run lint-imports` | ❌ W0 | ⬜ pending |
| 38-01-02 | 01 | 1 | INGEST-01 | — | N/A | unit | `uv run pytest tests/test_yfinance_provider.py::test_get_prices_returns_market_slices -xq` | ❌ W0 | ⬜ pending |
| 38-01-03 | 01 | 1 | INGEST-01 | — | N/A | unit | `uv run pytest tests/test_yfinance_provider.py::test_get_prices_fetch_failed_on_exception -xq` | ❌ W0 | ⬜ pending |
| 38-01-04 | 01 | 1 | INGEST-01 | — | N/A | unit | `uv run pytest tests/test_yfinance_provider.py::test_decimal_precision_not_float -xq` | ❌ W0 | ⬜ pending |
| 38-01-05 | 01 | 1 | INGEST-01 | — | N/A | unit | `uv run pytest tests/test_yfinance_provider.py -xq` | ❌ W0 | ⬜ pending |
| 38-02-01 | 02 | 1 | INGEST-02 | — | N/A | unit | `uv run pytest tests/test_rss_provider.py::test_get_headlines_returns_news_slices -xq` | ❌ W0 | ⬜ pending |
| 38-02-02 | 02 | 1 | INGEST-02 | — | N/A | unit | `uv run pytest tests/test_rss_provider.py::test_get_headlines_fetch_failed_on_exception -xq` | ❌ W0 | ⬜ pending |
| 38-02-03 | 02 | 1 | INGEST-02 | — | N/A | unit | `uv run pytest tests/test_rss_provider.py::test_entity_filtering -xq` | ❌ W0 | ⬜ pending |
| 38-02-04 | 02 | 1 | INGEST-02 | — | N/A | unit | `uv run pytest tests/test_rss_provider.py::test_url_routing_ticker_vs_topic -xq` | ❌ W0 | ⬜ pending |
| 38-02-05 | 02 | 1 | INGEST-02 | — | N/A | unit | `uv run pytest tests/test_rss_provider.py -xq` | ❌ W0 | ⬜ pending |
| 38-03-01 | 03 | 2 | INGEST-01, INGEST-02 | — | N/A | integration | `uv run pytest tests/integration/test_market_data_integration.py -xq` | ❌ W0 | ⬜ pending |
| 38-03-02 | 03 | 2 | INGEST-01, INGEST-02 | — | N/A | integration | `uv run pytest tests/integration/test_rss_integration.py -xq` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `pyproject.toml` — add `yfinance>=0.2.54` and `feedparser>=6.0.11` to `[project] dependencies`
- [ ] `pyproject.toml [tool.importlinter] source_modules` — add `alphaswarm.ingestion.yfinance_provider` and `alphaswarm.ingestion.rss_provider`
- [ ] `src/alphaswarm/ingestion/yfinance_provider.py` — stub module (class skeleton only)
- [ ] `src/alphaswarm/ingestion/rss_provider.py` — stub module (class skeleton only)
- [ ] `src/alphaswarm/ingestion/__init__.py` — add exports for `YFinanceMarketDataProvider` and `RSSNewsProvider`
- [ ] `tests/test_yfinance_provider.py` — test file with placeholder test (collection must pass)
- [ ] `tests/test_rss_provider.py` — test file with placeholder test (collection must pass)
- [ ] `tests/integration/test_market_data_integration.py` — stub integration test
- [ ] `tests/integration/test_rss_integration.py` — stub integration test
- [ ] `uv run lint-imports` exits 0 after source_modules update

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Yahoo Finance RSS returns real headlines for AAPL | INGEST-02 | Network-dependent, requires human inspection of content quality | Run integration test, inspect returned headlines list is non-empty |
| Google News RSS returns relevant headlines for "EV battery" | INGEST-02 | Content relevance is subjective | Run integration test, inspect headlines contain EV-related text |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
