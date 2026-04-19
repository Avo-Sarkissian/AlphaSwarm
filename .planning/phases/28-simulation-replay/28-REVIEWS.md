---
phase: 28
reviewers: [gemini, codex]
reviewed_at: 2026-04-12T00:00:00Z
plans_reviewed: [28-01-PLAN.md, 28-02-PLAN.md, 28-03-PLAN.md]
---

# Cross-AI Plan Review — Phase 28: Simulation Replay

---

## Gemini Review

# Implementation Plan Review: Phase 28 — Simulation Replay

Phase 28 establishes a read-only replay mechanism for AlphaSwarm, allowing users to visualize past simulation cycles without re-running LLM inference. The plans effectively bridge the existing Textual TUI rendering pipeline with a new `ReplayStore` and optimized Neo4j read patterns.

## Summary
The implementation strategy is logically tiered into three waves: foundational data types and graph read methods (Plan 01), CLI/TUI integration logic (Plan 02), and human verification (Plan 03). The approach wisely avoids side-effect-heavy `StateStore` reuse, instead implementing a parallel `ReplayStore` that satisfies the existing `StateSnapshot` contract. This minimizes the risk of state corruption and visual stuttering. The performance-critical path (`read_full_cycle_signals`) is well-designed using flat-row aggregation to maximize Neo4j index utility.

## Strengths
- **State Separation:** The use of a dedicated `ReplayStore` avoids the destructive queue-drain behavior of the `StateStore`, ensuring that replaying doesn't interfere with or get corrupted by the live simulation data structures.
- **Performance Optimization:** The decision to use flat rows for `read_full_cycle_signals` rather than `COLLECT` aggregations is a mature optimization that ensures the `$cycle_id` composite index is hit efficiently, easily meeting the <2s success criteria.
- **Zero-Inference Mode:** The CLI handler (`_handle_replay`) correctly initializes `AppState` with `with_ollama=False`. This ensures replay mode is truly independent of local LLM availability and prevents cold-loading large models for data visualization.
- **UX Continuity:** Reusing the existing `AlphaSwarmApp` and its 200ms polling tick ensures that the replay experience (cell coloring, sidebar entries) feels identical to a live simulation.
- **Comprehensive Testing:** The inclusion of Wave 0 tests for Cypher parameters, Argparse contracts, and Enum extensions before implementation ensures a high-confidence integration.

## Concerns
- **`ReplayStore.snapshot()` Efficiency** — **LOW**: Current logic iterates through the full signals dict (300 items) to filter by `round_num` every 200ms. While negligible for 300 items, a more performant pattern would be to pre-cache the per-round dicts in `ReplayStore` during `set_round()`.
- **Rationale Truncation Sync** — **LOW**: Plan 02 Task 2 helper `_load_replay_round_data` truncates rationales to 50 chars. Ensure this logic is kept in sync with any future changes to the `RationaleSidebar` width to prevent layout breaking during replay vs live modes.
- **Neo4j DateTime Objects** — **MEDIUM**: The `CyclePickerScreen` needs to handle the `neo4j.time.DateTime` object. Plan 02 includes a `.to_native()` check, but ensure this handles the case where Neo4j might return UTC vs Local time correctly to avoid confusing the user in the picker list.

## Suggestions
- **Visual Step Indicator:** In `HeaderBar.render_replay_header`, consider adding a small indicator when the timer is close to firing to give the user visual feedback during the 3s auto-advance window.
- **Replay ID Shortening:** In the `CyclePickerScreen`, the `short_id` is derived via `str(c["cycle_id"])[:8]`. Ensure that the `Cycle` node actually stores UUID strings; if they are stored as raw UUID objects, the cast to string is mandatory before slicing.
- **Neo4j Index Verification:** Consider adding an explicit `EXPLAIN` log in debug mode for the first `read_full_cycle_signals` call to verify that the `NodeIndexSeek` is actually occurring in the user's environment.

## Risk Assessment: LOW
The risk level is **LOW**. The plans follow the established architectural patterns of the project. The "Pitfalls" section in the research document demonstrates a deep understanding of potential failure modes (timer leaks, race conditions), all of which are addressed in Plan 02. The separation of `ReplayStore` from `StateStore` is the single most important safety guard implemented here.

---

## Codex Review

## Summary

The phase is decomposed in the right order: Plan 01 establishes replay data contracts, Plan 02 wires CLI/TUI behavior, and Plan 03 handles manual visual verification. The main risks are not architectural; they are contract mismatches and integration details. As written, the plans are likely to produce a partially working replay mode, but I would not consider them ready to execute without tightening the data contract, TUI polling behavior, default cycle selection, and performance verification.

### Plan 01: Data Layer And Wave 0 Tests

**Strengths**
- Good separation between `ReplayStore` and `StateStore`; this correctly avoids corrupting live state and avoids the destructive rationale queue drain.
- Adding `SimulationPhase.REPLAY` is the right choice. It fits existing phase-gate patterns better than an ad hoc flag.
- New per-round graph methods avoid modifying existing report methods that likely assume Round 3.
- Cypher uses parameters for `cycle_id`, `round_num`, and `limit`, which addresses the injection threat model.

**Concerns**
- **HIGH:** Signal casing is inconsistent. Tests use `"buy"`, `"sell"`, `"hold"` and `SignalType(signal_str)`, but bracket Cypher checks `d.signal = 'BUY'`, `'SELL'`, `'HOLD'`. One of these is wrong. This can silently produce all-zero bracket counts.
- **HIGH:** `read_full_cycle_signals()` claims to return signal/confidence/sentiment, but the planned return type is `dict[tuple[str, int], AgentState]`, and `AgentState` only contains `signal` and `confidence` in the provided interface. Sentiment is read then dropped.
- **MEDIUM:** The query starts with `MATCH (a:Agent)-[:MADE]->(d:Decision {cycle_id: $cycle_id})`. For the performance goal, prefer starting from `Decision` to encourage index usage: `MATCH (d:Decision {cycle_id: $cycle_id})<-[:MADE]-(a:Agent)`.
- **MEDIUM:** The CLI tests are not testing the actual CLI. They build a standalone `argparse.ArgumentParser`, so they can pass even if `alphaswarm replay` is never wired into `cli.py`.
- **MEDIUM:** `test_agent_cell_disabled_during_replay` only asserts `SimulationPhase.REPLAY != SimulationPhase.COMPLETE`; it does not test `AgentCell.on_click` behavior.
- **LOW:** Plan 01 modifies `src/alphaswarm/tui.py` for `_PHASE_LABELS`, but `tui.py` is missing from `files_modified`.

**Suggestions**
- Clarify the replay signal state contract: either add a replay-specific dataclass with `signal`, `confidence`, and `sentiment`, or explicitly state that sentiment is only used by bracket summaries and not returned in `read_full_cycle_signals()`.
- Normalize signal handling in one place, and use `SignalType.BUY.value`/equivalent in Cypher expectations and tests.
- Strengthen graph tests to assert `session.execute_read` is called with the intended transaction function and parameters.
- Replace fake CLI parser tests with tests against the real parser if a parser factory exists; otherwise add a small parser factory as part of the CLI work.
- Replace the enum inequality test with a real `AgentCell` click-gate test or move that coverage to Plan 02.

**Risk Assessment: MEDIUM-HIGH** — The shape is good, but the signal/sentiment contract mismatch and weak tests could let a broken replay data layer pass.

### Plan 02: CLI And TUI Wiring

**Strengths**
- Correctly avoids Ollama by using `create_app_state(..., with_ollama=False, with_neo4j=True)`.
- Reuses `AlphaSwarmApp`, existing grid rendering, and Textual `Timer`, which keeps the implementation aligned with the current architecture.
- Uses `ReplayStore` as a separate data source instead of writing replay data into `StateStore`.
- Adds sensible controls: `r`, `p`, `space/right`, and `escape`.

**Concerns**
- **HIGH:** `ReplayStore.snapshot()` returns the same `rationale_entries` every poll. If existing `_poll_snapshot` adds rationale entries from every snapshot, the sidebar will duplicate entries every 200ms. The plan says "no drain," which is correct, but Plan 02 must also change replay polling/sidebar update semantics.
- **HIGH:** CLI replay has no completed live `StateStore` to restore. After `Esc`, `_replay_store = None` means `_poll_snapshot` will likely show `IDLE`, not `COMPLETE`. That conflicts with "Escape exits replay and restores COMPLETE state."
- **HIGH:** `alphaswarm replay` defaults via `read_latest_cycle_id()`, which can select an incomplete or failed cycle. Since Plan 01 adds `read_completed_cycles()`, default replay should use the most recent completed cycle instead.
- **MEDIUM:** Per-round bracket/rationale loads can race. A slow Round 1 load could finish after Round 2 begins and overwrite Round 2 data. `_load_replay_round_data()` should check that the requested round is still current before mutating `ReplayStore`.
- **MEDIUM:** Plan 02 is a large interactive change with almost no new automated tests. Existing Plan 01 tests do not cover `_handle_replay`, replay exit, timer state, picker behavior, footer/header rendering, or disabled controls.
- **MEDIUM:** D-11 says shock injection controls must be disabled during replay, but the plan only covers agent clicks and save. Any `action_open_shock_window` or shock key binding needs an explicit replay gate.
- **MEDIUM:** Manual mode may not mark replay `[DONE]` when advancing to Round 3 unless the user advances again. Define whether Round 3 immediately means done in manual mode.
- **LOW:** `_handle_replay` should close the graph manager after `tui_app.run()` exits, ideally in a `finally`.
- **LOW:** The plan uses private fields like `_cycle_id` and `_entries`; acceptable if consistent locally, but it increases brittleness.

**Suggestions**
- In replay mode, update the rationale sidebar only on round changes, or add a `replace_entries()` style method instead of feeding persistent entries through the live queue-style path.
- Use `read_completed_cycles(limit=1)` for CLI defaulting, or add `read_latest_completed_cycle_id()`.
- Track replay entry source: CLI replay can quit on `Esc`, while in-app replay can restore the previous `COMPLETE` dashboard.
- Add stale-load guards: before applying bracket/rationale rows, verify `self._replay_store is not None` and `round_num == self._replay_round`.
- Add focused tests for `_handle_replay` with `with_ollama=False`, `CyclePickerScreen` option selection, replay footer/header methods, and replay action state transitions.
- Gate all shock/run/seed actions explicitly when `_replay_store is not None`.

**Risk Assessment: HIGH** — The plan is directionally right, but TUI replay has race and polling issues that can produce visibly incorrect behavior even if the code imports and tests pass.

### Plan 03: Human Verification

**Strengths**
- Correctly recognizes that visual distinction, key handling, and timing need an interactive pass.
- The manual scenarios cover the major user workflows: CLI entry, auto-advance, manual mode, exit, disabled interactions, and cycle picker.
- Running the full test suite before manual verification is appropriate.

**Concerns**
- **HIGH:** The `<2s` Cypher performance success criterion is not actually verified. "Observable from load time in logs" is too weak. This needs a measured query duration or a `PROFILE`/integration check against a populated graph.
- **MEDIUM:** CLI replay and in-app replay exit expectations are conflated. CLI replay cannot "restore final simulation state" unless the app intentionally synthesizes one or quits.
- **MEDIUM:** The prerequisite "run a quick simulation first" may be slow and depends on Ollama/model availability, even though replay itself should not.
- **LOW:** `files_modified: []` conflicts with the instruction to create `28-03-SUMMARY.md`.

**Suggestions**
- Add a concrete performance step: log `read_full_cycle_signals()` elapsed time with `time.perf_counter()`, or provide a Cypher `PROFILE` command and require the measured duration to be recorded.
- Split manual exit checks into "CLI replay exit" and "post-simulation TUI replay exit."
- Require the summary file to capture cycle id, node count, measured query time, and pass/fail notes for each manual scenario.

**Risk Assessment: MEDIUM** — The manual flow is useful, but it does not prove the performance criterion and needs clearer expectations for CLI replay.

### Overall Risk Assessment: HIGH (until revised)
Success criteria can appear satisfied while important behavior is broken: bracket counts may be wrong due to signal casing, sentiment may be dropped despite the contract, rationale entries may duplicate during polling, CLI replay may select an incomplete cycle, and query performance is not measured. With those issues fixed, the architecture itself is sound and the phase should be achievable without major redesign.

---

## Consensus Summary

### Agreed Strengths
*(Mentioned by both reviewers)*

- **ReplayStore/StateStore separation** — Both reviewers independently identified this as the strongest architectural decision: prevents destructive queue-drain and state corruption.
- **Zero-inference mode** — `with_ollama=False` in `_handle_replay` correctly decouples replay from LLM availability.
- **Flat-row Cypher design** — Using flat rows instead of COLLECT aggregations to maximize index utilization for the `<2s` performance target.
- **Wave ordering** — Sequential waves (data types → CLI/TUI → human verification) are the right decomposition.
- **`SimulationPhase.REPLAY` enum** — Better than an ad hoc flag; fits existing gate patterns.

### Agreed Concerns
*(Raised by 2+ reviewers — highest priority)*

| # | Concern | Severity | Reviewers |
|---|---------|----------|-----------|
| 1 | Signal casing inconsistency — tests use lowercase `"buy"/"sell"/"hold"` but Cypher compares uppercase `'BUY'/'SELL'/'HOLD'`; silently produces zero bracket counts | HIGH | Codex |
| 2 | Rationale sidebar duplication — `_poll_snapshot` will duplicate entries every 200ms because `ReplayStore.snapshot()` returns the same `rationale_entries` on every poll (no drain) | HIGH | Codex |
| 3 | CLI replay restores wrong state — after `Esc`, no prior `StateStore` exists when launched via CLI, so `COMPLETE` restore is impossible without explicit handling | HIGH | Codex |
| 4 | Default cycle selection selects incomplete cycles — `read_latest_cycle_id()` can return incomplete/failed cycles; should use `read_completed_cycles(limit=1)` | HIGH | Codex |
| 5 | Performance criterion not actually verified — Plan 03 relies on "observable from logs" which is too weak for the `<2s` success criterion | HIGH | Codex; Gemini (implicit) |
| 6 | Neo4j DateTime handling in CyclePickerScreen — UTC vs local time ambiguity in `.to_native()` | MEDIUM | Both |

### Divergent Views
*(Where reviewers disagreed)*

- **Overall risk level**: Gemini assessed **LOW** risk (well-structured plans following established patterns); Codex assessed **HIGH** risk (data contract mismatches and polling race conditions can produce visibly wrong behavior that passes tests). The divergence is driven by Codex examining the signal/sentiment contract and polling semantics in more detail. **Recommendation: treat as HIGH until the 4 HIGH concerns are resolved in a replanning pass.**
- **`ReplayStore.snapshot()` efficiency**: Gemini flagged the 300-item iteration as a LOW concern; Codex raised the duplication issue as HIGH (different root causes — efficiency vs. correctness).

---

*Review complete. To incorporate feedback: `/gsd-plan-phase 28 --reviews`*
