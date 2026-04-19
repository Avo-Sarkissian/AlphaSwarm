# Phase 10: TUI Panels and Telemetry - Context

**Gathered:** 2026-03-27
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 10 extends the Textual TUI Core Dashboard (Phase 9) with three new panels: a rationale sidebar streaming high-influence agent reasoning, a hardware telemetry footer displaying live system metrics, and a bracket aggregation panel with per-bracket sentiment progress bars. All panels render non-blocking via the existing 200ms snapshot polling loop. No Miro integration. No new simulation engine changes.

</domain>

<decisions>
## Implementation Decisions

### Dashboard Layout
- **D-01:** Right sidebar + bottom row layout. The full layout hierarchy is:
  1. `HeaderBar` — docked top (unchanged from Phase 9)
  2. Main row (horizontal): `agent-grid` (left, existing) + `RationaleSidebar` (right)
  3. Bottom row (horizontal): `TelemetryFooter` (narrow, left) + `BracketPanel` (wide, right)

  This replaces the Phase 9 `grid-container` centering approach. The grid shifts left to share the main row with the rationale sidebar. The bottom row is docked at the bottom.

### Rationale Sidebar (TUI-03)
- **D-02:** Selection criterion — high influence weight. Entries are populated by the top INFLUENCED_BY edge weight holders each round. The simulation queries influence weights after each round completes (influence topology is already computed in Phase 8) and pushes the highest-weight agents' rationales into an `asyncio.Queue` on `StateStore`. Drains up to 5 entries per 200ms tick per TUI-03.
- **D-03:** Entry format — `> A_42 [BUY] momentum aligns with macro...` — agent short ID, signal in brackets, rationale text truncated at ~50 characters. Signal word is colored per existing theme (green=BUY, red=SELL, gray=HOLD).
- **D-04:** Display style — scrolling log, newest entries prepend at the top. Older entries scroll down and eventually off-screen. Textual's `RichLog` or a prepend-capable `ListView` widget handles this. No pagination controls.

### Telemetry Footer (TUI-04)
- **D-05:** Tokens-per-second — tracked via Ollama eval_count + eval_duration from inference responses. OllamaClient accumulates `cumulative_tokens: int` and `cumulative_eval_ms: float`. A new `update_tps(tokens, eval_ms)` method on `StateStore` computes running TPS and stores it. The snapshot exposes it as `tps: float`.
- **D-06:** Telemetry footer displays 4 metrics inline: `RAM: {memory_percent:.0f}%  |  TPS: {tps:.1f}  |  Queue: {active_count}  |  Slots: {current_slots}`. All data already present in `GovernorMetrics` except TPS (new). "Queue depth" = `GovernorMetrics.active_count` — inference slots currently in use.

### Bracket Aggregation Panel (TUI-05)
- **D-07:** Display style — progress bar per bracket. Each of the 10 brackets renders as one row: `BracketName  [████░░░░░] 80%`. Bar fill = dominant signal percentage. Bar color = dominant signal (green for BUY-dominant, red for SELL-dominant, gray for HOLD-dominant). Uses the existing ALPHASWARM_THEME color constants.
- **D-08:** Scope — all 10 brackets always shown. Update trigger: on round completion (`RoundCompleteEvent` already carries `BracketSummary` list from Phase 8). StateStore gets a `set_bracket_summaries(summaries: list[BracketSummary])` method.

### Claude's Discretion
- Textual widget choices for the progress bar (custom `ProgressBar` subclass vs. `Static` with rich markup bars)
- Exact CSS for the new layout containers (widths/heights for sidebar and bottom row)
- How `asyncio.Queue` is exposed on `StateStore` — whether rationale entries are pushed by simulation.py or by a dedicated high-influence selector post-round
- Whether `TelemetryFooter` uses `set_interval` independently or reads from the same 200ms snapshot tick as the rest of the TUI

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing TUI Implementation (Primary)
- `src/alphaswarm/tui.py` — `AlphaSwarmApp`, `AgentCell`, `HeaderBar`, `ALPHASWARM_THEME`. Phase 9 layout to be extended. Contains `_poll_snapshot()` — the 200ms timer that drives all rendering.
- `src/alphaswarm/state.py` — `StateStore`, `StateSnapshot`, `GovernorMetrics`, `AgentState`. GovernorMetrics already has `current_slots`, `active_count`, `memory_percent`. Needs: `asyncio.Queue` for rationale entries, `tps: float`, `bracket_summaries: list[BracketSummary]`.
- `src/alphaswarm/app.py` — `AppState` and `create_app_state()` factory. StateStore is already wired in.
- `src/alphaswarm/ollama_client.py` — `OllamaClient`. Needs `eval_count` + `eval_duration` extraction from Ollama response metadata to feed TPS tracking.

### Simulation Engine (Phase 8 outputs consumed by Phase 10)
- `src/alphaswarm/simulation.py` — `run_simulation()`, `RoundCompleteEvent`, `SimulationResult`. `RoundCompleteEvent` carries `bracket_summaries: list[BracketSummary]` — needs to call `state_store.set_bracket_summaries()` after each round.
- `src/alphaswarm/graph.py` — `GraphStateManager.read_peer_decisions()` — influence weights for top-N agents available here. Post-round rationale queue population reads from here.

### Requirements
- `.planning/REQUIREMENTS.md` — TUI-03 (rationale sidebar: asyncio.Queue, ≤5 per tick), TUI-04 (telemetry: RAM, TPS, queue depth, slots), TUI-05 (bracket aggregation panel, updated per round)
- `.planning/ROADMAP.md` — Phase 10 success criteria (4 criteria)

### Prior Phase Context
- `.planning/phases/09-tui-core-dashboard/09-CONTEXT.md` — D-01 (Worker pattern), D-02 (per-agent snapshot writes), D-04/D-05 (cell color logic), D-06 (header format). Layout being extended in Phase 10.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `ALPHASWARM_THEME` in `tui.py` — color constants (`#4FC3F7` primary, `#66BB6A` success/green, `#EF5350` error/red, `#78909C` secondary/gray). Use these for bracket bar colors.
- `compute_cell_color()` in `tui.py` — HSL color logic. Bracket bars should mirror same green/red/gray semantics.
- `GovernorMetrics` in `state.py` — already has `current_slots`, `active_count`, `pressure_level`, `memory_percent`. TUI-04 is mostly wired; only TPS is new.
- `BracketSummary` in Phase 8 — `dominant_signal`, `bullish_pct`, `bearish_pct`, `hold_pct` fields. Ready for bracket panel rendering.
- `_poll_snapshot()` in `tui.py` — existing 200ms timer. All new panel updates hang off this same callback.

### Integration Points
- `state.py` — Add: `asyncio.Queue` for rationale entries (with `push_rationale()` method), `tps: float` field + `update_tps()`, `bracket_summaries` list + `set_bracket_summaries()`, expose all in `StateSnapshot`.
- `ollama_client.py` — Extract `eval_count` and `eval_duration` from Ollama response; pass to `state_store.update_tps()`.
- `simulation.py` — After each round, call `state_store.set_bracket_summaries(bracket_summaries)`. Post-round, query top-N influence weights and push rationale entries to queue.
- `tui.py` — Restructure layout: replace `grid-container` centering with main-row + bottom-row composition. Add `RationaleSidebar`, `TelemetryFooter`, `BracketPanel` widgets. Update `_poll_snapshot()` to drain rationale queue and refresh telemetry/bracket panels.

</code_context>

<deferred>
## Deferred Ideas

- Seed rumor text display in header — noted as deferred from Phase 9, still not in Phase 10 requirements (TUI-03/04/05). Not in scope.
- Agent hover tooltip (signal + confidence + rationale preview) — out of Phase 10 scope.
- Bracket row grouping in agent grid — sequential layout decided in Phase 9; bracket grouping could be a later enhancement.

</deferred>

---

*Phase: 10-tui-panels-and-telemetry*
*Context gathered: 2026-03-27*
