---
phase: 19-per-stock-tui-consensus-display
verified: 2026-04-07T21:40:00Z
status: passed
score: 19/19 must-haves verified
---

# Phase 19: Per-Stock TUI Consensus Display Verification Report

**Phase Goal:** Users see the payoff of live data grounding — per-ticker consensus breakdown in the TUI showing which stocks agents are bullish/bearish on, how confident they are, and where brackets disagree.
**Verified:** 2026-04-07T21:40:00Z
**Status:** PASSED
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | TickerConsensus dataclass exists, is frozen, and holds all required fields including both weighted_signal and majority_signal | VERIFIED | `src/alphaswarm/state.py` lines 49-63: `@dataclass(frozen=True) class TickerConsensus` with 7 fields |
| 2 | StateStore.set_ticker_consensus() stores data and exposes it via snapshot() | VERIFIED | `state.py` lines 205-208: async method with lock; line 245: `ticker_consensus=self._ticker_consensus` in snapshot() |
| 3 | compute_ticker_consensus() computes correct majority signal and percentage | VERIFIED | `simulation.py` lines 238-249: max() with tie-break key; majority_pct stored as fraction |
| 4 | compute_ticker_consensus() computes correct confidence-weighted signal and score | VERIFIED | `simulation.py` lines 220, 243-246, 250: `weighted_sums[dir] += dec.confidence * w`; weighted_score normalized |
| 5 | Bracket breakdown is ticker-scoped using TickerDecision.direction, NOT AgentDecision.signal | VERIFIED | `simulation.py` lines 222-226: explicit comment "Per-ticker bracket accumulation using td.direction (NOT dec.signal)" |
| 6 | PARSE_ERROR agents are excluded from all ticker consensus computation | VERIFIED | `simulation.py` lines 173, 202: `if dec.signal == SignalType.PARSE_ERROR: continue`; defensive td.direction check at line 211 |
| 7 | Division by zero is guarded when no valid votes exist | VERIFIED | `simulation.py` lines 249-250: `if total_votes > 0 else 0.0` and `if total_weighted > 0.0 else 0.0` |
| 8 | Tie-break is deterministic: BUY > HOLD > SELL priority | VERIFIED | `simulation.py` line 146: `_TIE_BREAK_ORDER: dict[str, int] = {"BUY": 0, "HOLD": 1, "SELL": 2}`; applied in max() key |
| 9 | Ticker strings are normalized to uppercase before aggregation | VERIFIED | `simulation.py` lines 178, 207: `td.ticker.upper()` in both ticker collection and per-ticker loop |
| 10 | majority_pct stored as 0.0-1.0 fraction, not 0-100 percentage | VERIFIED | `simulation.py` line 249: `majority_counts[majority_signal] / total_votes`; `state.py` line 62 comment: "0.0-1.0 (fraction of valid votes...)" |
| 11 | TUI displays a TickerConsensusPanel as the rightmost column in main-row | VERIFIED | `tui.py` line 834: `yield self._ticker_consensus_panel` inside `with Container(id="main-row")`, placed after `_rationale_sidebar` |
| 12 | Each ticker shows BOTH weighted_signal AND majority_signal explicitly in the header line | VERIFIED | `tui.py` lines 464-473: separate `w:` and `m:` label segments with distinct signals and scores |
| 13 | When weighted and majority disagree, both are independently visible to the user | VERIFIED | Format renders both signals with independent color and value; `test_ticker_consensus_panel_render_header_both_signals` confirms BUY and SELL visible simultaneously |
| 14 | Each ticker has bracket mini-bars showing per-bracket signal distribution | VERIFIED | `tui.py` lines 476-487: per-bracket loop rendering `s.display_name`, fill/empty Unicode block chars |
| 15 | Panel shows 'Awaiting R{n}...' when simulation is active but consensus not yet pushed | VERIFIED | `tui.py` line 450: `text.append(f"Awaiting R{self._round_num}...\n", ...)` when phase not IDLE/COMPLETE |
| 16 | Panel shows 'No tickers extracted' only when simulation is idle with no data | VERIFIED | `tui.py` lines 449-452: separate code path when phase is IDLE or COMPLETE |
| 17 | Panel updates after each round via _poll_snapshot diff check | VERIFIED | `tui.py` lines 1017-1028: diff on `snapshot.ticker_consensus != self._prev_ticker_consensus` (plus phase/round changes) |
| 18 | Panel scrolls vertically when content exceeds viewport height | VERIFIED | `tui.py` line 401: `overflow-y: auto` in `TickerConsensusPanel` DEFAULT_CSS |
| 19 | majority_pct displayed as percentage (multiply 0.0-1.0 fraction by 100 for display) | VERIFIED | `tui.py` line 473: `tc.majority_pct * 100:.0f` |

**Score:** 19/19 truths verified

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/alphaswarm/state.py` | TickerConsensus dataclass + StateStore.set_ticker_consensus() + StateSnapshot.ticker_consensus field | VERIFIED | All 3 additions present at lines 49-63, 102, 205-208 |
| `src/alphaswarm/simulation.py` | compute_ticker_consensus() function with custom per-ticker bracket aggregator + 3 call sites at round completion | VERIFIED | Function at lines 149-279; call sites at lines 1117, 1254, 1383 |
| `tests/test_state.py` | Tests for TickerConsensus frozen dataclass and StateStore ticker consensus storage | VERIFIED | 5 tests: `test_ticker_consensus_frozen`, `test_ticker_consensus_fields`, `test_set_ticker_consensus`, `test_snapshot_ticker_consensus_default`, `test_state_snapshot_includes_ticker_consensus` |
| `tests/test_simulation.py` | Tests for compute_ticker_consensus majority, weighted, bracket scope, tie-break, ticker normalization, integration wiring | VERIFIED | 11 tests matching all required behaviors including `test_compute_ticker_consensus_majority`, `test_compute_ticker_consensus_bracket_scope_uses_direction`, `test_compute_ticker_consensus_simulation_wiring` |
| `src/alphaswarm/tui.py` | TickerConsensusPanel widget, compose() wiring, _poll_snapshot() diff update with phase/round context | VERIFIED | Class at lines 385-494; compose wiring at line 834; poll wiring at lines 1017-1028 |
| `tests/test_tui.py` | Tests for panel render output, empty state, awaiting state, bracket bars, both signals visible, disagreement case | VERIFIED | 9 tests including `test_ticker_consensus_panel_render_header_both_signals` (disagreement), `test_ticker_consensus_panel_awaiting_state_round1` |

---

## Plan 01 Checklist (Explicit Must-Have Items)

| Item | Status | Location |
|------|--------|----------|
| `class TickerConsensus` frozen dataclass with all required fields | VERIFIED | `state.py` lines 49-63 |
| `weighted_signal`, `majority_signal`, `majority_pct`, `bracket_breakdown` fields | VERIFIED | `state.py` lines 59-63 |
| `StateStore.set_ticker_consensus()` method | VERIFIED | `state.py` lines 205-208 |
| `StateSnapshot.ticker_consensus` field | VERIFIED | `state.py` line 102 |
| `compute_ticker_consensus()` in simulation.py | VERIFIED | `simulation.py` line 149 |
| Called at 3 round-completion points | VERIFIED | Lines 1117, 1254, 1383 |
| PARSE_ERROR agents excluded | VERIFIED | Lines 173, 202, 211 |
| Tie-break deterministic (BUY > HOLD > SELL) | VERIFIED | Lines 146, 241, 245 |
| majority_pct stored as 0.0-1.0 fraction | VERIFIED | Line 249; comment on line 62 of state.py |
| `_TIE_BREAK_ORDER` constant defined | VERIFIED | `simulation.py` line 146 |

---

## Plan 02 Checklist (Explicit Must-Have Items)

| Item | Status | Location |
|------|--------|----------|
| `class TickerConsensusPanel(Widget)` exists | VERIFIED | `tui.py` line 385 |
| `width: 44` in DEFAULT_CSS | VERIFIED | `tui.py` line 396 |
| `overflow-y: auto` in DEFAULT_CSS | VERIFIED | `tui.py` line 401 |
| `BAR_WIDTH = 12` in TickerConsensusPanel | VERIFIED | `tui.py` line 407 |
| `can_focus = False` | VERIFIED | `tui.py` line 416 |
| `update_consensus(self, consensus, phase, round_num)` method | VERIFIED | `tui.py` lines 424-438 |
| "Awaiting R" text in render method | VERIFIED | `tui.py` line 450: `f"Awaiting R{self._round_num}..."` |
| "No tickers" text in render method | VERIFIED | `tui.py` line 452: `"No tickers\nextracted\n"` |
| "w:" and "m:" labels in render (dual-signal display) | VERIFIED | `tui.py` lines 464, 470 |
| `tc.majority_pct * 100` conversion in render | VERIFIED | `tui.py` line 473 |
| `yield self._ticker_consensus_panel` in compose() | VERIFIED | `tui.py` line 834 |
| `snapshot.ticker_consensus != self._prev_ticker_consensus` in _poll_snapshot() | VERIFIED | `tui.py` line 1019 |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `simulation.py` | `state.py` | `compute_ticker_consensus` returns `tuple[TickerConsensus, ...]` stored via `set_ticker_consensus` | WIRED | `await state_store.set_ticker_consensus(compute_ticker_consensus(...))` at all 3 round sites |
| `simulation.py` | `state.py` | `snapshot().ticker_consensus` exposes stored data to TUI | WIRED | `ticker_consensus=self._ticker_consensus` in `snapshot()` at line 245 |
| `tui.py TickerConsensusPanel` | `state.py TickerConsensus` | `update_consensus(snapshot.ticker_consensus, snapshot.phase, snapshot.round_num)` | WIRED | `tui.py` line 1023-1025: passes all 3 params |
| `tui.py _poll_snapshot` | `tui.py TickerConsensusPanel` | diff check triggers `update_consensus` with phase context | WIRED | Lines 1017-1028: diff on consensus + phase + round_num |
| `tui.py compose()` | `tui.py TickerConsensusPanel` | `yield self._ticker_consensus_panel` in main-row container | WIRED | Line 834 inside `with Container(id="main-row")` |

---

## Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `TickerConsensusPanel.render()` | `self._consensus` | `update_consensus()` <- `_poll_snapshot()` <- `StateStore.snapshot().ticker_consensus` <- `StateStore.set_ticker_consensus()` <- `compute_ticker_consensus()` <- round decisions | Yes — draws from live agent decisions with confidence weights; not static | FLOWING |
| `compute_ticker_consensus()` | `majority_counts`, `weighted_sums` | Iterates `agent_decisions` list from actual round results; reads `TickerDecision.direction` per ticker | Yes — aggregates real per-agent vote data | FLOWING |

---

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| All ticker consensus TUI tests pass | `uv run pytest tests/test_tui.py -k "test_ticker_consensus" -q` | 9 passed, 29 deselected in 0.06s | PASS |
| Full suite (minus Neo4j integration) passes | `uv run pytest --ignore=tests/test_graph_integration.py -q` | 603 passed, 4 warnings in 15.98s | PASS |

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| DTUI-01 | 19-01, 19-02 | Per-ticker consensus panel visible in TUI showing ticker symbol, aggregate signal, aggregate confidence, vote distribution | SATISFIED | `TickerConsensusPanel` renders per-ticker header lines; `compose()` wires it as rightmost main-row column |
| DTUI-02 | 19-01, 19-02 | Both confidence-weighted voting and discrete majority vote computed and visible, even when they disagree | SATISFIED | Dual `w:` and `m:` labels with independent signal values; `test_ticker_consensus_panel_render_header_both_signals` verifies disagreement case |
| DTUI-03 | 19-01, 19-02 | Per-bracket signal distribution visible for each ticker | SATISFIED | Custom bracket aggregator uses `TickerDecision.direction`; 10 bracket mini-bars rendered per ticker |

---

## Roadmap Success Criteria

| # | Success Criterion | Status | Evidence |
|---|-------------------|--------|----------|
| 1 | After simulation completes, TUI displays per-ticker consensus panel showing ticker symbol, aggregate signal, aggregate confidence, and vote distribution | SATISFIED | `TickerConsensusPanel` renders all four data points per ticker; wired to snapshot polling |
| 2 | Consensus aggregation uses confidence-weighted voting (confidence multiplied by influence_weight) alongside discrete majority vote, and both are visible in display | SATISFIED | `weighted_sums[dir] += dec.confidence * w` with fallback to `persona.influence_weight_base`; both `w:` and `m:` rendered |
| 3 | For each ticker, user can see which brackets are bullish vs bearish, making inter-bracket disagreement visually clear | SATISFIED | Per-ticker bracket breakdown uses `TickerDecision.direction` (not global signal); 10 mini-bars with fill chars rendered |

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| None | — | No placeholders, stub returns, TODO markers, or empty implementations found in Phase 19 additions | — | — |

No anti-patterns detected. The `TickerConsensusPanel` has substantive render logic. The `compute_ticker_consensus()` function is fully implemented with real aggregation. All state wiring is complete.

---

## Human Verification Required

### 1. Visual TUI Layout

**Test:** Run a full simulation and observe the TUI at round completion.
**Expected:** TickerConsensusPanel appears as the rightmost column in main-row, right of the rationale sidebar, with per-ticker lines showing `w:BUY 0.74 | m:SELL (54%) R1` format and bracket mini-bars below each ticker.
**Why human:** Visual layout correctness (column width=44, border, scroll behavior) cannot be confirmed without rendering the live Textual TUI. The CSS is present but pixel-accurate layout requires a running terminal.

### 2. "Awaiting R{n}..." Live Transition

**Test:** Observe the panel during Round 1 execution before any `set_ticker_consensus` call completes.
**Expected:** Panel displays "Awaiting R1..." (not "No tickers extracted") while agents are running.
**Why human:** Requires real-time observation of transient state between phase transition and first consensus push. Tests cover this logic path but the live timing of the transition cannot be automated without a running simulation.

---

## Gaps Summary

No gaps. All 19 must-haves verified across both plans. All 3 ROADMAP success criteria satisfied. The 603-test suite passes cleanly (excluding the pre-existing Neo4j Docker integration test, which is unrelated to Phase 19). The two items flagged for human verification are visual/real-time checks that cannot be automated without a live Textual terminal — they do not block goal achievement.

---

_Verified: 2026-04-07T21:40:00Z_
_Verifier: Claude (gsd-verifier)_
