---
phase: 19
reviewers: [gemini, codex]
reviewed_at: 2026-04-07T16:00:00-04:00
plans_reviewed: [19-01-PLAN.md, 19-02-PLAN.md]
---

# Cross-AI Plan Review — Phase 19

## Gemini Review

# Cross-AI Plan Review: Phase 19

The implementation plans for **Phase 19: Per-Stock TUI Consensus Display** are exceptionally well-structured and provide a surgically precise roadmap for delivering the required features. They leverage existing architectural patterns—specifically mirroring the `BracketPanel` and `StateStore` snapshotting—to ensure consistency and minimize technical debt.

## Summary
These plans provide a clean separation between data aggregation logic (Plan 01) and visual representation (Plan 02). By extending the `StateStore` and wiring the consensus computation directly into the simulation's round-completion hooks, the design ensures that the TUI remains a passive, high-performance observer of the simulation state. The TDD-focused verification strategy is robust, covering edge cases like division-by-zero and `PARSE_ERROR` exclusions that are critical for stable aggregation in a multi-agent system.

## Strengths
- **Architectural Symmetry:** Reusing the `BracketPanel` logic and `BracketSummary` dataclass is highly efficient and ensures that the "per-ticker" view feels like a natural extension of the global "bracket" view.
- **Robust Data Normalization:** The explicit handling of `SignalType` case normalization (D-09) and the fallback mechanism for influence weights (D-09) prevent subtle bugs in the consensus math.
- **Performance-First TUI Design:** Using `overflow-y: auto` with diff-based updates in `_poll_snapshot` adheres to the project's requirement to decouple agent throughput from render throughput, preventing TUI lag during peak inference.
- **Detailed TDD Framework:** The plans include specific unit and integration tests for every new behavior, including "plain-text" render assertions that are effective for verifying TUI output without a complex visual test harness.

## Concerns
- **Round 3 Influence Data (LOW):** Plan 01 uses `round2_weights` for the Round 3 consensus computation. While this avoids an extra Neo4j query and matches existing patterns, it technically means the "influence" weighting for the final consensus doesn't reflect any new citations made during the third round. Given the local compute constraints, this is a reasonable trade-off but should be documented as a known design choice.
- **Vertical Clipping (LOW):** With 12 lines per ticker and a 3-ticker cap, the panel will require 36+ lines of vertical space. While `overflow-y: auto` is implemented, users with standard 24-line terminals will always be in a scroll state. This is mitigated by the scroll support, but visual density should be monitored during the human-verification task.
- **Tie-Breaking Determinism (LOW):** In `compute_ticker_consensus`, the plan uses `max(dict, key=...)`. If two signals have identical counts/weights, the winner depends on Python's dictionary insertion order (which is deterministic in 3.11+ but potentially unexpected). A consistent tie-break (e.g., BUY > HOLD > SELL) would be safer for reproducible research.

## Suggestions
- **Dynamic Progress Indicators:** In the TickerConsensusPanel's empty/awaiting state, consider showing which round the simulation is currently in (e.g., "Awaiting Round 1...") to provide better feedback during the 100-agent inference waves.
- **Helper Extraction:** If the mini-bar rendering logic becomes more complex than the global version, consider refactoring the bar-drawing logic into a shared utility function between `BracketPanel` and `TickerConsensusPanel` to ensure visual parity.

## Risk Assessment
- **Overall Risk: LOW**
- **Justification:** The plans introduce no new external dependencies or inference calls. They rely on established, validated patterns for state management and TUI rendering. The primary risks (math errors or layout breaks) are thoroughly addressed by the TDD tasks and the explicit UI-SPEC constraints.

**Verdict: Approved. Proceed to Execution.**

---

## Codex Review

**Cross-Plan Note**

Both plans are well-structured and mostly mirror the existing seams in `state.py`, `simulation.py`, and `tui.py`. The main problem is upstream contract drift: the supplied plan text, `19-CONTEXT.md`, and `19-UI-SPEC.md` disagree on layout, `bracket_breakdown` type, `majority_pct` semantics, and scroll behavior. That should be normalized before execution.

### Plan 01 Review

**Summary**

Plan 01 is strong on structure, sequencing, and TDD discipline. It uses the right extension points in `state.py` and `simulation.py`, and it stays within phase scope. The biggest issue is correctness: the current plan would likely compute the per-ticker bracket breakdown incorrectly and has a few contract inconsistencies that can cause either wrong data or misleading tests.

**Strengths**
- Clear dependency split: data layer first, UI later.
- Good reuse of existing patterns from `StateStore` in `state.py` and `compute_bracket_summaries` in `simulation.py`.
- TDD coverage is broad for majority vote, weighted vote, fallback weights, and `PARSE_ERROR` exclusion.
- Scope is controlled. No unnecessary new module or persistence layer.

**Concerns**
- `HIGH`: The planned `bracket_breakdown = compute_bracket_summaries(ticker_agent_subset, ...)` is logically wrong if `ticker_agent_subset` still contains original `AgentDecision` objects. `compute_bracket_summaries` counts `decision.signal`, not `TickerDecision.direction`, so ticker bars can reflect global sentiment instead of per-ticker sentiment.
- `HIGH`: The plan contract is inconsistent on `TickerConsensus.bracket_breakdown` and `majority_pct`. The top-level plan says `dict[str, str]` and `0.0-1.0`; the phase docs say `tuple[BracketSummary, ...]` and percentage `0-100`.
- `HIGH`: The "division by zero" test case is incompatible with the proposed algorithm. If tickers are collected only from non-`PARSE_ERROR` decisions, "all PARSE_ERROR agents" should produce an empty tuple, not a zeroed `TickerConsensus`.
- `MEDIUM`: Round 3 uses `round2_weights`, but `19-CONTEXT.md` says current-round influence weights should be used. That needs an explicit decision, not an implementation convenience.
- `MEDIUM`: Tie-break behavior is underspecified. The plan claims alphabetical tie-breaks, but `max()` on the initialized dict will follow insertion order, not alphabetical order.
- `MEDIUM`: No integration test proves `run_simulation(..., state_store=...)` actually populates `snapshot().ticker_consensus` at the three round-completion points in `simulation.py`.
- `LOW`: Ticker normalization and duplicate ticker decisions per agent are not addressed, which can split consensus rows (`aapl` vs `AAPL`) or double-count a single agent.

**Suggestions**
- Replace the bracket reuse shortcut with a true ticker-scoped bracket aggregator, or create transformed per-ticker decisions before calling `compute_bracket_summaries`.
- Standardize the `TickerConsensus` schema once in the phase docs and both plans before implementation.
- Decide explicitly whether Round 3 weighted consensus uses `round3_weights` or "latest available weights," then align tests and wording.
- Replace the impossible zero-vote test with either "returns empty tuple" or a design that accepts an explicit ticker universe.
- Add one integration test around `run_simulation` + `StateStore` to verify the state flow, not just grep for call sites.

**Risk Assessment**

`HIGH` risk. The implementation path is straightforward, but one core algorithmic mistake would make DTUI-03 wrong even if tests are mostly green.

### Plan 02 Review

**Summary**

Plan 02 is clean, incremental, and consistent with the existing `BracketPanel`/`_poll_snapshot()` pattern in `tui.py`. The main weaknesses are product-contract gaps: it does not clearly satisfy "both voting methods visible" when weighted and majority disagree, and it does not properly distinguish "awaiting round data" from "no tickers extracted."

**Strengths**
- Good reuse of existing widget and diff-update patterns.
- Minimal surface area: one widget, compose wiring, poll wiring, tests.
- Human verification checkpoint is appropriate for a TUI layout change.
- Avoids over-engineering and keeps the panel read-only.

**Concerns**
- `HIGH`: The display format shows `weighted_signal` and `majority_pct`, but not `majority_signal`. If weighted and majority disagree, DTUI-02 is not actually visible to the user.
- `HIGH`: The plan collapses "no tickers extracted" and "waiting for round output" into one state, while `19-UI-SPEC.md` explicitly distinguishes empty state from `Awaiting R{n}...`.
- `MEDIUM`: Layout is not fully reconciled. Current app CSS uses `#grid-container { width: 1fr; }` in `tui.py`, while the locked decision and phase docs disagree on whether the grid or rationale panel should flex. The plan chooses one variant without resolving the conflict.
- `MEDIUM`: The plan says no CSS changes are needed, but a third fixed-width column can pressure smaller viewports and existing headless tests.
- `MEDIUM`: Tests are render-only. There is no app-level test proving `_poll_snapshot()` updates the new panel the same way it updates the bracket panel.
- `LOW`: Reusing `BracketPanel._dominant_signal()` creates UI-to-UI coupling. It works, but a shared helper would be cleaner.

**Suggestions**
- Show both aggregations explicitly, for example `w: BUY 0.74 | maj: SELL 54%`, not just percentage.
- Add a separate awaiting state driven by `snapshot.phase`/`snapshot.round_num`; the panel likely needs phase context, not just consensus data.
- Resolve the layout contract before implementation and adjust test viewport sizes accordingly.
- Add one headless app test that seeds `StateStore.ticker_consensus`, calls `_poll_snapshot()`, and asserts the panel updated.
- Verify the chosen scroll behavior once against Textual 8.1.1 and document the final `can_focus` decision.

**Risk Assessment**

`MEDIUM-HIGH` risk. The coding work is simple, but the current UI contract can still miss DTUI-02 and mislead users during live rounds unless the display semantics are tightened.

---

## Consensus Summary

### Agreed Strengths
- Both reviewers confirm the **BracketPanel/StateStore mirror pattern** is the right architectural choice — zero new dependencies, leverages validated seams
- Both praise the **TDD discipline** and broad coverage of edge cases (PARSE_ERROR exclusion, fallback weights, division-by-zero)
- Both confirm **diff-based `_poll_snapshot()` polling** is correct for decoupling inference throughput from render latency
- Both agree **scope is well-controlled** — pure wiring phase with no unnecessary new modules

### Agreed Concerns
1. **[HIGH] Bracket breakdown algorithm correctness (Plan 01)** — Codex flags that calling `compute_bracket_summaries()` on `AgentDecision` objects for a ticker subset counts `decision.signal` (global), not `TickerDecision.direction` (per-ticker). This is a logic bug that would make DTUI-03 display global sentiment instead of ticker-scoped sentiment.
2. **[HIGH] DTUI-02 visibility gap (Plan 02)** — Codex flags that the display format shows `weighted_signal` but not `majority_signal`. If the two disagree, the user cannot see both — violating DTUI-02. Gemini does not flag this explicitly but notes "both visible" is a success criterion.
3. **[MEDIUM] Round 3 uses `round2_weights` — needs explicit documentation** — Both reviewers note this is a design choice that should be explicit, not implicit.
4. **[LOW] Tie-breaking determinism** — Both flag `max()` on dict won't produce alphabetical tie-breaks as claimed; Python 3.11+ insertion order is deterministic but not alphabetical.

### Divergent Views
- **Risk level:** Gemini rates overall risk LOW; Codex rates Plan 01 HIGH and Plan 02 MEDIUM-HIGH. The divergence stems from Codex actually reading the live codebase and finding the `compute_bracket_summaries` / `TickerDecision.direction` discrepancy — a real bug that Gemini's review missed because it reasoned from the plan text alone.
- **Empty state handling:** Codex flags the "awaiting vs. no data" state collapse as HIGH; Gemini suggests a dynamic "Awaiting Round N..." indicator as a LOW-priority improvement. Codex's framing is more precise — the UI-SPEC already specifies this distinction, so it's a plan gap rather than a suggestion.
