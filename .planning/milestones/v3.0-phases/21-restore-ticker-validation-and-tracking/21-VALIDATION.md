---
phase: 21
slug: restore-ticker-validation-and-tracking
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-08
---

# Phase 21 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x + pytest-asyncio 0.24+ |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` — `asyncio_mode = "auto"` |
| **Quick run command** | `uv run pytest tests/test_ticker_validator.py tests/test_parsing.py -q` |
| **Full suite command** | `uv run pytest -q` |
| **Estimated runtime** | ~15 seconds (quick), ~30 seconds (full) |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_ticker_validator.py tests/test_parsing.py -q`
- **After every plan wave:** Run `uv run pytest -q`
- **Before `/gsd-verify-work`:** Full suite must be green (baseline: 616 passed, 15 errors are pre-existing Neo4j integration failures — acceptable)
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 21-01-01 | 01 | 0 | TICK-02 | — | N/A | unit | `uv run pytest tests/test_ticker_validator.py -q` | ❌ W0 | ⬜ pending |
| 21-01-02 | 01 | 1 | TICK-02 | — | Invalid symbols rejected with warning | unit | `uv run pytest tests/test_ticker_validator.py::test_validate_returns_true_for_valid_symbol -x` | ❌ W0 | ⬜ pending |
| 21-01-03 | 01 | 1 | TICK-02 | — | Case-insensitive SEC lookup | unit | `uv run pytest tests/test_ticker_validator.py::test_validate_case_insensitive -x` | ❌ W0 | ⬜ pending |
| 21-01-04 | 01 | 1 | TICK-02 | — | CDN unreachable → validator returns None gracefully | unit | `uv run pytest tests/test_ticker_validator.py::test_get_ticker_validator_returns_none_on_connect_error -x` | ❌ W0 | ⬜ pending |
| 21-01-05 | 01 | 2 | TICK-02 | — | Invalid symbol dropped with reason="invalid" | unit | `uv run pytest tests/test_parsing.py -k "drop" -x` | ❌ W0 | ⬜ pending |
| 21-01-06 | 01 | 2 | TICK-03 | — | Top-3 cap: excess tickers dropped with reason="cap" | unit | `uv run pytest tests/test_parsing.py::test_parse_seed_tickers_capped_at_3 -x` | ✅ | ⬜ pending |
| 21-01-07 | 01 | 2 | TICK-03 | — | ParsedSeedResult.dropped_tickers populated correctly | unit | `uv run pytest tests/test_parsing.py -k "dropped" -x` | ❌ W0 | ⬜ pending |
| 21-01-08 | 01 | 3 | TICK-03 | — | CLI displays dropped tickers section when present | unit | `uv run pytest tests/test_cli.py -k "dropped" -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_ticker_validator.py` — 325-line file deleted by commit `7ba7efa`; restore verbatim from git history — covers TICK-02 (15 tests across 5 categories)
- [ ] New tests in `tests/test_parsing.py` — `dropped_tickers` field populated correctly for "invalid" and "cap" reason paths (TICK-02 + TICK-03 integration)
- [ ] New tests in `tests/test_cli.py` — `_print_injection_summary` displays dropped-ticker section when `parsed_result.dropped_tickers` is non-empty (TICK-03)

*Existing pytest infrastructure (asyncio_mode=auto, shared fixtures) covers all other requirements.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `uv run python -m alphaswarm inject-seed` end-to-end with real SEC file | TICK-02/TICK-03 | Requires Ollama running locally | Run `uv run python -m alphaswarm inject-seed "AAPL quarterly beat"` — verify ticker count and no crash |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
