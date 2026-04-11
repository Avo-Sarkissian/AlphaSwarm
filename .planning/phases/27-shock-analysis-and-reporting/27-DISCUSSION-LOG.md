> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions captured in CONTEXT.md — this log preserves the Q&A.

**Date:** 2026-04-11
**Phase:** 27-shock-analysis-and-reporting
**Mode:** discuss
**Areas analyzed:** TUI exposure, PRECEDES edges, Pivot metric, Section placement

## Assumptions Presented

Phase 26 built: ShockEvent nodes with `injected_before_round`, `HAS_SHOCK` relationship to Cycle, and explicitly deferred PRECEDES edges to Phase 27.

Existing report pipeline: TOOL_TO_TEMPLATE + SECTION_ORDER pattern, all 9 sections + portfolio_impact (conditional). HTML report reuses same data automatically.

## Discussion

### TUI Exposure

| Question | Options | Selected |
|----------|---------|---------|
| Where does before/after appear? | Report only / TUI post-simulation panel / TUI inline + report | TUI inline + report |
| Which TUI panel shows the delta? | BracketPanel delta mode / New ShockSummaryWidget / ShockInputScreen repurposed | BracketPanel delta mode (recommended) |

### PRECEDES Edges

| Question | Options | Selected |
|----------|---------|---------|
| Add PRECEDES edges or query by round? | Query by injected_before_round / Add PRECEDES edges | Query by injected_before_round (recommended) |

### Pivot / Held-Firm Metric

| Question | Options | Selected |
|----------|---------|---------|
| How to define "pivoted"? | Signal change only / Signal change or confidence ≥20 / Reuse flip_type | Signal change only (recommended) |
| What is the "before" baseline? | Round immediately before vs round after / Always Round 1 as baseline | Round immediately before vs round after (recommended) |

### Section Placement

| Question | Options | Selected |
|----------|---------|---------|
| Where does shock impact land in report? | After portfolio_impact (section 11) / Before consensus_summary (section 0) / After round_timeline (section 2.5) | After portfolio_impact as section 11 (recommended) |
| Conditional or always show? | Conditional — only when shock injected / Always with placeholder | Conditional (recommended) |

## Corrections Made

No corrections — all recommended defaults accepted.
