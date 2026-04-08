---
phase: 16
slug: ticker-extraction
status: complete
nyquist_compliant: true
wave_0_complete: true
created: 2026-04-06
---

# Phase 16 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x + pytest-asyncio |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` — `asyncio_mode = "auto"` |
| **Quick run command** | `uv run pytest tests/test_ticker_validator.py tests/test_parsing.py -k "seed" -x -q` |
| **Full suite command** | `uv run pytest tests/ -x -q` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_ticker_validator.py tests/test_parsing.py -k "seed" -x -q`
- **After every plan wave:** Run `uv run pytest tests/ -x -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 16-01-01 | 01 | 0 | TICK-01 | — | N/A | unit | `uv run pytest tests/test_ticker_validator.py::test_load_ticker_set_returns_expected_symbols -x` | ✅ | ✅ green |
| 16-01-02 | 01 | 0 | TICK-01 | — | N/A | unit | `uv run pytest tests/test_ticker_validator.py::test_load_ticker_set_uppercase_conversion -x` | ✅ | ✅ green |
| 16-02-01 | 02 | 1 | TICK-02 | — | Invalid symbols rejected with warning | unit | `uv run pytest tests/test_ticker_validator.py::test_validate_returns_true_for_valid_symbol -x` | ✅ | ✅ green |
| 16-02-02 | 02 | 1 | TICK-02 | — | Case-insensitive SEC lookup | unit | `uv run pytest tests/test_ticker_validator.py::test_validate_case_insensitive -x` | ✅ | ✅ green |
| 16-02-03 | 02 | 1 | TICK-02 | — | Invalid symbol rejected | unit | `uv run pytest tests/test_ticker_validator.py::test_validate_returns_false_for_unknown_symbol -x` | ✅ | ✅ green |
| 16-02-04 | 02 | 1 | TICK-02 | — | CDN unreachable fallback | unit | `uv run pytest tests/test_ticker_validator.py::test_get_ticker_validator_returns_none_on_connect_error -x` | ✅ | ✅ green |
| 16-02-05 | 02 | 1 | TICK-02 | — | Timeout fallback | unit | `uv run pytest tests/test_ticker_validator.py::test_get_ticker_validator_returns_none_on_timeout -x` | ✅ | ✅ green |
| 16-03-01 | 03 | 2 | TICK-03 | — | Tickers extracted from seed | unit | `uv run pytest tests/test_parsing.py::test_parse_seed_with_tickers -x` | ✅ | ✅ green |
| 16-03-02 | 03 | 2 | TICK-03 | — | Top-3 cap enforced | unit | `uv run pytest tests/test_parsing.py::test_parse_seed_tickers_capped_at_3 -x` | ✅ | ✅ green |
| 16-03-03 | 03 | 2 | TICK-03 | — | Invalid ticker dropped | unit | `uv run pytest tests/test_parsing.py::test_parse_seed_event_drops_invalid_ticker -x` | ✅ | ✅ green |
| 16-03-04 | 03 | 2 | TICK-03 | — | Dropped ticker tracking | unit | `uv run pytest tests/test_parsing.py::test_parse_seed_event_dropped_tickers_cap_reason -x` | ✅ | ✅ green |
| 16-04-01 | 03 | 2 | TICK-03 | — | CLI displays dropped tickers | unit | `uv run pytest tests/test_cli.py::test_print_injection_summary_shows_dropped_tickers -x` | ✅ | ✅ green |
| 16-05-01 | 01 | 0 | TICK-01 | — | N/A | integration | `uv run pytest tests/test_seed_pipeline.py -x -q` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] `tests/test_ticker_validator.py` — unit tests for SEC JSON parsing, validation, CDN fallback (TICK-01, TICK-02)
- [x] `tests/test_parsing.py` — seed parsing tests including ticker extraction, cap, and drop tracking (TICK-03)
- [x] `tests/test_cli.py` — CLI injection summary display with dropped tickers (TICK-03)
- [x] `tests/test_seed_pipeline.py` — integration tests for inject pipeline end-to-end (TICK-01)

*Existing pytest + pytest-asyncio infrastructure already covers framework needs.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Full inject-seed pipeline with real Ollama | TICK-01, TICK-03 | Requires live Ollama model loaded | Run `uv run python -m alphaswarm inject-seed "AAPL quarterly beat"` — verify ticker count, extraction, and no crash |
| SEC data download from CDN | TICK-02 | Requires network access to SEC EDGAR | Delete `data/company_tickers.json`, run inject-seed — verify file is re-downloaded and validation works |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 15s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved
