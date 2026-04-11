---
phase: 26
reviewers: [gemini, codex]
reviewed_at: 2026-04-10T00:00:00Z
plans_reviewed: [26-01-PLAN.md, 26-02-PLAN.md, 26-03-PLAN.md, 26-04-PLAN.md, 26-05-PLAN.md]
---

# Cross-AI Plan Review — Phase 26

## Gemini Review

# Phase 26: Shock Injection Core - Plan Review

The implementation plans for Phase 26 are exceptionally well-structured, adhering to a rigorous TDD lifecycle and demonstrating a deep understanding of the existing codebase's architectural nuances, particularly the complex ResourceGovernor state machine and the Textual TUI event loop.

## 1. Summary
The 5-plan sequence for Phase 26 establishes a robust foundation for interactive simulation by introducing a "side-channel" for user input that bypasses the resource-governance state machine without compromising system integrity. The transition from Wave 0 test scaffolding to surgical implementation across the governor, state, graph, TUI, and simulation layers is logical and minimizes the risk of regression in the critical governor monitoring loop.

## 2. Strengths
*   **Surgical Governor Intervention:** The decision to manipulate `_resume_event` directly via `suspend()` and `resume()` (Plan 02) rather than calling `stop_monitoring()` is a direct and correct response to historical deadlock bugs. It preserves the memory-pressure monitoring state throughout the user interaction window.
*   **Rising-Edge Latch in TUI:** Plan 04 correctly identifies and mitigates the risk of "modal stacking" in the 200ms `_poll_snapshot` loop by implementing a boolean latch (`_shock_window_was_open`).
*   **Safe Sync-to-Async Bridge:** Using `self.run_worker()` for `submit_shock` in the TUI (Plan 04) correctly handles the transition from synchronous Textual callbacks to asynchronous Queue operations, preventing event loop stalls.
*   **Immutability of Base State:** Plan 05 uses round-local `effective_message` variables, ensuring the base `rumor` remains uncontaminated for downstream analysis and replay features.
*   **Graceful Degradation:** The integration in Plan 05 correctly treats Neo4j write failures as non-blocking, ensuring a failed log entry doesn't halt the entire simulation round.

## 3. Concerns
*   **Governor State Precondition (LOW):** Plan 02/05 relies on a "soft" precondition check (`governor.state == RUNNING`). While inter-round gaps should logically have zero active agents, if a persistent memory pressure event (CRISIS/PAUSED) is active when the round ends, the shock window will be skipped. This is technically correct for safety but might confuse a user who expected an input prompt.
*   **Neo4jWriteError Signature (LOW):** Plan 03 notes the need to verify if `Neo4jWriteError` accepts `original_error=`. If the existing exception class lacks this kwarg, the implementation might fail.
*   **TaskGroup Cancellation (MEDIUM):** If the simulation task is cancelled while `await_shock()` is blocking, the `finally` block in `run_simulation` (Plan 05) will trigger `governor.resume()`. This is good, but the plan should ensure `close_shock_window()` is also called in the `finally` block to prevent the TUI from being stuck in a "window open" state on the next run. Currently, it is inside the `try` block.

## 4. Suggestions
*   **TUI Consistency:** In `ShockInputScreen` (Plan 04), ensure the `Input` widget has `select_on_focus=True` (if supported by the project's Textual version) to make clearing placeholder text easier for the user.
*   **State Cleanup:** Move `await state_store.close_shock_window()` inside the `finally` block in `run_simulation` (Plan 05) to ensure the TUI edge-latch is reset even if a write or await operation is cancelled.
*   **Logging Detail:** In the governor `suspend`/`resume` methods, include the `cycle_id` in the log context if accessible, to improve traceability in multi-simulation logs.

## 5. Risk Assessment: LOW
The risk is low because:
1.  **Strict Isolation:** The new methods are additive and do not modify the core logic of the ResourceGovernor or the Ollama client.
2.  **TDD Foundation:** Plan 01 ensures 100% test coverage for the new feature before implementation begins.
3.  **Proven Patterns:** Every new primitive (Queue bridge, Modal screen, parameterized Cypher) is a clone of a pattern already working in the codebase.
4.  **Hardware Awareness:** The approach respects the M1 Max memory constraints by pausing inference during the user authoring phase.

The plans are ready for execution.

---

## Codex Review

## Overall Assessment

The phase is well decomposed and mostly achieves the Phase 26 goals: governor primitive, state/graph data plane, TUI input, and simulation orchestration are split cleanly. The main risks are not in the feature concept, but in a few cross-plan mismatches: Plan 05 claims full-suite completion without depending on Plan 04, the real `StateStore` end-to-end test deadlocks with a `maxsize=1` queue, and the governor resume semantics may briefly override real memory-pressure pauses. I would tighten those before execution.

## 26-01 Plan Review

**Summary**
Good RED-state scaffolding plan with clear test names and collection checks, but it is slightly inconsistent about test count and the stubs are weaker than true failing behavioral tests.

**Strengths**
- Establishes named pytest nodes before implementation, which supports later validation.
- Centralizes `mock_state_store` instead of duplicating fixtures.
- Keeps production code untouched.
- Uses loud `pytest.fail(...)` markers rather than silent `pass`.

**Concerns**
- **MEDIUM:** Objective says "21 failing stubs," while the plan actually defines 19.
- **MEDIUM:** Stubs do not import the expected future APIs, so collection will not catch missing symbols.
- **LOW:** Some validation commands use brittle `grep | wc` checks that can pass/fail for formatting reasons.
- **LOW:** `grep -c "SHOCK-01\|SHOCK-02\|SHOCK-03"` in validation does not reliably equal test count.

**Suggestions**
- Fix the count to 19 everywhere, or add the missing two tests if 21 is intended.
- Add lightweight imports in stubs where safe, or explicitly state that API presence is validated in later plans.
- Replace the requirement grep count with a direct expected-test-name checklist.

**Risk Assessment: LOW-MEDIUM**
Low implementation risk because it only touches tests, but the count mismatch and weak RED signal can confuse downstream phase validation.

## 26-02 Plan Review

**Summary**
The governor plan is intentionally surgical and follows the stated design decision, but the interaction between manual `resume()` and the memory-pressure state machine needs stronger protection and tests.

**Strengths**
- Minimal API: synchronous `suspend()` and `resume()` around an existing event gate.
- Explicitly avoids stop/start monitoring, which addresses the known deadlock history.
- Tests target observable acquire blocking/unblocking, not just method presence.
- Preserves async behavior by blocking only `acquire()` waiters.

**Concerns**
- **HIGH:** `resume()` blindly setting `_resume_event` can release agents even if the monitor moved to PAUSED/CRISIS during the shock window.
- **HIGH:** The monitor-loop test only checks that the task stays alive; it does not prove that `acquire()` remains blocked while the monitor is running.
- **MEDIUM:** Plan relies on a caller precondition, but the callee has no guard and future callers could violate it.
- **LOW:** Tests do not directly assert `_pool` and `_monitor_task` identity are unchanged.

**Suggestions**
- Add a test where monitoring is active under GREEN pressure, `suspend()` is called, and `acquire()` remains blocked across at least one monitor tick.
- Decide explicitly whether `resume()` should respect current governor state, for example by only setting the event if state is RUNNING, or by introducing a separate manual pause event that `acquire()` also awaits.
- Prefer a public `state` property in later caller checks if it exists, rather than direct `_state` access.
- Assert `_pool is same_object` and `_monitor_task is same_object` around suspend/resume.

**Risk Assessment: MEDIUM-HIGH**
The code change is small, but it sits directly on the memory-safety gate. A subtle resume race would violate a hard project constraint.

## 26-03 Plan Review

**Summary**
The StateStore and Neo4j primitives are the right foundation, but the queue lifecycle and graph write verification need tightening to avoid deadlocks and silent persistence failures.

**Strengths**
- Single-slot queue matches the "one shock per inter-round window" model.
- Event plus `next_round` gives the TUI a clean polling interface.
- Graph write uses parameterized Cypher, which handles shock text safely.
- Requirements traceability is a useful addition.

**Concerns**
- **HIGH:** A stale queue item after cancellation could leak into the next shock window unless cleanup is guaranteed elsewhere.
- **MEDIUM:** `MATCH (c:Cycle ...) CREATE ...` can silently do nothing if the cycle is missing, while `write_shock_event()` still returns a UUID.
- **MEDIUM:** The graph test as written mostly verifies `execute_write` arguments; it does not inspect the Cypher emitted by `_write_shock_event_tx`.
- **MEDIUM:** `submit_shock()` accepts arbitrarily large strings; given the M1 memory constraint and prompt injection into 100 agents, a length cap should be considered.
- **LOW:** Plan text says "5 accessor methods" but defines 6 methods.

**Suggestions**
- Ensure `close_shock_window()` or `request_shock()` drains stale queue contents, or guarantee cleanup in the simulation `finally`.
- Test `_write_shock_event_tx` directly with a mocked transaction and assert the Cypher contains `ShockEvent` and `HAS_SHOCK`.
- Consider verifying write counters or using a Cypher pattern that fails/logs if no `Cycle` matched.
- Add a basic shock text length/trim policy, even if conservative.

**Risk Assessment: MEDIUM**
The API shape is good, but queue cleanup and silent Neo4j no-op behavior are real operational risks.

## 26-04 Plan Review

**Summary**
The TUI plan is well-scoped and follows the existing modal pattern, but `_poll_snapshot` integration should be isolated or tested carefully because direct calls against an unmounted app are likely brittle.

**Strengths**
- Mirrors the existing input screen pattern, keeping UI consistency.
- Rising-edge latch directly addresses modal stacking.
- Uses `run_worker` for sync-to-async callback bridging.
- Covers Enter and Escape behavior.

**Concerns**
- **MEDIUM:** Proposed `_poll_snapshot` tests may fail because the method likely touches mounted widgets before reaching the shock block.
- **MEDIUM:** Existing app-state mocks may not have `is_shock_window_open()` and `shock_next_round()`, causing unrelated TUI tests to regress.
- **MEDIUM:** Empty Enter is part of behavior but lacks a dedicated test.
- **LOW:** `pilot.press(*"Fed emergency rate cut")` may not match the project's existing Textual input helper pattern, especially around spaces.

**Suggestions**
- Extract a small `_check_shock_window()` helper called by `_poll_snapshot()` and test that directly.
- Update shared TUI fixtures/mocks to include the new StateStore methods.
- Add `test_shock_input_screen_empty_enter_dismisses_with_none`.
- Use the same Pilot typing helper already present in the test suite.

**Risk Assessment: MEDIUM**
Feature risk is moderate mainly because Textual test harnesses are sensitive to mounted app state and event-loop behavior.

## 26-05 Plan Review

**Summary**
This plan wires the feature into the critical simulation path, but it has the most serious cross-plan and lifecycle risks. The intended behavior is right; the execution plan needs dependency and cleanup fixes before implementation.

**Strengths**
- Places shock injection at the correct R1→R2 and R2→R3 gaps.
- Keeps `rumor` immutable by introducing `effective_message_r2/r3`.
- Guards the non-TUI path with `state_store is not None`.
- Persists shock events before the shocked round starts.
- Catches Neo4j write failures and continues simulation, which is pragmatic.

**Concerns**
- **HIGH:** Plan 05 claims all 19 tests/full suite green but does not depend on Plan 04. If Wave 2 runs in parallel, TUI stubs may still fail.
- **HIGH:** The proposed end-to-end test deadlocks: `StateStore` queue has `maxsize=1`, so pre-submitting two shocks before simulation consumes the first will block forever.
- **HIGH:** `close_shock_window()` is not in a `finally`; cancellation or errors during `await_shock()` can leave the TUI window/latch stuck open.
- **HIGH:** `governor.resume()` may release `_resume_event` even if memory pressure changed the governor to PAUSED/CRISIS during the shock wait.
- **MEDIUM:** The plan duplicates two large shock blocks; this increases the chance of R2/R3 drift.
- **MEDIUM:** The tests prove `dispatch_wave` receives the message, but not that all 100 personas are present in the dispatched batch.
- **LOW:** Direct `governor._state` access is brittle; use a public state accessor if available.

**Suggestions**
- Either add Plan 04 as a dependency for Plan 05, or remove "full suite/all 19 tests green" from Plan 05 and make it final phase verification after both Wave 2 plans finish.
- Fix the end-to-end test by using a mock `await_shock.side_effect`, or schedule the second `submit_shock(None)` only after the first queue item is consumed.
- Wrap shock lifecycle as: suspend, request, `try await_shock`, `finally close_shock_window`, outer `finally resume`.
- Consider a private helper like `_collect_inter_round_shock(next_round=...)` to centralize suspend/request/await/close/persist/resume.
- Assert the `personas` argument length in the shock propagation test, ideally with 100 personas or a clearly documented smaller test fixture plus a dispatcher contract test.

**Risk Assessment: HIGH**
This plan touches the simulation critical path and currently has a hard deadlock in the proposed test plus incomplete cleanup on cancellation. Fixing those makes the overall phase much safer.

---

## Consensus Summary

### Agreed Strengths
(Mentioned by both reviewers)

- **Surgical `_resume_event` approach** — Both reviewers validated that manipulating only the event gate (not calling `stop_monitoring`) is the correct and safe approach given the prior deadlock history.
- **Immutability of base `rumor`** — Both noted the `effective_message_r2/r3` pattern correctly prevents rumor contamination across rounds and downstream features.
- **Rising-edge latch for `_poll_snapshot`** — Both recognized the boolean latch prevents modal stacking in the 200ms polling loop.
- **`run_worker` for sync-to-async bridging** — Both confirmed this correctly prevents event loop stalls in the TUI dismiss callback.

### Agreed Concerns
(Issues raised by 2+ reviewers — highest priority for replanning)

| Concern | Gemini | Codex | Severity | Action Required |
|---------|--------|-------|----------|-----------------|
| `close_shock_window()` must be in `finally`, not `try` | MEDIUM | HIGH | **HIGH** | Move cleanup into `finally` in Plan 05 so cancellation/errors don't leave TUI stuck |
| `resume()` may release agents if governor moved to PAUSED/CRISIS during shock wait | LOW | HIGH | **MEDIUM-HIGH** | Decide: should `resume()` check governor state before setting event, or introduce a separate manual-pause event |

### Divergent Views
(Where reviewers disagreed — worth investigating)

- **Overall risk:** Gemini rates the phase LOW risk overall; Codex rates Plan 05 HIGH risk due to the end-to-end test deadlock and missing dependency link. **Codex's specific concerns about Plan 05 are concrete and actionable** — the deadlock scenario is well-described and the dependency gap is verifiable.
- **Plan 02 monitor-loop test sufficiency:** Gemini does not flag this; Codex rates it HIGH and suggests proving `acquire()` stays blocked across a monitor tick, not just that the task stays alive.
- **Stub import completeness (Plan 01):** Gemini doesn't raise this; Codex flags that stubs without future API imports won't catch symbol-missing errors at collection time.

### Top 3 Actionable Items for --reviews Replanning

1. **Plan 05: Move `close_shock_window()` into `finally` block** — Both reviewers identified this. Cancellation safety is a hard requirement on the simulation critical path.
2. **Plan 05: Fix end-to-end test deadlock** — Codex-specific but HIGH risk. Use `mock await_shock.side_effect` pattern or schedule second `submit_shock` only after first queue item consumed.
3. **Plan 02: Clarify `resume()` semantics** — If governor moved to PAUSED/CRISIS during shock wait, should `resume()` respect that? Add a test that proves behavior under concurrent memory pressure. Both reviewers flagged this with different severity; a concrete decision prevents a subtle race condition.
