---
phase: 17
slug: market-data-pipeline
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-06
---

# Phase 17 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.0+ with pytest-asyncio 0.24.0+ |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `uv run pytest tests/test_market_data.py -x -q` |
| **Full suite command** | `uv run pytest tests/ -x -q` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_market_data.py -x -q`
- **After every plan wave:** Run `uv run pytest tests/ -x -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 17-01-01 | 01 | 0 | DATA-01 | — | N/A | unit | `uv run pytest tests/test_market_data.py::test_snapshot_model_valid -x` | ❌ W0 | ⬜ pending |
| 17-01-02 | 01 | 1 | DATA-01 | — | N/A | unit | `uv run pytest tests/test_market_data.py::test_fetch_yfinance_returns_snapshot -x` | ❌ W0 | ⬜ pending |
| 17-01-03 | 01 | 1 | DATA-01 | — | N/A | unit | `uv run pytest tests/test_market_data.py::test_parallel_fetch_all_tickers -x` | ❌ W0 | ⬜ pending |
| 17-02-01 | 02 | 2 | DATA-02 | — | Degraded snapshot on failure, not abort | unit | `uv run pytest tests/test_market_data.py::test_av_fallback_on_yfinance_failure -x` | ❌ W0 | ⬜ pending |
| 17-02-02 | 02 | 2 | DATA-02 | — | N/A | unit | `uv run pytest tests/test_market_data.py::test_degraded_snapshot_both_fail -x` | ❌ W0 | ⬜ pending |
| 17-02-03 | 02 | 2 | DATA-02 | — | N/A | unit | `uv run pytest tests/test_market_data.py::test_av_skipped_no_key -x` | ❌ W0 | ⬜ pending |
| 17-03-01 | 03 | 3 | DATA-04 | — | N/A | unit | `uv run pytest tests/test_market_data.py::test_cache_write_creates_file -x` | ❌ W0 | ⬜ pending |
| 17-03-02 | 03 | 3 | DATA-04 | — | N/A | unit | `uv run pytest tests/test_market_data.py::test_cache_hit_within_ttl -x` | ❌ W0 | ⬜ pending |
| 17-03-03 | 03 | 3 | DATA-04 | — | N/A | unit | `uv run pytest tests/test_market_data.py::test_cache_miss_expired_ttl -x` | ❌ W0 | ⬜ pending |
| 17-03-04 | 03 | 3 | DATA-04 | — | N/A | unit | `uv run pytest tests/test_market_data.py::test_cache_hit_logged -x` | ❌ W0 | ⬜ pending |
| 17-04-01 | 04 | 4 | DATA-01 | — | N/A | integration | `uv run pytest tests/test_graph.py::test_create_ticker_with_market_data -x` | ❌ W0 | ⬜ pending |
| 17-04-02 | 04 | 4 | DATA-01 | — | N/A | integration | `uv run pytest tests/test_simulation.py::test_market_data_fetched_before_round1 -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `uv add yfinance>=1.2.0` — yfinance not in project venv (prerequisite for all implementation)
- [ ] `tests/test_market_data.py` — stubs for DATA-01, DATA-02, DATA-04 (12 tests); mock yfinance `Ticker` via `asyncio.to_thread`, mock httpx for AV calls
- [ ] `tests/conftest.py` — shared fixtures (if not already present)

*Wave 0 must complete before any implementation wave begins.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Degraded data warning visible in CLI output | DATA-02 (SC-2) | Requires running full simulation and reading terminal output | Run simulation with a ticker that fails both yfinance + AV; verify structlog WARNING appears before Round 1 |
| Cache-hit indicator visible in logs | DATA-04 (SC-4) | Requires two successive simulation runs | Run same simulation twice within 1 hour; second run should log `cache_hit=True` at INFO level for each ticker |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
