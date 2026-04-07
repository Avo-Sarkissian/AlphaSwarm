# Phase 19: Per-Stock TUI Consensus Display - Context

**Gathered:** 2026-04-07
**Status:** Ready for planning

<domain>
## Phase Boundary

After simulation completes (and after each round), the TUI displays a per-ticker consensus panel showing each ticker symbol, aggregate signal, confidence-weighted score, majority-vote percentage, and per-bracket signal breakdown. This is a pure TUI/display phase — no changes to the simulation engine logic, agent prompts, or data model beyond new StateStore fields and the new widget. Data is sourced entirely from `AgentDecision.ticker_decisions` (Phase 18 output) and `influence_weights` (already computed in simulation.py).

</domain>

<decisions>
## Implementation Decisions

### Panel Placement
- **D-01:** New **right-side column** added to `main-row` in `AlphaSwarmApp.compose()`. Layout becomes: `grid-container (30w) | rationale sidebar (1fr) | ticker consensus panel (width=44)`. The panel is always rendered (visible during live rounds showing "Awaiting..." per round, updating after each round fires).
- **D-02:** `BracketPanel` stays in `bottom-row` unchanged. The new `TickerConsensusPanel` is independent — it shows ticker-level data, bracket panel shows global bracket-level data.

### Update Timing
- **D-03:** Ticker consensus **updates after each round** (Round 1 → Round 2 → Round 3). Not only at COMPLETE. After each round completes in `simulation.py`, compute ticker consensus from that round's decisions and push to `StateStore`. The panel shows the current round's consensus evolving across all 3 rounds.
- **D-04:** Round label shown per ticker: `"R1"`, `"R2"`, `"R3"` (or `"Final"` at COMPLETE). This lets the user see consensus shifting across rounds.

### Data Model (StateStore / StateSnapshot)
- **D-05:** New frozen dataclass `TickerConsensus` in `state.py`:
  ```python
  @dataclass(frozen=True)
  class TickerConsensus:
      ticker: str
      round_num: int
      weighted_signal: str     # "BUY" / "SELL" / "HOLD"
      weighted_score: float    # 0.0–1.0 (confidence-weighted sum)
      majority_signal: str     # "BUY" / "SELL" / "HOLD"
      majority_pct: float      # percentage of valid votes for majority signal
      bracket_breakdown: tuple[BracketSummary, ...]  # per-bracket for this ticker only
  ```
- **D-06:** `StateSnapshot` gains: `ticker_consensus: tuple[TickerConsensus, ...] = ()`.
- **D-07:** `StateStore` gains: `async def set_ticker_consensus(self, consensus: tuple[TickerConsensus, ...]) -> None` — same pattern as `set_bracket_summaries()`.

### Consensus Computation
- **D-08:** After each round in `simulation.py`, a new `compute_ticker_consensus()` function iterates over all `AgentDecision.ticker_decisions` for that round, grouped by ticker. For each ticker:
  - **Majority vote**: count BUY/SELL/HOLD from all agents' `TickerDecision.direction`. Dominant signal = majority; `majority_pct` = dominant count / total valid votes × 100.
  - **Confidence-weighted**: sum `decision.confidence × influence_weights.get(agent_id, base_weight)` per signal direction. Weighted signal = direction with highest weighted sum; `weighted_score` = that sum / total weighted sum.
  - **Bracket breakdown**: same `compute_bracket_summaries()` logic but filtered to agents with a `TickerDecision` for this ticker. Reuses `BracketSummary` dataclass — no new type needed.
- **D-09:** Agents with empty `ticker_decisions` (PARSE_ERROR fallback) are excluded from all ticker consensus computation. `influence_weights` from the current round are used; fallback to `persona.influence_weight_base` if an agent's ID is absent from the weights dict.

### Widget (TUI)
- **D-10:** New `TickerConsensusPanel(Widget)` in `tui.py`. Pattern mirrors `BracketPanel.render() -> Text`. TCSS: `width: 44`, `height: 100%`, `border-left: solid $secondary`.
- **D-11:** Display format — header line per ticker: `AAPL  BUY  w=0.74  (68% majority)  R3`. Below each ticker header: 10 bracket mini-bars (same fill-char `█`/`░` pattern as `BracketPanel`, BAR_WIDTH=12). Bar color = dominant signal for that bracket × that ticker.
- **D-12:** With 3 tickers × (1 header + 10 bracket rows + 1 separator) = ~36 rows. Panel must support scrolling via `overflow: auto` or `overflow-y: scroll` TCSS, or use `textual.scroll_view.ScrollView` as container. Vertical scrolling is the correct approach — Textual supports it natively via `can_focus=True` and scroll bindings.
- **D-13:** When no tickers are present in the snapshot (simulation ran without ticker extraction), panel shows: `"No tickers\nextracted"` in `#78909C` gray.
- **D-14:** `_poll_snapshot()` diffs `snapshot.ticker_consensus != self._prev_ticker_consensus` to trigger `TickerConsensusPanel.update_consensus(...)`. Same diff pattern as bracket panel.

### Claude's Discretion
- Exact TCSS scroll implementation (ScrollView vs overflow property)
- Whether bracket bar label in the ticker panel uses full display name or abbreviated (e.g. "Quants" vs "QUA")
- Exact round label display (`R1`/`R2`/`R3`/`Final` vs `Round 1` etc.)
- Test fixture approach (real `TickerConsensus` instances vs mocked StateSnapshot)
- Whether `compute_ticker_consensus()` lives in `simulation.py` or a new `consensus.py` module

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & Roadmap
- `.planning/ROADMAP.md` — Phase 19 goal, success criteria (3 criteria), DTUI-01/02/03 requirement IDs
- `.planning/REQUIREMENTS.md` — v3 requirements section (DTUI entries)

### Phase 18 Output (Primary — ticker decisions produced here)
- `src/alphaswarm/types.py` — `TickerDecision` (line 169), `AgentDecision.ticker_decisions` (line 186-187), `SignalType`, `SimulationPhase`
- `.planning/phases/18-agent-context-enrichment-and-enhanced-decisions/18-CONTEXT.md` — D-06/D-07/D-08 (TickerDecision schema, direction=SignalType, time_horizon as free string)

### TUI Layer (Extend here)
- `src/alphaswarm/tui.py` — `BracketPanel` (line 314) — exact pattern to mirror for `TickerConsensusPanel`; `AlphaSwarmApp.compose()` (line 706) — add new panel here; `_poll_snapshot()` (~line 810) — add diff + update call; `AlphaSwarmApp.CSS` (~line 620) — add `#ticker-panel` TCSS
- `src/alphaswarm/state.py` — `BracketSummary` (line 32), `StateSnapshot` (line 73), `StateStore` (line 87), `set_bracket_summaries()` (line 177) — template for new `set_ticker_consensus()` method; `snapshot()` (line 191) — add `ticker_consensus` field

### Simulation Integration
- `src/alphaswarm/simulation.py` — `compute_bracket_summaries()` (line 87) — template for new `compute_ticker_consensus()`; `influence_weights` computation pattern (line 693+); round completion points where `set_bracket_summaries()` is called — add `set_ticker_consensus()` call at same points

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `BracketPanel` (`tui.py:314`) — `render() -> Text` with `FILL_CHAR`/`EMPTY_CHAR`/`BAR_WIDTH`/`_SIGNAL_COLORS` — copy this pattern exactly for per-ticker bracket mini-bars
- `BracketSummary` dataclass (`state.py:32`) — already has `buy_count`, `sell_count`, `hold_count`, `total`, `avg_confidence` — reuse for `TickerConsensus.bracket_breakdown` without a new type
- `compute_bracket_summaries()` (`simulation.py:87`) — filter by ticker instead of running globally; same accumulator pattern
- `set_bracket_summaries()` / `_bracket_summaries` pattern (`state.py:177`) — direct template for `set_ticker_consensus()` / `_ticker_consensus`
- `_poll_snapshot()` diff check (`tui.py:~870`) — `if snapshot.bracket_summaries != self._prev_bracket_summaries:` — replicate for ticker consensus

### Established Patterns
- All new state dataclasses: frozen, in `state.py`, accessed only via `StateSnapshot`
- `StateStore` writes: always under `asyncio.Lock` via `async def` methods
- `snapshot()` returns immutable snapshot — `ticker_consensus` field added as `tuple[TickerConsensus, ...]`
- `structlog` logging: `logger = structlog.get_logger(component="tui")` already set
- Widget CSS: declared in `DEFAULT_CSS` class variable; pixel-exact widths

### Integration Points
- `state.py`: Add `TickerConsensus` dataclass + `ticker_consensus: tuple[TickerConsensus, ...]` to `StateSnapshot` + `set_ticker_consensus()` to `StateStore`
- `simulation.py`: Add `compute_ticker_consensus()` function; call `await state_store.set_ticker_consensus(...)` at same points as `set_bracket_summaries()` (after each round)
- `tui.py`: Add `TickerConsensusPanel` widget; wire into `AlphaSwarmApp.compose()` as 3rd column of `main-row`; add `_prev_ticker_consensus` diff state; update `_poll_snapshot()`

</code_context>

<specifics>
## Specific Ideas

- Display format per ticker (from user): `AAPL  BUY  w=0.74  (68% majority)  R3` — weighted signal is primary, majority percentage inline in parens, round label at right
- Mini bracket bars per ticker (from user): same `█░` fill pattern as BracketPanel, BAR_WIDTH=12, one row per bracket. With 3 tickers × 10 brackets the panel needs scrolling — use Textual's native scroll support.
- Round label progression: panel shows round label (`R1`, `R2`, `R3`) so user can see consensus evolving; final round shows `R3` (not a special "Final" label to keep it compact).

</specifics>

<deferred>
## Deferred Ideas

- **Weighted score formula validation** — whether `confidence × influence_weight` is the right weighting (vs `confidence × influence_weight²`) is a tuning question, not a Phase 19 architectural decision. Use linear product for now.
- **Click-to-drill-down** — clicking a ticker row to expand full bracket detail was considered but deferred; mini bars per bracket are already shown inline.
- **Historical round comparison** — showing all 3 rounds simultaneously for one ticker (e.g. sparkline of weighted score) — deferred to a future enhancement phase.
- **`expected_return_pct` and `time_horizon` display** — `TickerDecision` has these fields (Phase 18) but they are not displayed in Phase 19. Reserved for Phase 20 report integration.

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 19-per-stock-tui-consensus-display*
*Context gathered: 2026-04-07*
