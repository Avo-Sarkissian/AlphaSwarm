# Phase 22: Fix Report Tool Name Mismatch - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions captured in CONTEXT.md — this log preserves the discussion.

**Date:** 2026-04-08
**Phase:** 22-fix-report-tool-name-mismatch
**Mode:** discuss
**Areas analyzed:** Test string consistency, System prompt wording

## Assumptions Presented

### Tool Name Mismatches
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Only 2 tool names mismatch: `consensus_summary` and `signal_flips` | Confident | `report.py:32,37` vs `cli.py:755,760`; all 6 other names match |
| `TOOL_TO_TEMPLATE` and `SECTION_ORDER` already use correct names | Confident | `report.py:215-236` |

### Test Hygiene
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| `test_basic_extraction` parser test uses `consensus_summary` as generic string | Confident | `tests/test_report.py:34,38` |
| Updating the test string has no behavioral impact | Confident | `_parse_action_input` is a generic regex extractor |

## Discussion Outcomes

### Test string consistency
- **Decision:** Update `test_report.py:34` to use `bracket_summary` instead of `consensus_summary`
- **Rationale:** Keeps test strings consistent with real tool names for readability

### System prompt wording
- **Decision:** Update `bracket_summary` description to "Get per-bracket consensus summary (BUY/SELL/HOLD counts per bracket for Round 3)"
- **Decision:** Keep `signal_flip_analysis` description as-is: "Get agents who changed position between rounds" (already accurate)

## Corrections Made

No corrections — user confirmed recommended approach for both areas.

## External Research

Not applicable — pure internal fix, no external dependencies.
