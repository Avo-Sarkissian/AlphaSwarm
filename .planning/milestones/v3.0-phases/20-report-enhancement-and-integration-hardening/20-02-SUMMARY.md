---
phase: 20-report-enhancement-and-integration-hardening
plan: "02"
subsystem: report
tags: [report, jinja2, tdd, cli, market-context]
dependency_graph:
  requires: [write_ticker_consensus_summary, read_market_context]
  provides: [09_market_context.j2, market_context_data-assembler-param, cli-market-context-wiring]
  affects: [report.py, cli.py, tests/test_report.py]
tech_stack:
  added: []
  patterns: [jinja2-template, optional-kwarg-extension, prepend-section-pattern]
key_files:
  created:
    - src/alphaswarm/templates/report/09_market_context.j2
  modified:
    - src/alphaswarm/report.py
    - src/alphaswarm/cli.py
    - tests/test_report.py
decisions:
  - "Market Context section prepended before SECTION_ORDER loop (D-03) — not inserted into TOOL_TO_TEMPLATE or SECTION_ORDER"
  - "Consensus column consolidates majority_signal, majority_pct, and consensus_score into single cell (7 columns vs original 8) per cross-AI review feedback"
  - "market_context_data silently omitted when None or empty list — no error, no stub section"
  - "TOOL_TO_TEMPLATE and SECTION_ORDER left at 8 entries each (D-02 unchanged)"
metrics:
  duration: "~8 min"
  completed: "2026-04-08T04:00:00Z"
  tasks_completed: 2
  files_modified: 3
  files_created: 1
---

# Phase 20 Plan 02: Market Context Report Section Summary

**One-liner:** Jinja2 7-column market context template wired into ReportAssembler.assemble() and CLI _handle_report() to render per-ticker price/consensus comparison in post-simulation reports.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 (RED) | Add failing tests for market context template and assembler extension | 8ffeebd | tests/test_report.py |
| 1 (GREEN) | Create 09_market_context.j2 template and extend assemble() with market_context_data | be8b77c | src/alphaswarm/templates/report/09_market_context.j2, src/alphaswarm/report.py |
| 2 | Wire CLI _handle_report to fetch and inject market context data | ae26fc4 | src/alphaswarm/cli.py |

## What Was Built

### 09_market_context.j2 (new template)

7-column Jinja2 template rendering per-ticker market data alongside agent consensus signals:

- **Columns:** Ticker | Consensus | Last Close | 30d Change | P/E | 52w Range | Status
- **Consensus column** consolidates `majority_signal`, `majority_pct` (as %), and `consensus_score` into a single cell: `SELL (72%) [0.68]` — reduces from 8 to 7 columns per cross-AI review feedback
- **None handling:** All numeric fields use `if field is not none else 'N/A'` guards (Jinja2 D-07)
- **Degraded marker:** `{{ '[degraded data]' if row.is_degraded else '' }}` in Status column (D-09)
- **Empty guard:** Section only renders when `market_context_data` is non-empty (controlled by assembler)

### report.py (extended)

`ReportAssembler.assemble()` signature extended with optional `market_context_data` keyword argument:

```python
def assemble(
    self,
    observations: list[ToolObservation],
    cycle_id: str,
    *,
    market_context_data: list[dict] | None = None,
) -> str:
```

Market context is prepended to `sections` list **before** the `for tool_name in SECTION_ORDER:` loop — ensuring it appears first in the rendered report (D-03). `TOOL_TO_TEMPLATE`, `SECTION_ORDER`, `MAX_ITERATIONS`, and `REACT_SYSTEM_PROMPT` are untouched.

### cli.py (wired)

Two changes to `_handle_report()`:

1. After `gm = app.graph_manager`, added: `market_context_data = await gm.read_market_context(cycle_id)`
2. Updated `assembler.assemble()` call to pass `market_context_data=market_context_data`

### tests/test_report.py (8 new tests)

**TestReportAssemblerMarketContext (4 tests):**
- `test_includes_market_context_when_data_present` — assemble() with data includes heading and ticker
- `test_skips_market_context_when_absent` — assemble() without kwarg omits heading
- `test_skips_market_context_when_empty_list` — assemble() with `[]` omits heading
- `test_market_context_appears_before_other_sections` — market context index < consensus summary index

**TestMarketContextTemplate (4 tests):**
- `test_renders_full_data_row` — TSLA row with all fields populates correctly
- `test_renders_none_fields_as_na` — None pe_ratio and price_change_30d_pct render as N/A
- `test_degraded_marker` — is_degraded=True shows [degraded data]
- `test_no_degraded_marker_when_false` — is_degraded=False shows no marker

## Verification

- `uv run pytest tests/test_report.py::TestReportAssemblerMarketContext tests/test_report.py::TestMarketContextTemplate -x -q` — 8 passed
- `uv run pytest tests/test_report.py -x -q` — 21 passed
- `uv run pytest tests/ -x -q --ignore=tests/test_graph_integration.py` — 616 passed
- `grep "## Market Context" src/alphaswarm/templates/report/09_market_context.j2` — match
- `grep "market_context_data" src/alphaswarm/report.py` — 4 matches (signature, docstring, if block, render call)
- `grep "read_market_context" src/alphaswarm/cli.py` — match
- `grep "market_context_data=" src/alphaswarm/cli.py` — match
- `ls src/alphaswarm/templates/report/09_market_context.j2` — exists

**Note:** `tests/test_graph_integration.py` excluded — pre-existing event loop failure requiring live Neo4j Docker container (pre-dates this plan).

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None.

## Self-Check: PASSED

- `/Users/avosarkissian/Documents/VS Code/AlphaSwarm/.claude/worktrees/agent-ad0c4b62/src/alphaswarm/templates/report/09_market_context.j2` — FOUND (created)
- `/Users/avosarkissian/Documents/VS Code/AlphaSwarm/.claude/worktrees/agent-ad0c4b62/src/alphaswarm/report.py` — FOUND (modified)
- `/Users/avosarkissian/Documents/VS Code/AlphaSwarm/.claude/worktrees/agent-ad0c4b62/src/alphaswarm/cli.py` — FOUND (modified)
- `/Users/avosarkissian/Documents/VS Code/AlphaSwarm/.claude/worktrees/agent-ad0c4b62/tests/test_report.py` — FOUND (modified)
- Commit `8ffeebd` — FOUND
- Commit `be8b77c` — FOUND
- Commit `ae26fc4` — FOUND
