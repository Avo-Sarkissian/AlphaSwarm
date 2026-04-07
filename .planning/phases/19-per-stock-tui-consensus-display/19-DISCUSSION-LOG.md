# Phase 19: Per-Stock TUI Consensus Display - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions captured in CONTEXT.md — this log preserves the analysis.

**Date:** 2026-04-07
**Phase:** 19-per-stock-tui-consensus-display
**Mode:** discuss
**Areas analyzed:** Panel placement, Update timing, Bracket disagreement display, Dual consensus format

## Assumptions Going In

Key codebase facts surfaced before discussion:
- `TickerDecision` (Phase 18) already produced per-agent with `ticker`, `direction`, `expected_return_pct`, `time_horizon`
- `AgentDecision.ticker_decisions: list[TickerDecision]` — default empty list, backward-compatible
- `influence_weights` already computed in `simulation.py` for dynamic topology (peer selection)
- `BracketPanel` (width=40, bottom-row height=12) shows 10 per-bracket signal bars — exact pattern to reuse
- Current layout: HeaderBar (top) | main-row (grid + rationale sidebar) | bottom-row (telemetry + bracket panel)
- `StateStore.snapshot()` → `StateSnapshot` — frozen dataclass; new fields follow established pattern
- `set_bracket_summaries()` in StateStore is the direct template for new `set_ticker_consensus()`

## Assumptions Presented

### Panel Placement
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| New right-side column in main-row | Confident | Existing layout has space; grid is only 30w; rationale sidebar is 1fr |
| BracketPanel stays in bottom-row unchanged | Confident | Ticker panel is additive, not a replacement |

### Update Timing
| Assumption | Confident | Evidence |
|------------|-----------|----------|
| Only at COMPLETE | Likely | Success criteria says "after simulation completes" |
| Updates after each round | Possible | More aligned with live dashboard philosophy |

### Bracket Disagreement
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Compact bullish/bearish text lists | Likely | Space-efficient, readable in terminal |
| Mini bracket bars (BracketPanel pattern) | Possible | Richer, but potentially tall with 3 tickers |

### Dual Consensus Format
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Weighted primary + majority inline | Confident | Compact, both values present, matches DTUI-02 |

## Corrections Made

### Update Timing
- **Original assumption:** Only computed and displayed at SimulationPhase.COMPLETE
- **User correction:** Updates after each round (Round 1, 2, 3)
- **Reason:** User wants to see consensus evolving in real-time across all 3 rounds

### Bracket Disagreement Display
- **Original assumption:** Compact bullish/bearish text lists (recommended)
- **User correction:** Mini bracket bars per ticker (same BracketPanel pattern, scrollable)
- **Reason:** User prefers the richer visual format; panel will scroll to accommodate 3 tickers × 10 brackets

## No External Research

All data sourced from existing codebase — no external library research needed. BracketPanel/BracketSummary patterns are established and sufficient.
