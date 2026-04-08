---
phase: 16-ticker-extraction
plan: "01"
subsystem: parsing
tags: [ticker-extraction, types, parsing, prompt-engineering, tdd]
dependency_graph:
  requires: []
  provides: [ExtractedTicker-model, SeedEvent.tickers, ParsedSeedResult.dropped_tickers, ticker-parsing-pipeline]
  affects: [seed.py, parsing.py, types.py]
tech_stack:
  added: []
  patterns: [frozen-pydantic-model, 3-tier-parse-fallback, validator-callback-injection]
key_files:
  created:
    - tests/test_ticker_extraction.py
  modified:
    - src/alphaswarm/types.py
    - src/alphaswarm/seed.py
    - src/alphaswarm/parsing.py
decisions:
  - "ExtractedTicker follows frozen Pydantic BaseModel pattern identical to SeedEntity -- no new patterns introduced"
  - "_try_parse_seed_json returns tuple (SeedEvent | None, list[dict]) so caller can collect dropped tickers without a separate data structure"
  - "parse_seed_event threads ticker_validator through all 3 tiers identically -- no tier-specific validator logic"
  - "Dropped tickers use string reason labels ('invalid' | 'cap') matching plan spec; stored as tuple[dict] on ParsedSeedResult for immutability"
metrics:
  duration: "5 min"
  completed: "2026-04-06"
  tasks_completed: 2
  files_modified: 3
  files_created: 1
---

# Phase 16 Plan 01: Ticker Extraction Types and Parsing Infrastructure Summary

**One-liner:** ExtractedTicker frozen Pydantic model, SeedEvent.tickers field, and 3-tier parsing pipeline with SEC validator callback and top-3 relevance cap.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add ExtractedTicker model, SeedEvent.tickers, ParsedSeedResult.dropped_tickers | b3f25e9 | src/alphaswarm/types.py |
| 2 | Expand ORCHESTRATOR_SYSTEM_PROMPT and update parsing pipeline | 66b0684 | src/alphaswarm/seed.py, src/alphaswarm/parsing.py |

**TDD commits:**
- 1791043 — test(16-01): failing tests for Task 1 types (RED)
- b3f25e9 — feat(16-01): Task 1 implementation (GREEN)
- 7df2791 — test(16-01): failing tests for Task 2 parsing and prompt (RED)
- 66b0684 — feat(16-01): Task 2 implementation (GREEN)

## What Was Built

### ExtractedTicker (types.py)

A new frozen Pydantic BaseModel placed immediately after `SeedEntity`. Fields:
- `symbol: str` — ticker symbol (e.g. "AAPL")
- `company_name: str` — full company name
- `relevance: float = Field(ge=0.0, le=1.0)` — centrality to the rumor

Follows the same pattern as `SeedEntity` for consistency.

### SeedEvent.tickers (types.py)

Added `tickers: list[ExtractedTicker] = Field(default_factory=list)` between `entities` and `overall_sentiment`. Defaults to empty list for full backward compatibility — all existing tests pass without modification.

### ParsedSeedResult.dropped_tickers (types.py)

Added `dropped_tickers: tuple[dict[str, str], ...] = ()` to the frozen dataclass. Each entry is `{"symbol": str, "reason": "invalid"|"cap"}`. Defaults to empty tuple for backward compatibility.

### ORCHESTRATOR_SYSTEM_PROMPT (seed.py)

Expanded from entities-only to include a tickers section:
- Instructs LLM to identify publicly traded companies with `symbol`, `company_name`, `relevance` fields
- Restricts to "major US exchanges" to reduce spurious symbols
- Updates JSON schema to `{"entities": [...], "tickers": [...], "overall_sentiment": float}`

### _try_parse_seed_json (parsing.py)

New signature: `(text, original_rumor, ticker_validator=None) -> tuple[SeedEvent | None, list[dict]]`

Logic added after entity parsing:
1. Reads `data.get("tickers", [])` — gracefully handles missing key
2. Validates each ticker via `ExtractedTicker.model_validate()` — skips invalid silently
3. Applies `ticker_validator` callback — drops with `reason="invalid"` if rejected
4. Sorts surviving tickers by `relevance` descending
5. Caps at 3 — drops excess with `reason="cap"`
6. Passes `tickers=all_tickers` to `SeedEvent` constructor

All failure paths return `(None, [])`.

### parse_seed_event (parsing.py)

New signature: `(raw, original_rumor, ticker_validator=None) -> ParsedSeedResult`

Threads `ticker_validator` through all 3 tiers. Collects `dropped` list from each `_try_parse_seed_json` call. Returns `ParsedSeedResult(..., dropped_tickers=tuple(dropped))`. Tier 3 fallback returns `dropped_tickers=()`.

## Test Coverage

16 tests in `tests/test_ticker_extraction.py`:
- 7 type model tests (Task 1)
- 9 parsing and prompt tests (Task 2)

Full suite: 531 tests passing, 0 failures (up from 522 before this plan).

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — all fields are wired. The `ticker_validator` callback defaults to `None` (pass-through, no SEC validation), which is correct: Plan 02 provides the actual SEC validator.

## Self-Check: PASSED

- `tests/test_ticker_extraction.py` — exists and all 16 tests pass
- `src/alphaswarm/types.py` — contains `class ExtractedTicker`, `tickers: list[ExtractedTicker]`, `dropped_tickers: tuple`
- `src/alphaswarm/seed.py` — contains "tickers" in ORCHESTRATOR_SYSTEM_PROMPT
- `src/alphaswarm/parsing.py` — contains `ticker_validator`, `ExtractedTicker`, `reason.*invalid`, `reason.*cap`, `all_tickers[:3]`
- Commits b3f25e9 and 66b0684 verified in git log
