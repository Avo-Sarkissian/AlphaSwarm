---
phase: 17
slug: market-data-pipeline
status: complete
nyquist_compliant: true
wave_0_complete: true
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
| 17-01-01 | 01 | 0 | DATA-01 | — | N/A | unit | `uv run pytest tests/test_market_data.py::TestMarketDataSnapshotModel -x` | ✅ | ✅ green |
| 17-01-02 | 01 | 1 | DATA-01 | — | N/A | unit | `uv run pytest tests/test_market_data.py::TestYfinanceFetch -x` | ✅ | ✅ green |
| 17-02-01 | 02 | 2 | DATA-02 | — | Degraded snapshot on failure, not abort | unit | `uv run pytest tests/test_market_data.py::TestFallbackDegradation -x` | ✅ | ✅ green |
| 17-03-01 | 03 | 3 | DATA-04 | — | N/A | unit | `uv run pytest tests/test_market_data.py::TestDiskCache -x` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] `uv add yfinance>=1.2.0` — yfinance installed in project venv
- [x] `tests/test_market_data.py` — test classes for DATA-01, DATA-02, DATA-04 (TestMarketDataSnapshotModel, TestYfinanceFetch, TestFallbackDegradation, TestDiskCache)
- [x] `tests/conftest.py` — shared fixtures present

*Wave 0 must complete before any implementation wave begins.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Degraded data warning visible in CLI output | DATA-02 (SC-2) | Requires running full simulation and reading terminal output | Run simulation with a ticker that fails both yfinance + AV; verify structlog WARNING appears before Round 1 |
| Cache-hit indicator visible in logs | DATA-04 (SC-4) | Requires two successive simulation runs | Run same simulation twice within 1 hour; second run should log `cache_hit=True` at INFO level for each ticker |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 15s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved
