---
phase: 40-simulation-context-wiring
plan: 01
subsystem: simulation

tags: [simulation, worker, batch_dispatcher, tdd, market_context, round1]

# Dependency graph
requires:
  - phase: 06-round-1-standalone
    provides: run_round1 pipeline + dispatch_wave scalar plumbing
  - phase: 07-rounds-2-3-peer-influence-and-consensus
    provides: peer_context scalar precedent mirrored by market_context
provides:
  - AgentWorker.infer(market_context=...) with D-04 system-message ordering
  - dispatch_wave(market_context=...) scalar plumbing (D-07 same-for-all-agents)
  - _safe_agent_inference(market_context=...) positional forwarding
  - run_round1(market_context=...) keyword-only forwarding to dispatch_wave
  - Six Wave 0 unit tests covering all three layers of plumbing
affects:
  - 40-02-simulation-context-wiring Plan 02 (ContextPacket assembly + formatter)
  - 40-03-simulation-context-wiring Plan 03 (provider wiring in lifespan / CLI)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Scalar parameter threading mirrors peer_context precedent (worker.py -> batch_dispatcher.py -> simulation.py)"
    - "D-04 system-message ordering: market_context BEFORE peer_context in messages list"
    - "D-07 same-scalar-all-agents contract: one market_context, identical to every agent in the wave"
    - "D-06 scope containment: Round 1 only; _dispatch_round and run_simulation intentionally untouched"

key-files:
  created:
    - .planning/phases/40-simulation-context-wiring/deferred-items.md
    - .planning/phases/40-simulation-context-wiring/40-01-SUMMARY.md
  modified:
    - src/alphaswarm/worker.py
    - src/alphaswarm/batch_dispatcher.py
    - src/alphaswarm/simulation.py
    - tests/test_worker.py
    - tests/test_batch_dispatcher.py
    - tests/test_simulation.py

key-decisions:
  - "D-04: market_context system message appended BEFORE peer_context so the market picture is available to the model before peer reasoning arrives in later rounds"
  - "D-06 scope containment: _dispatch_round (Rounds 2-3) and run_simulation intentionally untouched in Plan 01; Plan 02 wires the ContextPacket into run_simulation -> run_round1"
  - "D-07: dispatch_wave forwards market_context as a single scalar to every agent in the wave (not a per-agent list like peer_contexts)"
  - "TDD RED-GREEN cycle: one test commit with failing assertions, two feat commits that flip assertions GREEN"

patterns-established:
  - "TDD layered verification: tests exist at each of the three plumbing layers (worker, dispatcher, run_round1) so regressions localize quickly"
  - "Mock signature updates as auto-fix: when a kwarg gets added to a production signature, existing mock_infer stubs must grow the same kwarg (Rule 1 scope-local fix)"

requirements-completed: [SIM-04]

# Metrics
duration: ~25 min
completed: 2026-04-19
---

# Phase 40 Plan 01: Simulation Context Wiring — market_context plumbing skeleton

**Threaded `market_context: str | None` end-to-end from `run_round1` through `dispatch_wave` and `_safe_agent_inference` into `AgentWorker.infer` with D-04 system-message ordering, behind six Wave 0 unit tests.**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-04-19T17:10:00Z (approx)
- **Completed:** 2026-04-19T17:35:00Z (approx)
- **Tasks:** 3 (all autonomous, all TDD)
- **Files modified:** 6 source/test files + 2 planning files created

## Accomplishments

- `AgentWorker.infer` now accepts `market_context: str | None = None` and injects a `{"role": "system", "content": "Market context:\n..."}` message BEFORE any peer_context block per D-04.
- `dispatch_wave` and `_safe_agent_inference` forward the `market_context` scalar identically to every agent in the wave per D-07.
- `run_round1` accepts and forwards `market_context` to `dispatch_wave`; Rounds 2-3 (`_dispatch_round`) and `run_simulation` remain untouched per D-06.
- Six new Wave 0 tests (two per source file) lock in the D-04 ordering, D-07 scalar semantics, and D-06 scope containment.
- Backward compatibility preserved: calling any of the four plumbing functions without `market_context` yields byte-identical messages lists to the pre-Phase-40 baseline.

## Task Commits

Each task was committed atomically:

1. **Task 1: Wave 0 — Write six failing unit tests for market_context plumbing** — `338eb9b` (test)
2. **Task 2: Implement market_context in AgentWorker.infer** — `09a33ab` (feat)
3. **Task 3: Thread market_context through dispatch_wave and run_round1** — `041dcf5` (feat, includes auto-fix of 5 existing mock_infer signatures + 2 _safe_agent_inference direct-call tests)

## Files Created/Modified

- `src/alphaswarm/worker.py` — AgentWorker.infer gains `market_context: str | None = None`; messages list gains conditional `"Market context:\n..."` system message BEFORE peer_context.
- `src/alphaswarm/batch_dispatcher.py` — `_safe_agent_inference` gains positional `market_context: str | None`; `dispatch_wave` gains kw-only `market_context: str | None = None`; TaskGroup `tg.create_task` call forwards the scalar.
- `src/alphaswarm/simulation.py` — `run_round1` gains kw-only `market_context: str | None = None`; existing dispatch_wave call site now forwards `market_context=market_context`.
- `tests/test_worker.py` — adds `test_infer_with_market_context` + `test_infer_with_market_and_peer_context`.
- `tests/test_batch_dispatcher.py` — adds `test_dispatch_wave_forwards_market_context` + `test_dispatch_wave_market_context_default_none`; five existing `mock_infer` stubs + two direct `_safe_agent_inference` calls updated to accept/pass the new kwarg (Rule 1 auto-fix).
- `tests/test_simulation.py` — adds `test_market_context_round1_only` + `test_run_round1_market_context_default_none`.
- `.planning/phases/40-simulation-context-wiring/deferred-items.md` — documents 6 pre-existing mypy errors in simulation.py unrelated to Plan 01 (verified pre-existing via `git stash` + mypy re-run).

## Decisions Made

- Chose `.append` twice (not `.insert(1, ...)`) in AgentWorker.infer so D-04 ordering is enforced by source order — reads top-to-bottom and matches existing peer_context style.
- Did NOT introduce a per-agent `market_contexts: list[str | None] | None` — Plan 40 CONTEXT.md D-07 locks the contract as scalar-for-all; per-agent variation would blow the M1 context window on formatter output reuse.
- Left `run_simulation` untouched despite it being the natural parent call site — Plan 02 will add provider params there and wire them through to `run_round1.market_context=`. Keeping Plan 01 surgical avoids premature coupling.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 — Bug] Existing `mock_infer` stubs in test_batch_dispatcher.py did not accept the new `market_context` kwarg**
- **Found during:** Task 3 (verification run after threading the kwarg through dispatch_wave)
- **Issue:** 5 pre-existing `mock_infer` signatures were declared as `(user_message, peer_context=None)` and TypeError'd once `_safe_agent_inference` started forwarding `market_context=` to `worker.infer`. Tests: `test_partial_failure_produces_parse_error`, `test_batch_failure_threshold_hit`, `test_low_failure_rate_does_not_call_report`, `test_dispatch_wave_per_agent_peer_contexts`, `test_dispatch_wave_peer_contexts_none_falls_back_to_scalar`.
- **Fix:** Appended `market_context: str | None = None` to each `mock_infer` signature via `replace_all` Edit. No assertion changes.
- **Files modified:** tests/test_batch_dispatcher.py
- **Verification:** 103 tests pass across test_worker.py, test_batch_dispatcher.py, test_simulation.py.
- **Committed in:** 041dcf5 (Task 3 commit)

**2. [Rule 1 — Bug] Two direct `_safe_agent_inference` calls in cancellation tests missed the new required positional `market_context` arg**
- **Found during:** Task 3 (same verification run)
- **Issue:** `test_cancelled_error_propagates` + `test_keyboard_interrupt_propagates` call `_safe_agent_inference` directly with positional args. Adding `market_context: str | None` as a required positional between `peer_context` and `jitter_min` shifts the signature and made both tests fail with `TypeError: _safe_agent_inference() missing 1 required positional argument`.
- **Fix:** Added `market_context=None` kwarg to both direct call sites. The kwarg form side-steps the positional-position shift and is self-documenting.
- **Files modified:** tests/test_batch_dispatcher.py
- **Verification:** Both tests green after fix.
- **Committed in:** 041dcf5 (Task 3 commit)

### Out-of-Scope Discoveries (logged, not fixed)

- **Pre-existing mypy strict errors in simulation.py** — 6 errors at lines 28 (BracketConfig attr-defined), 107 (str | None assignment), 1179/1185, 1198/1204, 1201/1207 (three type-arg untyped dicts), 1238/1244 (OllamaClient.generate "system" call-arg). Verified pre-existing via `git stash` + mypy re-run on commit `2f841ca`. Tracked in `.planning/phases/40-simulation-context-wiring/deferred-items.md`. Per Scope Boundary rule, not fixed in Plan 01.

---

**Total deviations:** 2 auto-fixed (both Rule 1 scope-local bugs introduced by the new signature)
**Impact on plan:** Minimal. Both auto-fixes are direct mechanical consequences of adding the new parameter; they preserve all existing test assertions. No scope creep.

## Issues Encountered

- Test D (`test_dispatch_wave_market_context_default_none`) passed on RED because my `mock_infer` defined `market_context: str | None = None` as a default-None kwarg, so when `dispatch_wave` forwarded no `market_context` the mock still accepted the call and recorded `None`. The plan anticipated 6 RED failures; actual was 5 RED + 1 passing baseline test. This is expected behavior — the test asserts the backward-compat baseline still works, and is semantically a regression guard rather than a strict TDD RED test. All six tests exist, five flip GREEN when Tasks 2-3 land, and one stays GREEN throughout.

## User Setup Required

None — pure in-process parameter threading, no external services.

## Threat Flags

None — no new trust boundaries crossed. market_context content flows in from Phase 38 providers via Plan 02 formatter (out of Plan 01 scope).

## Next Phase Readiness

- Plumbing skeleton ready for Plan 02 to inject a real string built from `ContextPacket` data (prices + headlines).
- `run_simulation` is the next integration point: Plan 02 will add provider params there, assemble a `ContextPacket`, format it, and pass the result to `run_round1(market_context=...)`.
- No blockers.

## Self-Check: PASSED

- FOUND: src/alphaswarm/worker.py (market_context param at line 73; `if market_context:` block before `if peer_context:`)
- FOUND: src/alphaswarm/batch_dispatcher.py (market_context positional in `_safe_agent_inference`; kw-only in `dispatch_wave`; forwarded in `tg.create_task`)
- FOUND: src/alphaswarm/simulation.py (market_context kw-only in `run_round1` at line 435; forwarded at dispatch_wave call line 509)
- FOUND: tests/test_worker.py (test_infer_with_market_context, test_infer_with_market_and_peer_context)
- FOUND: tests/test_batch_dispatcher.py (test_dispatch_wave_forwards_market_context, test_dispatch_wave_market_context_default_none)
- FOUND: tests/test_simulation.py (test_market_context_round1_only, test_run_round1_market_context_default_none)
- FOUND: commit 338eb9b (test(40-01): add failing tests for market_context plumbing)
- FOUND: commit 09a33ab (feat(40-01): add market_context to AgentWorker.infer)
- FOUND: commit 041dcf5 (feat(40-01): thread market_context through dispatch_wave and run_round1)
- FOUND: 103 tests green across the three test files; lint-imports green; zero market_context references in `_dispatch_round` or `run_simulation` bodies (D-06 + scope containment confirmed).

---
*Phase: 40-simulation-context-wiring*
*Completed: 2026-04-19*
