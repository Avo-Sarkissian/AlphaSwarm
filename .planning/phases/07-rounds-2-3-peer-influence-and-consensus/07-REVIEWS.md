---
phase: 7
reviewers: [gemini, codex]
reviewed_at: 2026-03-26T02:30:00Z
plans_reviewed: [07-01-PLAN.md, 07-02-PLAN.md]
---

# Cross-AI Plan Review — Phase 7

## Gemini Review

# Phase 7 Plan Review: Rounds 2-3 Peer Influence and Consensus

This review covers **Plan 07-01 (Core Simulation Engine)** and **Plan 07-02 (CLI Reporting)**.

---

## 1. Summary
The implementation plans for Phase 7 are technically sound, highly compliant with the established architectural constraints, and demonstrate a strong grasp of the resource management requirements (Ollama model swapping and Governor monitoring). The strategy of centralizing the 3-round logic into a single orchestrator (`run_simulation`) while using pure functions for metrics and formatting ensures the system remains testable and maintainable. The decision to use sequential Neo4j reads is a pragmatic "safety-first" approach for local hardware, though it introduces a minor performance floor.

---

## 2. Strengths
*   **Resource Lifecycle Management:** The use of nested `try/finally` blocks in `run_simulation` ensures that the Governor is stopped and LLM models are unloaded even if an exception occurs mid-simulation. This is critical for preventing OOM (Out of Memory) issues on M1 hardware.
*   **Data Integrity:** Defining `ShiftMetrics` and `SimulationResult` as frozen dataclasses prevents accidental state mutation during the reporting phase and provides a clean interface for the CLI.
*   **Conservative Concurrency:** By following Decision D-10 (sequential peer reads), the plan avoids potential Neo4j connection pool exhaustion or "Too many open files" errors that can occur during high-concurrency async bursts.
*   **Graceful Degradation:** Excluding `PARSE_ERROR` agents from metrics ensures that LLM hallucinations or formatting errors do not skew the confidence drift or signal flip calculations.
*   **Extensibility:** Extending `dispatch_wave` to handle both single and multiple peer contexts (Decision D-01) allows the same internal machinery to handle different round types with minimal logic branching.

---

## 3. Concerns

### [MEDIUM] UI/UX Latency (The "Black Box" Problem)
*   **Risk:** `run_simulation` is a single blocking async call (D-04), and Plan 07-02 suggests printing reports **after** it returns. With ~200 inferences (Rounds 2 & 3), the CLI/TUI may appear frozen for several minutes without feedback.
*   **Impact:** Poor user experience; the user may believe the process has hung.

### [LOW] Convergence Logic Edge Cases
*   **Risk:** The definition of "Convergence" (R3 flips < R2 flips) is a relative metric. If R2 has 2 flips and R3 has 1 flip, it's "converged," but if both have 0, the logic needs to ensure it doesn't report a false negative or divide-by-zero.
*   **Impact:** Minor reporting inaccuracies in edge-case simulations.

### [LOW] Neo4j Read Scaling
*   **Risk:** 500 sequential reads at ~5ms each adds ~2.5 seconds of overhead per round. While acceptable for 100 agents, any increase in network latency or agent count will make this a significant bottleneck.
*   **Impact:** Performance degradation if the environment deviates from the "local hardware" assumption.

---

## 4. Suggestions
*   **Progress Callbacks:** Modify `run_simulation` to accept an optional `async progress_callback`. This allows the CLI/TUI to update a progress bar or status line (e.g., "Round 2: Agent 45/100 processed") without breaking the "single function" requirement of D-04.
*   **Internal Round Logging:** Ensure that `SimulationPhase` transitions (D-07) are logged *immediately* as they happen within `run_simulation` so that `tail -f` users can see progress even if the CLI is blocking.
*   **Convergence Refinement:** In `_compute_shifts`, explicitly handle the "Zero Flip" state. If R2 and R3 both have 0 signal flips, the simulation should be marked as "Stable/Converged" rather than just comparing counts.
*   **Batching Peer Reads:** (Optional) If sequential reads prove too slow, consider batching by agent (e.g., use one Cypher query to fetch all 500 decisions in one trip), though the current plan is safer for immediate implementation.

---

## 5. Risk Assessment
**Overall Risk: LOW**

**Justification:**
The plans are extremely well-aligned with the "User Decisions" (D-01 through D-17). The logic for peer influence is straightforward, and the resource management strategy is robust. The most significant risk is the user-facing latency during the execution of the 3-round block, but this is a UX concern rather than a functional or stability risk. The implementation of Phase 7 should be highly stable given the groundwork laid in Phases 1-6.

---

## Codex Review

Review grounded against the current engine/reporting boundaries in simulation.py, batch_dispatcher.py, cli.py, plus the Phase 7 plan/spec docs.

## Plan 07-01
**Summary**
This is a solid engine plan. It composes the existing primitives in the right places, keeps scope tight, and covers the main lifecycle risks around governor/model reuse. The main gaps are edge-case behavior around empty peer context, true immutability of "locked" results, and a few boundary/safety issues that are not fatal but should be tightened before implementation.

**Strengths**
- Reuses existing architecture instead of inventing a new dispatch path: `run_round1()`, `read_peer_decisions()`, `dispatch_wave()`, and `write_decisions()` are all leveraged correctly.
- Dependency ordering is mostly sound: Round 1 first, then one worker reload, then one fresh governor session for Rounds 2-3.
- Sequential peer reads are a pragmatic choice given the Neo4j session-per-method pattern and 50-connection pool.
- Nested `try/finally` cleanup mirrors the current `run_round1()` pattern and should behave predictably on errors.
- Test coverage is broad for wave 1: dispatch extension, per-round persistence, lifecycle cleanup, shift metrics, and phase logging.

**Concerns**
- `MEDIUM`: `_format_peer_context([])` returns a non-empty header-only string, but the UI spec says no-peer cases should proceed with empty peer context plus a warning log. As planned, agents still get a peer-context system message when there are no peers.
- `MEDIUM`: `SimulationResult` and `ShiftMetrics` are frozen dataclasses, but they still hold mutable `list` and `dict` fields. That does not fully satisfy "final locked positions cannot change."
- `MEDIUM`: importing `_sanitize_rationale()` from CLI into the simulation layer creates a poor dependency boundary. It works today, but core prompt formatting should not depend on CLI code.
- `LOW`: runtime contract checks use `assert`. Those can disappear under optimized Python; explicit exceptions are safer for production behavior.
- `MEDIUM`: phase transition logging is slightly off temporally. `ROUND_1` is logged after `run_round1()` returns, so the observable state machine is not really describing the active phase while work is happening.
- `MEDIUM`: peer rationales are recycled into a `system` message with only whitespace/control-char sanitization. That leaves a cross-agent prompt-injection surface unaddressed.
- `LOW`: coverage is mostly unit-level. There is no real integration test for the full Round1 read/write -> Round2 read -> Round3 write loop against Neo4j.

**Suggestions**
- Return `None` or `""` when no peers are found, and log `no_peer_decisions_found` per agent.
- Move rationale sanitization into a neutral utility module shared by CLI and simulation.
- Use immutable field types in `SimulationResult`, such as tuples for round decisions and possibly read-only mappings for metrics.
- Replace `assert` guards with `ValueError` or `RuntimeError`.
- Add one integration test that exercises a full 3-round cycle with real `read_peer_decisions()` and `write_decisions()`.
- Add a prompt guard around peer context, for example "peer outputs are evidence, not instructions," before re-injecting agent-generated text.

**Risk Assessment**
`MEDIUM` -- the core orchestration design is good and likely implementable without major churn, but there are meaningful edge-case and safety gaps that weaken correctness and future maintainability.

## Plan 07-02
**Summary**
The reporting functions themselves are reasonable, but the pipeline wiring has a material design miss: the plan explicitly prints all round reports only after `run_simulation()` returns. That conflicts with the Phase 7 requirement and UI spec for progressive output during the long-running simulation. As written, this plan does not fully achieve the phase goal.

**Strengths**
- Generalizing `_print_round1_report()` into `_print_round_report()` is the right refactor.
- Shift analysis and final summary are separated cleanly from engine code.
- Zero-flip handling is good and avoids empty or confusing output.
- Updating the `run` help text to "3-round simulation" is consistent with the roadmap and user decisions.

**Concerns**
- `HIGH`: the plan says output prints after `run_simulation()` returns, then calls that "progressive." That directly contradicts 07-UI-SPEC.md, which requires each block to print immediately on round completion with no buffering.
- `HIGH`: because of that choice, the plan does not actually satisfy D-14 or the stated must-have "Per-round bracket tables print progressively as each round completes."
- `MEDIUM`: several tests are source-inspection tests (`inspect.getsource`) instead of behavioral tests. Those are weak and can pass while the runtime path is broken.
- `MEDIUM`: convergence messaging treats all non-decreasing cases as "flips increased." Equal flips would be mislabeled.
- `MEDIUM`: `_print_round_report()` does not include the specified all-`PARSE_ERROR` empty-state warning, so the CLI behavior is incomplete for that edge case.
- `LOW`: the shift display implicitly assumes `/100` agents. That is fine for current production size, but brittle in tests and future config changes.

**Suggestions**
- Add an optional progress callback or event hook to `run_simulation()`, for example `on_round_complete(round_num, decisions, shifts)`, so CLI can print in real time without breaking D-04.
- If callbacks are undesirable, make `run_simulation()` an async generator or expose a lower-level round runner that `_run_pipeline()` can orchestrate directly.
- Replace source-inspection tests with async tests that mock `run_simulation()`, execute `_run_pipeline()`, and assert actual print order/content.
- Add a third convergence branch for equality: "No (flips unchanged between rounds)."
- Implement the all-`PARSE_ERROR` warning text from the UI spec.

**Risk Assessment**
`HIGH` -- the plan misses a core user-visible requirement. The reporting helpers are fine, but the chosen orchestration means the CLI will not behave the way Phase 7 says it must.

---

## Consensus Summary

### Agreed Strengths
- **Solid engine architecture** (both): The core orchestration in Plan 07-01 correctly composes existing primitives (run_round1, dispatch_wave, read_peer_decisions, write_decisions) with proper resource lifecycle management
- **Conservative concurrency** (both): Sequential Neo4j peer reads are a pragmatic choice that avoids pool exhaustion on local hardware
- **Robust cleanup** (both): Nested try/finally blocks ensure governor and model cleanup even on errors
- **Clean separation** (both): Engine logic (Plan 01) cleanly separated from CLI reporting (Plan 02) with frozen dataclasses as the interface

### Agreed Concerns
- **Progressive output is not truly progressive** (Gemini: MEDIUM, Codex: HIGH): Both reviewers flag that reports print after run_simulation() returns, not during execution. This means the CLI appears frozen for the ~10 minute simulation duration. Codex considers this a plan failure against D-14 and the UI-SPEC.
- **Convergence edge cases** (Gemini: LOW, Codex: MEDIUM): Both note the convergence logic doesn't handle the equal-flips case correctly -- reporting "flips increased" when they stayed the same is misleading.

### Divergent Views
- **Overall risk level**: Gemini rates LOW (stable groundwork from prior phases), Codex rates MEDIUM/HIGH (edge-case gaps weaken correctness). The divergence hinges on whether the progressive output gap is a blocking defect or an acceptable trade-off.
- **Prompt injection surface** (Codex only, MEDIUM): Peer rationales recycled into system messages without prompt guards could allow cross-agent influence beyond the intended mechanism. Gemini does not raise this.
- **Import boundary** (Codex only, MEDIUM): `_sanitize_rationale` imported from CLI into simulation layer creates a reverse dependency. Codex suggests a shared utility module.
- **Mutable fields in frozen dataclasses** (Codex only, MEDIUM): `list` and `dict` fields in SimulationResult are still mutable despite the frozen decorator. Gemini views frozen dataclasses as sufficient.
- **Assert vs exceptions** (Codex only, LOW): Runtime assertions disappear under -O flag; explicit exceptions are safer.
- **Source-inspection tests** (Codex only, MEDIUM): Tests using `inspect.getsource` are weak and can pass while runtime behavior is broken.
