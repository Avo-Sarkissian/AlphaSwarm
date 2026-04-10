---
phase: 25-portfolio-impact-analysis
plan: 01
subsystem: portfolio
tags: [portfolio, schwab, csv-parser, jinja2, typeddict, regex, word-boundary, asyncio]

# Dependency graph
requires:
  - phase: 15-post-simulation-report
    provides: ReportAssembler, ToolObservation, TOOL_TO_TEMPLATE/SECTION_ORDER pattern, template directory
  - phase: 04-neo4j-graph-state
    provides: GraphStateManager.read_entity_impact() async method
provides:
  - src/alphaswarm/portfolio.py — Schwab CSV parser, ticker-entity bridge, TypedDict contracts, TICKER_ENTITY_MAP
  - src/alphaswarm/templates/report/10_portfolio_impact.j2 — markdown template with grouped gap subsections
  - static registration of portfolio_impact in TOOL_TO_TEMPLATE and SECTION_ORDER
  - tests/test_portfolio.py — 73 unit tests covering parser, bridge, template, assembler integration
affects:
  - 25-02 (CLI flag wiring, ReACT system prompt, pre-call determinism path, HTML section)
  - Future report phases that consume portfolio_impact observations

# Tech tracking
tech-stack:
  added: []
  patterns:
    - TypedDict contracts for strict typing of parser/bridge return shapes
    - Word-boundary regex (rf"\\b{re.escape(s)}\\b") to eliminate ticker substring false positives
    - asyncio.to_thread wrapper for blocking stdlib csv.DictReader (CLAUDE.md 100% async constraint)
    - Tie-breaker tuple iteration (HOLD > SELL > BUY) instead of dict-order-dependent max()
    - Privacy-safe structlog logging (aggregate counts + path only, never individual positions)
    - Static template registration in report.py vs runtime tool registration in Plan 02 (REPLAN-6 split)

key-files:
  created:
    - src/alphaswarm/portfolio.py
    - src/alphaswarm/templates/report/10_portfolio_impact.j2
    - tests/test_portfolio.py
    - .planning/phases/25-portfolio-impact-analysis/deferred-items.md
  modified:
    - src/alphaswarm/report.py (TOOL_TO_TEMPLATE + SECTION_ORDER append only)

key-decisions:
  - "Non-equity holdings surface as reason='non_equity' gaps (not silently dropped) so users can distinguish fund wrappers from uncovered equities"
  - "Tie-breaker HOLD > SELL > BUY applied via explicit TIE_BREAKER_ORDER tuple for deterministic behavior across dict reorderings"
  - "Static template registration split from runtime tool registration: Plan 01 writes TOOL_TO_TEMPLATE/SECTION_ORDER unconditionally; Plan 02 will register the runtime tool closure only when --portfolio is provided"
  - "market_value_display computed in the bridge (build_portfolio_impact) rather than on ExcludedHolding/Holding — keeps parser TypedDicts minimal and templates pure"
  - "Short-ticker entries (ARM, HON, NIO, TLN, VRT) use multi-word canonical names plus word-boundary regex as defense in depth against 'alarm', 'honest', 'bionic', 'talent', 'advert' collisions"

patterns-established:
  - "TypedDict per return shape: Holding, ExcludedHolding, PortfolioParseResult, MatchedPortfolioTicker, PortfolioGap, CoverageSummary, PortfolioImpact"
  - "Parser returns both matched (equity_holdings) and intentionally-preserved (excluded_holdings) sets instead of discarding non-matches silently"
  - "Currency parser handles dollar sign, thousands separators, trailing spaces, parens-negative, '--', 'N/A', empty — falls back to 0.0 on any failure"
  - "Header row discovered dynamically via scan of first N lines rather than hardcoded index"
  - "Gap subsections grouped by reason in Jinja template via selectattr filter"

requirements-completed: [PORTFOLIO-01, PORTFOLIO-02, PORTFOLIO-03, PORTFOLIO-04]

# Metrics
duration: ~5m
completed: 2026-04-10
---

# Phase 25 Plan 01: Portfolio Data Layer Summary

**Schwab CSV parser + word-boundary ticker bridge + grouped-gap markdown template, with 73 review-locked unit tests landing the portfolio feature's side-effect-free building blocks for Plan 02 to wire into the CLI and HTML report.**

## Performance

- **Duration:** ~5 min 16 s
- **Started:** 2026-04-10T19:35:54Z (first RED commit)
- **Completed:** 2026-04-10T19:41:10Z (final GREEN commit)
- **Tasks:** 2
- **Commits:** 4 (2 RED + 2 GREEN TDD pairs)
- **Files created:** 4
- **Files modified:** 1

## Accomplishments

- New `src/alphaswarm/portfolio.py` module exposes 7 TypedDict contracts (Holding, ExcludedHolding, PortfolioParseResult, MatchedPortfolioTicker, PortfolioGap, CoverageSummary, PortfolioImpact) plus PortfolioParseError
- `parse_schwab_csv` handles BOM, dynamic header detection, currency edge cases, duplicate aggregation, and non-equity preservation
- `parse_schwab_csv_async` wraps the blocking parser in `asyncio.to_thread` per CLAUDE.md 100% async constraint (REPLAN-1)
- `build_portfolio_impact` uses word-boundary regex matching against `TICKER_ENTITY_MAP` (25 tickers) to bridge holdings to `read_entity_impact()` results, emitting both matched_tickers and grouped gap_tickers
- Deterministic tie-breaker (HOLD > SELL > BUY) via explicit `TIE_BREAKER_ORDER` tuple (REPLAN-8)
- `10_portfolio_impact.j2` renders matched table + grouped gap subsections (No Simulation Coverage / Non-Equity Holdings) via `selectattr` filters
- Static template registration in `report.py` (TOOL_TO_TEMPLATE + SECTION_ORDER) — runtime tool registration deferred to Plan 02 per REPLAN-6 split
- 73 unit tests cover parser shape, currency/quantity edge cases, header detection, BOM, duplicates, malformed input, word-boundary negatives (ARM vs alarm, HON vs honest, VRT vs advert, TLN vs talent), multi-word positives (SCHW/Charles Schwab, HIMS/Hims & Hers, TSM/Taiwan Semiconductor, BYDDY/BYD, NIO/Nio Inc.), tie-breaker shapes, build_portfolio_impact semantics, async wrapper, template rendering, empty states, and ReportAssembler integration
- All 33 pre-existing `test_report.py` tests remain green — no regression in the assembler

## Task Commits

Each task was committed atomically (TDD RED → GREEN):

1. **Task 1 RED: failing tests for parser and bridge** — `500b36a` (test)
2. **Task 1 GREEN: portfolio.py parser, bridge, TypedDicts** — `390c3d9` (feat)
3. **Task 2 RED: failing tests for template and assembler** — `e085321` (test)
4. **Task 2 GREEN: 10_portfolio_impact.j2 + report.py registration** — `5ab728c` (feat)

## Files Created/Modified

### Created
- `src/alphaswarm/portfolio.py` (473 lines) — 7 TypedDict contracts, parse_schwab_csv, parse_schwab_csv_async, build_portfolio_impact, TICKER_ENTITY_MAP (25 entries), _parse_currency, _parse_quantity, _find_header_row, _compile_entity_patterns, _match_entity, PortfolioParseError, REASON_NO_COVERAGE, REASON_NON_EQUITY, TIE_BREAKER_ORDER
- `src/alphaswarm/templates/report/10_portfolio_impact.j2` (47 lines) — Portfolio Impact markdown section with conditional Matched Positions table, grouped Coverage Gaps subsections (No Simulation Coverage + Non-Equity Holdings), empty-state copy
- `tests/test_portfolio.py` (780 lines) — 73 unit tests across 17 test classes
- `.planning/phases/25-portfolio-impact-analysis/deferred-items.md` — logs pre-existing Neo4j integration test failure as out-of-scope

### Modified
- `src/alphaswarm/report.py` — added `"portfolio_impact": "10_portfolio_impact.j2"` to TOOL_TO_TEMPLATE and `"portfolio_impact"` to SECTION_ORDER (two-line append; no other lines touched)

## Public API

```python
# Module: alphaswarm.portfolio

# TypedDict contracts
class Holding(TypedDict): ticker, shares, market_value
class ExcludedHolding(TypedDict): ticker, shares, market_value, asset_type
class PortfolioParseResult(TypedDict): equity_holdings, excluded_holdings
class MatchedPortfolioTicker(TypedDict): ticker, shares, market_value,
    market_value_display, signal, confidence, entity_name, avg_sentiment, mention_count
class PortfolioGap(TypedDict): ticker, shares, market_value,
    market_value_display, reason, asset_type
class CoverageSummary(TypedDict): covered, total_equity_holdings, coverage_pct
class PortfolioImpact(TypedDict): matched_tickers, gap_tickers, coverage_summary

# Exceptions
class PortfolioParseError(ValueError): ...

# Constants
TICKER_ENTITY_MAP: dict[str, list[str]]  # 25 entries
REASON_NO_COVERAGE = "no_simulation_coverage"
REASON_NON_EQUITY = "non_equity"
TIE_BREAKER_ORDER: tuple[str, ...] = ("HOLD", "SELL", "BUY")

# Public functions
def parse_schwab_csv(path: Path) -> PortfolioParseResult
async def parse_schwab_csv_async(path: Path) -> PortfolioParseResult
async def build_portfolio_impact(
    parse_result: PortfolioParseResult,
    gm: GraphStateManager,
    cycle_id: str,
) -> PortfolioImpact
```

## Test Counts (73 total)

| Test class | Count | Area |
|---|---|---|
| TestCurrencyParsing | 8 | Currency edge cases (REVIEWS MEDIUM) |
| TestQuantityParsing | 4 | Quantity parsing (thousands separator) |
| TestHeaderRowDetection | 3 | Dynamic header detection (REVIEWS LOW) |
| TestParseSchwabCsv | 7 | Parser happy path + shape |
| TestBomEncoding | 1 | utf-8-sig BOM handling (REVIEWS LOW) |
| TestDuplicateTickerAggregation | 1 | Duplicate row aggregation (REVIEWS MEDIUM Codex) |
| TestMalformedCsvRaises | 3 | Fail-fast error paths |
| TestNoPersistence | 2 | No file writes + source grep check (D-05) |
| TestNoIndividualLogging | 1 | Privacy — log source grep check (REVIEWS MEDIUM Codex) |
| TestWordBoundaryMatch | 6 | ARM/VRT/HON/TLN negatives + positives (REVIEWS MEDIUM consensus) |
| TestBuildPortfolioImpact | 7 | Bridge semantics (matched, gaps, non-equity, denominator) |
| TestMajoritySignalTieBreaker | 5 | HOLD > SELL > BUY tie-breaker (REPLAN-8) |
| TestMultiWordEntityMatching | 6 | SCHW/HIMS/TSM/BYDDY/NIO multi-word matching (REPLAN-9) |
| TestAsyncWrapperUsesToThread | 1 | asyncio.to_thread lexical check (REPLAN-1) |
| TestTickerEntityMap | 3 | 25-entry coverage + multi-word disambiguation |
| TestTemplateRegistration | 3 | TOOL_TO_TEMPLATE/SECTION_ORDER entry present |
| TestPortfolioTemplate | 7 | Template heading, summary, matched table, gap subsections |
| TestPortfolioTemplateEmptyStates | 3 | Empty matched, all-covered, non-equity-only rendering |
| TestAssemblerIntegration | 2 | Assembler includes/omits portfolio section by observation presence |

## Review Concerns Addressed (from 25-REVIEWS.md)

| Concern | Severity | Source | Resolution |
|---|---|---|---|
| Ticker substring false positives (ARM vs ALARM) | MEDIUM | consensus | word-boundary `\\b{re.escape}\\b` regex in `_compile_entity_patterns` + multi-word short-ticker entries |
| Non-equity gap contradiction | HIGH | Codex | parser returns `excluded_holdings`; bridge surfaces as `reason="non_equity"` gaps with asset_type column in template |
| Currency parsing edge cases | MEDIUM | consensus | `_parse_currency` handles `$`, commas, spaces, parens-negative, `--`, `N/A`, empty, garbage — tested 8 shapes |
| Encoding / BOM | LOW | Gemini | `path.read_text(encoding="utf-8-sig")` + `TestBomEncoding::test_handles_utf8_bom` |
| Header row fragility | LOW | Gemini | `_find_header_row` scans first 5 lines for Symbol+Asset Type |
| Duplicate tickers | MEDIUM | Codex | parser aggregates shares + market_value deterministically |
| Type safety | MEDIUM | Codex | 7 TypedDict contracts |
| Privacy / no logging of holdings | MEDIUM | Codex | single `log.info` with counts + path only; verified via `TestNoIndividualLogging` source-grep |
| REPLAN-1 asyncio.to_thread | MEDIUM | consensus | `parse_schwab_csv_async` body is `return await asyncio.to_thread(parse_schwab_csv, path)` + lexical test |
| REPLAN-2 TypedDict key consistency | MEDIUM | consensus | `ExcludedHolding` omits `market_value_display`; bridge computes for all `PortfolioGap` entries |
| REPLAN-4 asset_type hardcode | MEDIUM | consensus | unmatched-equity branch hardcodes `asset_type="Equity"`; non-equity branch copies from ExcludedHolding |
| REPLAN-5 Intentional non-equity gap emission | HIGH | Codex | non-equity gaps preserved as reason=`non_equity` with separate template subheading |
| REPLAN-6 Static vs runtime tool registration | HIGH | Codex | Plan 01 does STATIC template registration only; runtime tool registration deferred to Plan 02 |
| REPLAN-8 Majority signal tie-breaker | MEDIUM | Gemini | `TIE_BREAKER_ORDER = ("HOLD", "SELL", "BUY")` tuple iteration, 5 tie-shape tests |
| REPLAN-9 Multi-word entity regex | MEDIUM | Codex | 6 multi-word positive tests (SCHW, HIMS, TSM, BYDDY, NIO) + 1 negative (Schwarz) |

## Decisions Made

- **Vertiv multi-word entry added:** plan only listed `"Vertiv"` but test `test_short_tickers_have_qualified_names` required at least one multi-word substring for VRT; added `"Vertiv Holdings"` as primary entry. This is a minor strengthening of the disambiguation — the word-boundary regex already protected VRT from matching "advert", but the explicit multi-word entry provides defense in depth consistent with ARM, NIO, TLN, HON.
- **Honeywell multi-word entry added:** same reasoning as VRT — added `"Honeywell International"` as primary before `"Honeywell"` fallback.
- **No refactor commits:** GREEN code was clean at the point of the first passing run; no refactor step produced meaningful diffs.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] TICKER_ENTITY_MAP: VRT and HON missing multi-word entries required by test**
- **Found during:** Task 1 GREEN run
- **Issue:** `test_short_tickers_have_qualified_names` asserted all of (ARM, HON, NIO, TLN, VRT) have at least one substring containing a space. Plan literal code had `"HON": ["Honeywell"]` and `"VRT": ["Vertiv"]` — single-word entries that failed the test.
- **Fix:** Changed to `"HON": ["Honeywell International", "Honeywell"]` and `"VRT": ["Vertiv Holdings", "Vertiv"]`. The multi-word entry sits first so it matches canonical corporate names; the single-word fallback stays for short references. Word-boundary regex already prevented "honest"/"advert" collisions; this is consistency with ARM/NIO/TLN.
- **Files modified:** `src/alphaswarm/portfolio.py`
- **Verification:** `TestTickerEntityMap::test_short_tickers_have_qualified_names` passes; `TestWordBoundaryMatch::test_hon_does_not_match_honest` and `test_vrt_does_not_match_advertisement` both pass.
- **Committed in:** `390c3d9` (Task 1 GREEN commit)

**2. [Rule 3 - Blocking] Plan test snippet had raw newline inside a Python string literal**
- **Found during:** Task 1 RED (writing `TestAsyncWrapperUsesToThread`)
- **Issue:** Plan showed `end = src.index("\n\n", start)` but the plan's raw text encoded the `\n` as actual newlines, which would have been a Python syntax error.
- **Fix:** Used `"\n\n\n"` as a sentinel and defensive `if ... in src[start:] else len(src)` fallback so the test works regardless of how many blank lines follow the function body.
- **Files modified:** `tests/test_portfolio.py`
- **Verification:** `TestAsyncWrapperUsesToThread::test_async_wrapper_uses_to_thread` passes; the `asyncio.to_thread` token is found within the function body.
- **Committed in:** `500b36a` (Task 1 RED commit)

---

**Total deviations:** 2 auto-fixed (1 test-locked data fix, 1 plan-text transcription fix)
**Impact on plan:** Neither changed the public contract, behavior, or scope. Both were local adjustments to make the plan's own tests self-consistent.

## Issues Encountered

- **Pre-existing Neo4j integration test failure** (tests/test_graph_integration.py::test_ensure_schema_idempotent): `RuntimeError: got Future attached to a different loop` in neo4j async driver shims. Pre-existing, unrelated to portfolio code. Logged to `.planning/phases/25-portfolio-impact-analysis/deferred-items.md` and excluded from plan-scope verification.
- **Worktree branch base was behind** (10ec506 instead of 86cea85 — parallel to master, not an ancestor). Fixed via `git reset --soft 86cea85` followed by `git checkout HEAD -- .planning src/alphaswarm tests pyproject.toml uv.lock` before starting plan work.

## User Setup Required

None — this plan is purely library/template code with no external service configuration.

## Next Phase Readiness

**Ready for Plan 25-02:**
- `portfolio.parse_schwab_csv_async()` available for CLI-triggered holdings loading
- `portfolio.build_portfolio_impact()` available for the pre-call determinism path
- `TOOL_TO_TEMPLATE["portfolio_impact"]` already routes ToolObservations to the markdown template
- `SECTION_ORDER` already places the portfolio section as the 9th/final canonical block
- Plan 02 must still:
  - Add `--portfolio` argparse flag to the `report` subparser in `src/alphaswarm/cli.py`
  - Add the runtime `portfolio_impact` closure to the `tools` dict in `_handle_report` (CONDITIONAL on `--portfolio`)
  - Extend `REACT_SYSTEM_PROMPT` with the portfolio tool line (CONDITIONAL on `--portfolio`)
  - Wire the pre-call determinism path that executes `portfolio_impact` automatically at cycle-end
  - Append the Portfolio Impact HTML section to `src/alphaswarm/templates/report/report.html.j2`

**No blockers.**

## Self-Check: PASSED

Verified:
- [x] `src/alphaswarm/portfolio.py` exists
- [x] `src/alphaswarm/templates/report/10_portfolio_impact.j2` exists
- [x] `tests/test_portfolio.py` exists
- [x] `.planning/phases/25-portfolio-impact-analysis/deferred-items.md` exists
- [x] Commit `500b36a` exists (Task 1 RED)
- [x] Commit `390c3d9` exists (Task 1 GREEN)
- [x] Commit `e085321` exists (Task 2 RED)
- [x] Commit `5ab728c` exists (Task 2 GREEN)
- [x] `uv run pytest tests/test_portfolio.py tests/test_report.py -q` → 106 passed
- [x] `grep -c '"portfolio_impact"' src/alphaswarm/report.py` → 2 (TOOL_TO_TEMPLATE + SECTION_ORDER)
- [x] `grep -c '\.write_text(\|\.write_bytes(\|json\.dump' src/alphaswarm/portfolio.py` → 0 (no disk writes)
- [x] No stubs found in created/modified files

---
*Phase: 25-portfolio-impact-analysis*
*Completed: 2026-04-10*
