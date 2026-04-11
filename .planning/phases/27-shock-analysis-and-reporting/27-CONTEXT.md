# Phase 27: Shock Analysis and Reporting - Context

**Gathered:** 2026-04-11
**Status:** Ready for planning

<domain>
## Phase Boundary

Add a shock impact analysis layer to the post-simulation report and BracketPanel TUI widget. When a simulation cycle had a shock injected, the report gains a dedicated shock impact section (section 11) showing which agents pivoted vs held firm, bracket-level signal shift aggregations, and per-round before/after signal distributions. The BracketPanel in the TUI switches from live signal bars to before/after delta bars after simulation ends. No new TUI widgets or layout changes required.

</domain>

<decisions>
## Implementation Decisions

### TUI Exposure
- **D-01:** BracketPanel gains a "delta mode" that activates post-simulation when a shock was detected for the current cycle. The panel switches from live signal-proportion bars to before/after diff bars showing how each bracket's BUY/SELL/HOLD split changed across the shock boundary.
- **D-02:** Delta mode activates via the existing `_poll_snapshot()` 200ms tick — the same mechanism used for all other StateStore→TUI reactivity. When `SimulationPhase.COMPLETE` is reached AND a ShockEvent exists for the cycle, BracketPanel renders delta bars instead of live bars.
- **D-03:** The TUI delta view is a compact summary only. Full agent-level detail (pivots, held-firm, bracket aggregations) lives in the report section.

### Neo4j Query Strategy
- **D-04:** No new Neo4j schema changes. Use `ShockEvent.injected_before_round` to determine the shock boundary. For a shock at `injected_before_round=N`, query Decision nodes where `round == N-1` (pre) and `round == N` (post).
- **D-05:** `(ShockEvent)-[:PRECEDES]->(Decision)` edges remain deferred — not added in Phase 27. The `injected_before_round` field provides the same targeting without schema migration.
- **D-06:** Two new `GraphStateManager` methods: `read_shock_event(cycle_id)` (returns ShockEvent metadata for the cycle, or None if no shock), and `read_shock_impact(cycle_id)` (returns per-agent pre/post signals, bracket aggregations, pivot list).

### Pivot / Held-Firm Metric
- **D-07:** An agent **pivoted** if its signal changed between the round immediately before the shock and the round after: `pre_signal != post_signal`. Signal is BUY / SELL / HOLD.
- **D-08:** An agent **held firm** if `pre_signal == post_signal` regardless of confidence delta.
- **D-09:** Baseline is always "round immediately before shock" — `injected_before_round=2` means compare Round 1 (pre) vs Round 2 (post); `injected_before_round=3` means Round 2 (pre) vs Round 3 (post).
- **D-10:** Do not use `flip_type` on RationaleEpisode for pivot detection. Compute directly from Decision nodes by round comparison. `flip_type` was designed for inter-round flip tracking independent of shock timing.

### Report Section (Section 11)
- **D-11:** New tool key `shock_impact` maps to template `11_shock_impact.j2`. Added to `TOOL_TO_TEMPLATE` and appended to end of `SECTION_ORDER` (after `portfolio_impact`).
- **D-12:** Section renders **only when a ShockEvent exists** for the cycle. When `read_shock_event()` returns None, the section is skipped entirely — no placeholder text, no empty section in the report. Conditional rendering logic lives in `ReportEngine` (same layer that conditionally includes `portfolio_impact` when portfolio data is absent).
- **D-13:** Section content (from the `11_shock_impact.j2` template):
  1. Shock header: shock text, injected before round N, timestamp
  2. Bracket-level signal shift table: per-bracket BUY/SELL/HOLD % before vs after, delta column
  3. Pivot count summary: total pivoted, total held firm, pivot rate %
  4. Agent pivot list: agents who changed signal (bracket, agent_id, pre_signal→post_signal)
  5. Held-firm notable agents: agents in minority-signal brackets who held firm (dissenter-style)

### Claude's Discretion
- Exact BracketPanel delta bar rendering style (arrow indicators, color delta, or side-by-side bars)
- Whether `read_shock_impact()` is a single compound query or split into sub-queries
- Held-firm threshold for "notable held-firm" agents (e.g., only surface held-firm agents whose bracket majority shifted)
- Whether the TUI BracketPanel delta mode persists until user quits, or reverts after N seconds

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Report pipeline (primary)
- `src/alphaswarm/report.py` — `TOOL_TO_TEMPLATE` (line 312), `SECTION_ORDER` (line 325), `ReportAssembler.render_section()`, `ReportEngine` loop — adding `shock_impact` follows the exact same pattern as all existing sections
- `src/alphaswarm/templates/report/10_portfolio_impact.j2` — existing template as structural reference for conditional section rendering

### TUI BracketPanel (primary)
- `src/alphaswarm/tui.py` — `BracketPanel` class (search "class BracketPanel"), `_poll_snapshot()` (line ~696) for delta-mode trigger, `SimulationPhase` enum for COMPLETE detection

### Neo4j ShockEvent schema (primary)
- `src/alphaswarm/graph.py` — `write_shock_event()` (line 176) and `SCHEMA_STATEMENTS` shock index (line 70) for ShockEvent node structure; `read_peer_decisions()` and `read_key_dissenters()` as Cypher read method patterns

### StateStore shock bridge (primary)
- `src/alphaswarm/state.py` — `is_shock_window_open()`, `shock_next_round()` (for TUI access pattern); `SimulationPhase` enum (for COMPLETE detection in BracketPanel delta trigger)

### Prior context (phase decisions that constrain this phase)
- `.planning/phases/26-shock-injection-core/26-CONTEXT.md` — D-11 through D-14 (ShockEvent schema: shock_id, cycle_id, shock_text, injected_before_round, HAS_SHOCK relationship), deferred items (PRECEDES edges)
- `.planning/phases/15-post-simulation-report/15-CONTEXT.md` — D-01 through D-09 (ReACT report engine, TOOL_TO_TEMPLATE pattern, section order, Cypher tool per section)
- `.planning/phases/24-html-report-export/24-CONTEXT.md` — D-05/D-08 (HTML report uses same data structures — shock_impact section automatically appears in HTML report)

### Requirements
- `.planning/REQUIREMENTS.md` — SHOCK-04, SHOCK-05 (to be defined — Phase 27 execution should create these entries)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `TOOL_TO_TEMPLATE` + `SECTION_ORDER` dicts in `report.py`: adding `shock_impact` is a one-line entry in each dict, then a new `GraphStateManager` method and a new `.j2` template file
- `read_key_dissenters()` in `graph.py`: structural template for the "held-firm notable agents" query (both filter by signal relationship to bracket majority)
- `BracketPanel` existing bar rendering: delta mode can reuse the same bar widgets with modified data source (pre/post snapshot instead of live snapshot)
- `portfolio_impact` conditional rendering in `ReportEngine`: direct template for how to conditionally include `shock_impact` only when `read_shock_event()` returns non-None
- `10_portfolio_impact.j2`: template file as structural reference (conditional data rendering, null-guard patterns)

### Established Patterns
- Session-per-method for all `GraphStateManager` reads
- `structlog` component-scoped logger (`component="report"`)
- `ToolObservation` dataclass for typed query results flowing from graph layer to assembler
- BracketPanel reactive updates via `_poll_snapshot()` tick — same detection point for delta-mode activation

### Integration Points
- `report.py`: add `"shock_impact"` to `TOOL_TO_TEMPLATE` and `SECTION_ORDER`; add `read_shock_event()` + `read_shock_impact()` call in `ReportEngine` with conditional skip when no shock
- `graph.py`: add `read_shock_event(cycle_id)` and `read_shock_impact(cycle_id)` async methods
- `tui.py BracketPanel`: add `_delta_mode: bool` flag, populate from `_poll_snapshot()` when `SimulationPhase.COMPLETE` + shock detected; render delta bars when true
- `src/alphaswarm/templates/report/11_shock_impact.j2`: new template file
- `.planning/REQUIREMENTS.md`: add SHOCK-04 (before/after TUI comparison) and SHOCK-05 (shock impact report section) entries

</code_context>

<specifics>
## Specific Ideas

- BracketPanel delta mode should feel like a natural state transition, not a separate widget — same bar positions, different data (before/after instead of live). Minimal visual disruption.
- The `injected_before_round` field makes Phase 27 queries clean and backward-compatible: all Phase 26 shock data already has this field populated.
- Section 11 template can mirror the "Key Dissenters" section structure (04): header, per-bracket summary table, then individual agent list.

</specifics>

<deferred>
## Deferred Ideas

- `(ShockEvent)-[:PRECEDES]->(Decision)` relationship — still deferred. Not needed with `injected_before_round` query strategy; add only if graph traversal performance becomes a concern in future phases.
- Multi-shock per cycle analysis — current design assumes one ShockEvent per cycle (Phase 26 queue is maxsize=1). Multi-shock handling is a future concern.
- Confidence delta as a secondary pivot signal — signal-change-only for Phase 27; confidence delta could be added as a "conviction shift" supplementary metric in a later report enhancement.

</deferred>

---

*Phase: 27-shock-analysis-and-reporting*
*Context gathered: 2026-04-11*
