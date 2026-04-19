---
phase: 27-shock-analysis-and-reporting
plan: "01"
subsystem: database, ui
tags: [neo4j, cypher, textual, shock-analysis, tui, delta-mode]

requires:
  - phase: 26-shock-injection-core
    provides: "write_shock_event persists ShockEvent node; ShockEvent schema with HAS_SHOCK edge"

provides:
  - "read_shock_event(cycle_id) returns ShockEvent metadata dict or None"
  - "read_shock_impact(cycle_id) returns full before/after pivot analysis dict"
  - "_aggregate_shock_impact pure-Python aggregator with comparable_agents denominator"
  - "BracketPanel delta mode: enable_delta_mode, reset_delta_mode, _render_delta, _render_live"
  - "Dashboard _bracket_panel_delta_active latch + _check_bracket_delta_mode + _activate_bracket_delta_mode"

affects:
  - 27-02-PLAN (report section, CLI wiring, templates — reads from read_shock_impact)

tech-stack:
  added: []
  patterns:
    - "session-per-method + execute_read + @staticmethod _tx for new graph read methods"
    - "Python inner aggregation after Cypher inner join: comparable_agents as denominator, not 100"
    - "Async worker latch pattern: set latch AFTER side-effectful call succeeds, not before worker fires"

key-files:
  created: []
  modified:
    - src/alphaswarm/graph.py
    - src/alphaswarm/tui.py
    - tests/test_graph.py
    - tests/test_tui.py

key-decisions:
  - "comparable_agents is the Cypher inner-join denominator (agents with BOTH pre and post Decision nodes), not 100. Surfaced as a top-level field so reports can note effective sample size."
  - "WHERE shock_round >= 2 guard in Cypher eliminates round=0 query risk at DB level for edge cases."
  - "_bracket_panel_delta_active latch is set inside _activate_bracket_delta_mode AFTER enable_delta_mode() succeeds — not in the sync _check_bracket_delta_mode call site. Transient Neo4j failure leaves latch False so next 200ms tick retries."
  - "reset_delta_mode() added to BracketPanel for future multi-simulation sessions in same TUI session. Single-session limitation documented: latch has no reset path across multiple runs without TUI restart."

patterns-established:
  - "Shock analysis aggregation: Cypher inner join returns per-agent rows; Python _aggregate_shock_impact builds bracket_deltas, pivot_agents, largest_shift, notable_held_firm_agents from rows."
  - "BracketPanel render dispatch: render() checks _delta_mode and delegates to _render_delta() or _render_live()."

requirements-completed: [SHOCK-04]

duration: ~20min
completed: 2026-04-11
---

# Phase 27 Plan 01: Shock Analysis Graph Methods and BracketPanel Delta Mode Summary

**Neo4j read_shock_event/read_shock_impact with Python pivot aggregation, and BracketPanel delta-bar mode triggered post-simulation via async worker latch**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-04-11T00:00:00Z
- **Completed:** 2026-04-11T00:20:00Z
- **Tasks:** 2 (both TDD)
- **Files modified:** 4

## Accomplishments

- Added `read_shock_event` and `read_shock_impact` to `GraphStateManager` following the session-per-method + execute_read + @staticmethod _tx pattern used throughout Phase 15
- `_aggregate_shock_impact` pure-Python static method computes pivot_count, held_firm_count, pivot_rate_pct, held_firm_rate_pct, pivot_agents, bracket_deltas (per-bracket signal shift), largest_shift, notable_held_firm_agents — all indexed by `comparable_agents` (inner-join denominator), not 100
- BracketPanel extended with delta mode: `enable_delta_mode()`, `reset_delta_mode()`, `_render_delta()`, `_render_live()` (renamed from `render`), updated `render()` dispatch
- Dashboard wired with `_bracket_panel_delta_active` latch, `_check_bracket_delta_mode()` called from `_poll_snapshot`, and async worker `_activate_bracket_delta_mode()` with correct latch-after-success timing
- All 7 Phase 27 SHOCK-04 stubs (4 graph + 3 TUI) turned GREEN; 98/98 graph+tui tests pass

## Task Commits

1. **TDD RED — stubs** - `f5330a6` (test)
2. **Task 1: read_shock_event + read_shock_impact + _aggregate_shock_impact** - `44ef1b0` (feat)
3. **Task 2: BracketPanel delta mode + dashboard latch** - `1b91642` (feat)

## Files Created/Modified

- `src/alphaswarm/graph.py` — Added `read_shock_event`, `_read_shock_event_tx`, `read_shock_impact`, `_read_shock_impact_tx`, `_aggregate_shock_impact` after `read_key_dissenters`
- `src/alphaswarm/tui.py` — Extended `BracketPanel` with delta mode; added `_shock_window_was_open` (Phase 26 dep) + `_bracket_panel_delta_active` to `Dashboard.__init__`; added `_check_bracket_delta_mode` + `_activate_bracket_delta_mode` to Dashboard
- `tests/test_graph.py` — 4 Phase 27 stubs replaced with real assertions
- `tests/test_tui.py` — 3 Phase 27 stubs replaced with real assertions

## Cypher Queries

**read_shock_event:**
```cypher
MATCH (c:Cycle {cycle_id: $cycle_id})-[:HAS_SHOCK]->(se:ShockEvent)
RETURN se.shock_id AS shock_id,
       se.shock_text AS shock_text,
       se.injected_before_round AS injected_before_round,
       se.created_at AS created_at
LIMIT 1
```

**read_shock_impact (inner join, WHERE shock_round >= 2 guard):**
```cypher
MATCH (c:Cycle {cycle_id: $cycle_id})-[:HAS_SHOCK]->(se:ShockEvent)
WITH se.injected_before_round AS shock_round, se.shock_text AS shock_text
WHERE shock_round >= 2
MATCH (a:Agent)-[:MADE]->(pre:Decision {cycle_id: $cycle_id, round: shock_round - 1})
MATCH (a)-[:MADE]->(post:Decision {cycle_id: $cycle_id, round: shock_round})
RETURN a.id AS agent_id, a.name AS agent_name, a.bracket AS bracket,
       pre.signal AS pre_signal, post.signal AS post_signal,
       (pre.signal <> post.signal) AS pivoted,
       shock_round AS shock_round, shock_text AS shock_text
ORDER BY a.bracket, a.id
```

## _aggregate_shock_impact Return Dict

| Key | Type | Description |
|-----|------|-------------|
| `shock_text` | str | Shock event text from rows[0] |
| `injected_before_round` | int | Round number the shock preceded |
| `comparable_agents` | int | Inner-join denominator (NOT 100) |
| `pivot_count` | int | Agents who changed signal |
| `held_firm_count` | int | Agents who kept signal |
| `pivot_rate_pct` | float | pivot_count / comparable_agents * 100 |
| `held_firm_rate_pct` | float | held_firm_count / comparable_agents * 100 |
| `pivot_agents` | list[dict] | [{bracket, agent_id, pre_signal, post_signal}] for pivoted agents |
| `bracket_deltas` | list[dict] | Per-bracket: pre/post buy/sell/hold pcts, delta_buy_pct, dominant_post, dominant_arrow |
| `largest_shift` | dict | {bracket, direction, delta} for max abs(delta_buy_pct) |
| `notable_held_firm_agents` | list[dict] | Held-firm agents whose bracket majority changed |

## Decisions Made

- `comparable_agents` is the Cypher inner-join denominator — agents who had BOTH pre-shock and post-shock Decision nodes. Rate percentages divide by this, not by 100.
- `_bracket_panel_delta_active` latch is set INSIDE `_activate_bracket_delta_mode` AFTER `enable_delta_mode()` succeeds. On transient Neo4j failure, latch stays False and next 200ms tick retries (T-04 mitigation).
- `reset_delta_mode()` added to BracketPanel. Single-session limitation: latch has no reset path for multiple simulation runs in the same TUI session. Documented for Plan 02 awareness.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added Phase 26 `_shock_window_was_open` to Dashboard.__init__**

- **Found during:** Task 2 (Dashboard activation latch)
- **Issue:** The worktree's tui.py predates Phase 26 additions. `_shock_window_was_open` was absent from `__init__`, which is set/read by `_check_shock_window`. Adding Phase 27 latch without it would leave a reference error if Phase 26 code lands in the same merge.
- **Fix:** Added `self._shock_window_was_open: bool = False` alongside `_bracket_panel_delta_active`.
- **Files modified:** `src/alphaswarm/tui.py`
- **Committed in:** `1b91642` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 3 — blocking gap from worktree base predating Phase 26 tui changes)
**Impact on plan:** Necessary defensive addition. No scope creep.

## Issues Encountered

The worktree branch was based on commit `10ec5060` (pre-Phase 26 tui.py, pre-Phase 27 stubs). After resetting to the correct base `733aaba`, the worktree correctly reflected the planned state. Phase 26 tui.py additions (ShockInputScreen, `_check_shock_window`) are absent from this worktree's source but are delivered by the parallel Phase 26 worktree — they will merge cleanly since no methods overlap.

## Known Stubs

None — all planned functionality wired to real data. `_render_delta` renders real `bracket_deltas` from `read_shock_impact`. No hardcoded empty values flow to UI rendering.

## Next Phase Readiness

- `read_shock_event` and `read_shock_impact` are fully callable — Plan 02 can use them directly in the report section assembler
- BracketPanel delta mode activates automatically post-simulation when a ShockEvent exists
- Plan 02 next: report section template, CLI `--shock` flag, ReportAssembler shock section

---

*Phase: 27-shock-analysis-and-reporting*
*Completed: 2026-04-11*
