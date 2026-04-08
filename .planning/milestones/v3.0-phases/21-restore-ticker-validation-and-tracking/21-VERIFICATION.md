---
phase: 21-restore-ticker-validation-and-tracking
verified: 2026-04-08T05:00:00Z
status: passed
score: 5/5 must-haves verified
re_verification: false
---

# Phase 21: Restore Ticker Validation and Tracking — Verification Report

**Phase Goal:** Surgically restore SEC ticker validation and dropped-ticker tracking deleted wholesale by commit 7ba7efa. All deleted code recovered verbatim from git history (commits 7ba7efa, 53bf186, 413d382). Close requirements TICK-02 and TICK-03.
**Verified:** 2026-04-08T05:00:00Z
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | parse_seed_event() rejects an invalid ticker symbol and records it in dropped_tickers with reason='invalid' | VERIFIED | test_parse_seed_event_drops_invalid_ticker passes; parsing.py lines 231-234 implement validation callback path |
| 2 | parse_seed_event() caps at 3 tickers and records excess symbols in dropped_tickers with reason='cap' | VERIFIED | test_parse_seed_event_dropped_tickers_cap_reason passes; parsing.py lines 239-242 implement cap+drop tracking |
| 3 | The CLI injection summary displays a Tickers count line, a ticker table, and a Dropped Tickers section when dropped_tickers is non-empty | VERIFIED | test_print_injection_summary_shows_dropped_tickers passes; cli.py lines 80, 91-98, 100-104 implement all three sections |
| 4 | get_ticker_validator() returns None gracefully when the SEC CDN is unreachable, allowing parsing to proceed without validation | VERIFIED | test_get_ticker_validator_returns_none_on_connect_error and _on_timeout both pass; ticker_validator.py lines 111-118 implement graceful None return |
| 5 | pyproject.toml already declares yfinance>=1.2.0 (verified, no change required) | VERIFIED | grep confirms "yfinance>=1.2.0" in pyproject.toml — no implementation change needed |

**Score:** 5/5 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/alphaswarm/ticker_validator.py` | Lazy SEC ticker set loader, async downloader, get_ticker_validator() callable factory | VERIFIED | 124 lines, exports get_ticker_validator and ensure_sec_data; module-level _ticker_set cache present at line 24 |
| `src/alphaswarm/types.py` | ParsedSeedResult with dropped_tickers field | VERIFIED | Line 153: `dropped_tickers: tuple[dict[str, str], ...] = ()` as third field; field order guard passes |
| `src/alphaswarm/parsing.py` | _try_parse_seed_json with SEC validation callback, parse_seed_event with ticker_validator param | VERIFIED | Callable imported at line 17; _try_parse_seed_json signature at line 199 accepts ticker_validator; parse_seed_event at line 258 accepts ticker_validator |
| `src/alphaswarm/seed.py` | inject_seed wired to get_ticker_validator, extended log with dropped_ticker_count | VERIFIED | Line 14 imports get_ticker_validator; line 89 awaits it; line 90 passes to parse_seed_event; lines 118-119 log ticker_count and dropped_ticker_count |
| `src/alphaswarm/cli.py` | _print_injection_summary displaying ticker table and dropped-ticker section | VERIFIED | Lines 80, 91-98, 100-104 implement Tickers count, ticker table, and Dropped Tickers section respectively |
| `tests/test_ticker_validator.py` | 16-test suite covering TICK-02 validator behaviors | VERIFIED | 16 tests collected and all 16 pass; includes autouse reset_ticker_cache fixture |
| `tests/test_parsing.py` | New tests for dropped_tickers invalid and cap paths | VERIFIED | Lines 587-636 contain both new tests; both pass |
| `tests/test_cli.py` | New test for CLI dropped-ticker display | VERIFIED | Lines 953-978 contain the new test; it passes |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `src/alphaswarm/seed.py` | `src/alphaswarm/ticker_validator.py` | get_ticker_validator() awaited before parse_seed_event call | WIRED | `from alphaswarm.ticker_validator import get_ticker_validator` at line 14; `validator = await get_ticker_validator()` at line 89 |
| `src/alphaswarm/parsing.py` | ticker_validator callback | _try_parse_seed_json receives ticker_validator parameter and calls it per symbol | WIRED | Lines 231-234: `if ticker_validator and not ticker_validator(ticker.symbol)` correctly guards each candidate ticker |
| `src/alphaswarm/cli.py` | parsed_result.dropped_tickers | _print_injection_summary iterates dropped_tickers when non-empty | WIRED | Lines 100-104: `if parsed_result.dropped_tickers:` guards the section; iterates and prints symbol + reason |

---

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `cli.py _print_injection_summary` | parsed_result.dropped_tickers | parse_seed_event() via seed.py inject_seed() | Yes — populated by validation and cap logic in _try_parse_seed_json | FLOWING |
| `parsing.py _try_parse_seed_json` | dropped list | ticker_validator callback result + all_tickers length check | Yes — real comparison against SEC symbol set (or None for graceful skip) | FLOWING |

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| 16 ticker_validator tests pass | uv run python -m pytest tests/test_ticker_validator.py -v | 16 passed in 0.06s | PASS |
| 2 new parsing dropped_tickers tests pass | uv run python -m pytest tests/test_parsing.py -k "drop or dropped" | 2 passed | PASS |
| 1 new CLI dropped-ticker test passes | uv run python -m pytest tests/test_cli.py -k "dropped" | 1 passed | PASS |
| Full targeted suite (95 tests) | uv run python -m pytest tests/test_ticker_validator.py tests/test_parsing.py tests/test_cli.py -q | 95 passed in 0.11s | PASS |
| Full suite baseline preserved | uv run python -m pytest -q | 635 passed, 15 pre-existing Neo4j errors | PASS |
| Import smoke test + field order guard | uv run python -c "... assert fields == ['seed_event', 'parse_tier', 'dropped_tickers']" | "All imports OK, field order correct" | PASS |
| yfinance>=1.2.0 in pyproject.toml | grep "yfinance" pyproject.toml | "yfinance>=1.2.0" confirmed | PASS |

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|---------|
| TICK-02 | 21-01-PLAN.md | SEC ticker validation: invalid symbols rejected via company_tickers.json symbol table | SATISFIED | ticker_validator.py provides get_ticker_validator(); 16 tests cover all validation paths including lazy cache, case-insensitive lookup, graceful CDN degradation |
| TICK-03 | 21-01-PLAN.md | Dropped-ticker tracking: excess/invalid tickers recorded with reason in ParsedSeedResult.dropped_tickers | SATISFIED | types.py has dropped_tickers field; parsing.py populates it for both 'invalid' and 'cap' reasons; cli.py displays the section |

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| None found | — | — | — | — |

No TODO/FIXME/placeholder comments, empty handlers, or hardcoded empty returns found in any modified file. The ticker_validator.py returns None intentionally on CDN failure as a documented graceful-degradation path — this is not a stub; parse_seed_event correctly handles None by skipping validation.

---

### Human Verification Required

**1. End-to-end inject-seed with real SEC data file**

**Test:** With Ollama running locally, place a real `data/sec_tickers.json` file from the SEC CDN and run `uv run python -m alphaswarm inject "Apple is acquiring Tesla"`.
**Expected:** The injection summary shows a Tickers count of 2 (AAPL, TSLA), a ticker table with both symbols, and no Dropped Tickers section (both are valid SEC symbols).
**Why human:** Requires a live Ollama instance and the real SEC data file; cannot be verified without running the LLM inference pipeline.

**2. Graceful CDN degradation in fresh environment**

**Test:** Remove `data/sec_tickers.json` and run inject-seed while the SEC CDN is blocked (e.g., via `/etc/hosts`).
**Expected:** The CLI proceeds without crashing; log contains `sec_validation_unavailable` warning; all extracted tickers are kept (no validation applied).
**Why human:** Requires network manipulation and a live Ollama instance.

---

### Gaps Summary

No gaps. All five observable truths are verified, all eight required artifacts exist and are substantive, all three key links are wired and data flows through them, both requirements (TICK-02, TICK-03) are satisfied, and the full test suite passes with 635 tests and no new failures beyond the 15 pre-existing Neo4j integration errors.

One minor deviation from the PLAN is worth noting: the PLAN specified a 15-test suite for test_ticker_validator.py but the actual implementation contains 16 tests (the SUMMARY correctly documents 16). The additional test (`test_download_sec_tickers_catches_timeout_and_reraises`) is an improvement over the plan — it closes an extra coverage gap and all 16 pass.

---

_Verified: 2026-04-08T05:00:00Z_
_Verifier: Claude (gsd-verifier)_
