---
phase: 18-agent-context-enrichment-and-enhanced-decisions
plan: 01
subsystem: enrichment, parsing, types
tags: [pydantic, structlog, market-data, prompt-engineering, bracket-slicing]

# Dependency graph
requires:
  - phase: 17-market-data-pipeline
    provides: MarketDataSnapshot, ExtractedTicker, SeedEvent.tickers field
provides:
  - TickerDecision model for per-ticker directional decisions
  - AgentDecision.ticker_decisions field (backward-compatible)
  - enrichment.py with format_market_block and build_enriched_user_message
  - Lenient ticker_decisions parse path (_lenient_parse_ticker_decisions)
  - Orchestrator prompt ticker extraction (SeedEvent.tickers population)
  - Updated JSON_OUTPUT_INSTRUCTIONS with ticker_decisions schema
affects: [18-02-PLAN, 18-03-PLAN, worker, simulation]

# Tech tracking
tech-stack:
  added: []
  patterns: [bracket-slice-formatting, lenient-nested-field-parsing, budget-capped-headline-injection]

key-files:
  created:
    - src/alphaswarm/enrichment.py
    - tests/test_types.py
    - tests/test_enrichment.py
  modified:
    - src/alphaswarm/types.py
    - src/alphaswarm/config.py
    - src/alphaswarm/parsing.py
    - src/alphaswarm/seed.py
    - tests/test_parsing.py

key-decisions:
  - "TickerDecision.direction reuses SignalType enum (D-08) -- avoids new enum, parse_error dropped by lenient parser"
  - "Macro bracket receives Earnings/Insider slice per locked D-04 decision, resolving ROADMAP phrasing ambiguity"
  - "Headline injection is budget-capped: store up to 10, inject only what fits within bracket char cap"
  - "Lenient parse path pops ticker_decisions from dict, validates base AgentDecision separately, then merges back"

patterns-established:
  - "Bracket-slice formatting: 3 frozen bracket groups map to 3 private formatters with per-bracket char caps"
  - "Lenient nested field parsing: pop problematic field, validate base model, leniently parse popped field, merge via model_copy"
  - "Budget-capped headline injection: compute remaining char budget after structured fields, distribute across tickers"

requirements-completed: [DECIDE-01, DECIDE-02, ENRICH-01, ENRICH-02]

# Metrics
duration: 8min
completed: 2026-04-07
---

# Phase 18 Plan 01: Agent Context Enrichment Foundations Summary

**TickerDecision model with lenient parsing, bracket-specific market data enrichment module, and seed-prompt ticker extraction wiring**

## Performance

- **Duration:** 8 min
- **Started:** 2026-04-07T13:46:20Z
- **Completed:** 2026-04-07T13:54:15Z
- **Tasks:** 2
- **Files modified:** 8

## Accomplishments
- Created TickerDecision model and extended AgentDecision with backward-compatible ticker_decisions field
- Built enrichment.py with 3 bracket-specific formatters (Technicals/Fundamentals/Earnings-Insider) and budget-capped headline injection
- Wired ticker extraction into ORCHESTRATOR_SYSTEM_PROMPT and _try_parse_seed_json so SeedEvent.tickers is finally populated (resolving Codex blocker #3)
- Added lenient ticker_decisions parse path that drops malformed entries without collapsing to PARSE_ERROR (resolving Codex blocker #4)
- Updated JSON_OUTPUT_INSTRUCTIONS with ticker_decisions schema showing only buy/sell/hold directions
- Added 22 new tests (6 types, 10 parsing, 12 enrichment) -- 560 total tests pass

## Task Commits

Each task was committed atomically:

1. **Task 1: TickerDecision model, AgentDecision extension, ticker extraction in seed prompt, and parse robustness** - `f977fb7` (feat)
2. **Task 2: enrichment.py module with bracket-specific formatting and JSON schema update** - `75b6d88` (feat)

_Both tasks followed TDD flow (RED: failing tests, GREEN: implementation)_

## Files Created/Modified
- `src/alphaswarm/types.py` - Added TickerDecision model, AgentDecision.ticker_decisions field
- `src/alphaswarm/enrichment.py` - New module: format_market_block, build_enriched_user_message, bracket slice constants
- `src/alphaswarm/config.py` - Updated JSON_OUTPUT_INSTRUCTIONS with ticker_decisions schema
- `src/alphaswarm/parsing.py` - Added _lenient_parse_ticker_decisions, _try_lenient_agent_parse, ExtractedTicker import, ticker parsing in _try_parse_seed_json
- `src/alphaswarm/seed.py` - Updated ORCHESTRATOR_SYSTEM_PROMPT with ticker extraction instructions
- `tests/test_types.py` - New: 6 tests for TickerDecision and AgentDecision.ticker_decisions
- `tests/test_parsing.py` - Extended: 10 new tests for ticker_decisions parsing and seed ticker extraction
- `tests/test_enrichment.py` - New: 12 tests for enrichment module

## Decisions Made
- TickerDecision.direction reuses SignalType (includes parse_error) but the prompt schema only shows buy/sell/hold -- if LLM emits parse_error, lenient parser drops that entry
- Macro bracket placed in Earnings/Insider slice per locked D-04 decision, not in a separate "sector-level" slice
- Headline injection uses two-pass approach: first format structured fields, then distribute remaining char budget across tickers with headlines
- Lenient parse helper extracted to _try_lenient_agent_parse() shared by all 3 parse tiers, avoiding code duplication

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- Worktree branch needed reset to correct base commit (7333195) before starting -- handled in initialization
- Pre-existing Neo4j integration test failure (test_graph_integration.py) due to no running Docker container -- not related to changes, excluded from verification

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- enrichment.py ready for 18-02 to wire format_market_block into worker agent prompt assembly
- TickerDecision model ready for 18-03 to aggregate per-ticker decisions in consensus
- SeedEvent.tickers now populated, enabling market data pipeline to activate (Phase 17 fetch_market_data guard: `if parsed_result.seed_event.tickers:`)

---
*Phase: 18-agent-context-enrichment-and-enhanced-decisions*
*Completed: 2026-04-07*
