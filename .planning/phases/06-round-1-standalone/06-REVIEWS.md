---
phase: 6
reviewers: [gemini, codex]
reviewed_at: 2026-03-26
plans_reviewed: [06-01-PLAN.md]
---

# Cross-AI Plan Review — Phase 6

## Gemini Review

### Summary
The plan for Phase 6 is a highly cohesive and surgically precise implementation that leverages existing infrastructure (Resource Governor, Batch Dispatcher, and Seed Injection) to deliver the first functional simulation milestone. By centralizing the orchestration logic in a new `simulation.py` module and strictly enforcing the model lifecycle (unload orchestrator → load worker → unload worker), the plan effectively mitigates the highest technical risk: memory exhaustion on local hardware. The testing strategy is comprehensive, covering both the logic of the pipeline and the user-facing CLI output, ensuring that "Round 1" is not just functional but also observable and robust.

### Strengths
- **Resource Safety:** The explicit use of a `finally` block for worker model unloading is a critical safety pattern for local LLM inference, preventing "zombie" models from locking up GPU/RAM.
- **Separation of Concerns:** Introducing `simulation.py` as a thin orchestration layer keeps `cli.py` focused on presentation while providing a testable entry point for future rounds (Round 2 and 3).
- **Data Integrity:** The plan specifically addresses `PARSE_ERROR` handling in bracket aggregation, preventing invalid LLM outputs from skewing the reported market signal distribution.
- **UX-Focused CLI:** The decision to truncate rationales at 80 characters and highlight "top movers" by confidence demonstrates a senior approach to CLI design, making the output of 100 agents human-readable.
- **Testing Rigor:** 15+ new tests targeting specific edge cases (e.g., positional alignment of IDs, error state cleanup, and bracket formatting) provide high confidence in the stability of the 238-test baseline.

### Concerns
- **Orchestrator Model Lifecycle (MEDIUM):** While the plan ensures the *worker* model is unloaded in a `finally` block, it relies on `inject_seed()` to handle the orchestrator model. If `inject_seed()` fails or leaves the orchestrator model loaded, the subsequent `load_worker()` call may trigger an OOM event.
- **Seed Injection Validation (LOW):** The plan uses raw rumor text as the user message. If the rumor is empty or excessively long, `inject_seed()` might fail before the worker phase begins.
- **Dependency on Positional Alignment (MEDIUM):** Relying on index-based alignment across async batches can be brittle if the dispatcher filters or reorders results.

### Suggestions
- Explicit model transition check in `run_round1()` before loading worker.
- Robust ID mapping instead of positional alignment.
- Phase failure reporting: warn if a bracket has high failure rate.
- Capture start/end time and report duration.

### Risk Assessment
**LOW** — Plan is well-aligned with constraints, risks are implementation details.

---

## Codex Review

### Summary
This is a good thin-orchestration plan: it reuses the existing seed pipeline, batch dispatcher, and graph persistence instead of inventing a new Round 1 subsystem. That keeps scope tight and aligned with the phase goal. The main problem is that two critical integration responsibilities are missing or underspecified: memory-governor monitoring lifecycle and async-safe app initialization. As written, the plan is close, but not yet complete enough to reliably satisfy the hard constraints.

### Strengths
- Reuses existing async building blocks instead of adding duplicate orchestration paths.
- `peer_context=None` and raw rumor as the user message correctly match Round 1 independence and the current worker contract.
- Worker unload in `finally` is the right safety pattern and matches the existing seed pipeline.
- CLI output scope is useful and bounded: bracket summary, failure counts, and top-confidence rationales are enough for Phase 6.
- The test list focuses on behavioral contracts rather than brittle model-output assertions.

### Concerns
- **HIGH:** The plan never starts or stops governor monitoring. Without `start_monitoring()`, the governor is only a fixed token pool, so the plan does not fully satisfy the RAM-throttling/pause hard constraint.
- **HIGH:** `_handle_run()` "following `_handle_inject()`" inherits an existing async bug. The current inject path creates app state inside an async handler, but `create_app_state(..., with_neo4j=True)` calls `run_until_complete()`, which is unsafe under a running event loop.
- **MEDIUM:** Schema/bootstrap ownership is ambiguous. `inject_seed()` does not call `ensure_schema()`, so the plan should explicitly say whether `_handle_run()` or `run_round1()` guarantees schema and agent seeding before decision writes.
- **MEDIUM:** Mock-only tests are too shallow for the riskiest behavior: event-loop lifecycle, cleanup ordering, and orchestration across async boundaries.
- **MEDIUM:** `Round1Result(cycle_id, parsed_result, agent_decisions, decisions)` looks redundant. Two decision collections create two sources of truth.
- **MEDIUM:** Failure-path cleanup is incomplete. Worker unload is covered, but report suppression, governor stop, and graph close also need explicit guarantees on `write_decisions()` failure, cancellation, or `GovernorCrisisError`.
- **MEDIUM:** Success criterion 3 is only partially demonstrated — plan doesn't validate results are queryable by bracket, signal, and confidence from Neo4j.
- **LOW:** Rationale truncation alone is not enough for CLI safety. Model text should be whitespace-normalized and stripped of control characters before printing.
- **LOW:** Positional pairing between worker configs and dispatcher results is safe today because `dispatch_wave()` returns results in task-creation order, but that is still an implicit contract.

### Suggestions
- Add `await governor.start_monitoring()` before dispatch and `await governor.stop_monitoring()` in the outermost `finally`.
- Fix app initialization before copying the current inject handler pattern.
- Make ownership explicit: CLI handler owns app creation/schema/cleanup; `run_round1()` owns seed→dispatch→persist.
- Simplify `Round1Result` to one canonical result collection.
- Add one higher-level async orchestration test with mocked external services but real function boundaries.
- Add explicit tests for 100 agents dispatched, 100 persisted tuples.
- Sanitize rationale snippets before printing.
- Consider `model_manager.ensure_clean_state()` at run start.

### Risk Assessment
**HIGH** — Overall shape is good and scope is disciplined, but the plan misses one hard-constraint mechanism (governor monitoring) and relies on an async initialization pattern that is already unsafe.

---

## Consensus Summary

### Agreed Strengths
- **Thin orchestration approach** — Both reviewers praise the plan for composing existing, tested building blocks rather than creating new subsystems. Good scope discipline.
- **Worker model finally-block safety** — Both highlight the try/finally pattern for worker model unload as critical and well-handled.
- **PARSE_ERROR filtering** — Both note the plan correctly handles invalid LLM outputs by excluding them from bracket aggregation while counting them in the header.
- **Behavioral test strategy** — Both appreciate that tests target contracts and edge cases rather than brittle output matching.

### Agreed Concerns
- **Positional alignment risk (MEDIUM)** — Both flag that pairing worker_configs with decisions by index position is an implicit contract that could break if dispatch_wave ever reorders or filters results.
- **Orchestrator model lifecycle dependency (MEDIUM)** — Both note the plan relies on inject_seed() to cleanly unload the orchestrator, with no fallback if it doesn't.

### Divergent Views
- **Overall risk assessment** — Gemini rates LOW, Codex rates HIGH. The divergence stems from Codex identifying two systemic issues (governor monitoring lifecycle and async-safe app initialization) that Gemini did not examine at the code level.
- **Governor monitoring lifecycle** — Codex flags as HIGH that the plan never calls `start_monitoring()`/`stop_monitoring()`, meaning RAM throttling won't actually engage. Gemini does not raise this.
- **Async initialization safety** — Codex identifies that `create_app_state()` may call `run_until_complete()` under an existing event loop, which is unsafe. Gemini does not flag this.
- **Round1Result redundancy** — Codex sees `agent_decisions` and `decisions` as two sources of truth; Gemini does not raise this concern.
- **Test depth** — Codex wants at least one integration-level async test; Gemini is satisfied with the unit test coverage.
