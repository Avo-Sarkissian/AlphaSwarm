---
phase: 30
reviewers: [gemini, codex]
reviewed_at: 2026-04-13T00:00:00Z
plans_reviewed: [30-01-PLAN.md, 30-02-PLAN.md]
---

# Cross-AI Plan Review — Phase 30: WebSocket State Stream

---

## Gemini Review

### Summary
The implementation plans for Phase 30 are well-structured, logically sequenced, and demonstrate a strong understanding of the FastAPI/asyncio ecosystem. By leveraging the `ConnectionManager` and `StateStore` infrastructure from Phase 29, the plans focus on the core "broadcaster" logic and the WebSocket route. The TDD approach in Plan 30-01 is excellent for ensuring the new integration points are reliable before wiring them into the main application. The plans correctly address critical asyncio patterns, such as proper `CancelledError` propagation and the "receive loop" requirement for WebSocket disconnect detection.

### Strengths
- **Strategic TDD (Wave 0):** Starting with failing integration tests that verify the lifespan and router integration ensures that the "wiring" is correct from the start.
- **Correct Task Lifecycle Management:** Plan 30-02 correctly uses the FastAPI lifespan for the broadcaster task and implements a clean shutdown sequence (`cancel()` + `await`).
- **Proper Exception Handling:** The explicit instruction to catch `Exception` but let `BaseException` (and thus `CancelledError`) propagate in the broadcast loop is vital for a responsive system.
- **Disconnect Detection:** Task 3 in Plan 30-01 correctly identifies that a `while True: await receive_text()` loop is necessary to detect client disconnects in FastAPI.
- **Separation of Concerns:** The `snapshot_to_json` helper encapsulates serialization logic, making the broadcaster loop cleaner and more testable.

### Concerns
- **MEDIUM — Rationale Drainage Rate:** The broadcaster drains only 5 rationales per tick (5Hz = 25 per second). In a 100-agent simulation, if a "round" triggers many agents simultaneously, the rationale buffer might grow faster than it is drained, leading to a "lagging" UI where rationales appear long after the state has changed.
- **LOW — JSON Serialization of Enums:** User Decision D-05 assumes `json.dumps(dataclasses.asdict(snapshot))` will work for `SignalType` (Str/Enum). Standard `json.dumps` does not handle Enums automatically unless they inherit from `str` (e.g., `class SignalType(str, Enum)`). If they are standard Enums, this will raise a `TypeError`. *[Note: Research confirms they are `str, Enum` — this is low risk but worth verifying.]*
- **LOW — Always-on Tick Inefficiency:** D-01 specifies the broadcaster ticks even when IDLE and with 0 clients. While simple, this consumes unnecessary CPU/IO (snapshotting 100 agents 5 times a second) when no one is watching.
- **LOW — Race Condition in `snapshot_to_json`:** `snapshot_to_json` calls `snapshot()` (non-destructive) then `drain_rationales()` (destructive). In high-concurrency, new rationales could be added between these two calls, meaning they appear in the next tick's snapshot instead of the current one. Acceptable for a UI stream but worth noting.

### Suggestions
- **Dynamic Rationale Drain:** Instead of a hard limit of 5, consider draining "all available" or a larger batch (e.g., 20–50) per tick to ensure the UI stays synchronized with simulation pace.
- **Verify Enum Inheritance:** Double-check that all Enums in `StateSnapshot` are defined as `(str, Enum)` or `StrEnum` to ensure `json.dumps` in `snapshot_to_json` doesn't crash.
- **Broadcaster Optimization:** Consider adding `if not connection_manager.client_count: continue` at the start of the loop to skip expensive state snapshots when no clients are connected.
- **Testing Timing:** In `test_ws_state_receives_snapshot`, use a small `asyncio.wait_for` to prevent the test from hanging if the broadcaster fails to tick.

### Risk Assessment
**Overall Risk: LOW**

The technical complexity is low because the heavy lifting (queuing, writer tasks) was completed in Phase 29. The primary risks are "soft" issues like UI lag (rationale drainage) or minor serialization errors, rather than system crashes or memory leaks. The cleanup logic is robust, which is the most common failure point for WebSocket implementations. The plan strictly adheres to the hard constraints (100% async, local only) and follows established architectural patterns.

---

## Codex Review

### Plan 30-01 Summary
Strong core implementation plan. It targets the right surface area, keeps the broadcaster independent from simulation lifecycle per D-01/D-02, and explicitly handles the major asyncio pitfalls: `CancelledError` propagation and WebSocket disconnect detection. The main risks are around timing semantics, destructive rationale draining, and test realism around FastAPI lifespan behavior.

### Plan 30-01 Strengths
- Clean separation: `broadcaster.py` owns snapshot serialization and tick loop; `routes/websocket.py` owns WebSocket lifecycle only.
- Correctly avoids catching `BaseException`, so task cancellation can propagate.
- Includes a receive loop, which is necessary for FastAPI/Starlette to observe client disconnects.
- Uses Phase 29 `ConnectionManager` instead of reimplementing queueing or writer-task logic.
- Test coverage maps well to the phase success criteria: serialization, cancellation, receive stream, disconnect cleanup.

### Plan 30-01 Concerns
- **HIGH:** `snapshot() + drain_rationales(5) + asdict()` is ambiguous and may be wrong. If the snapshot is created before draining and the drained rationale entries are not explicitly inserted into the snapshot dict, the stream can omit rationales while still destructively removing them.
- **MEDIUM:** Starting the broadcaster inside `_unit_lifespan` may mutate shared test state by draining rationales during unrelated tests. This can create timing-dependent failures.
- **MEDIUM:** `test_ws_state_receives_snapshot` can become flaky or hang if it depends on a real 200ms background tick with `TestClient`. The test needs a deterministic timeout or a shortened test interval.
- **MEDIUM:** The route depends on `websocket.app.state.connection_manager`. The plan should verify that both test app and production app expose that exact state field.
- **MEDIUM:** Loop shape `snapshot + broadcast; await sleep(0.2)` means cadence is "work time + 200ms," not true 5Hz. Probably fine for 7.3KB snapshots, but it can drift under load.
- **LOW:** The TDD "4 new stubs fail with ImportError" claim may become a collection-level failure if missing modules are imported at test module import time.
- **LOW:** `receive_text()` is acceptable for disconnect detection, but `receive()` would be more tolerant if clients ever send non-text frames.
- **LOW:** Logging inside the broadcast loop should avoid noisy repeated logs if `snapshot()` or `broadcast()` fails every 200ms. A throttled or structured error log would be safer.

### Plan 30-01 Suggestions
- Make `snapshot_to_json` explicitly merge drained rationales into the emitted snapshot, e.g., `d["rationale_entries"] = [dataclasses.asdict(r) for r in rationales]` (override after `asdict(snap)`) — make this explicit in the plan.
- Add a test that proves rationales are included once and then drained on the next call.
- Parameterize or isolate the test app so the broadcaster only starts for WebSocket integration tests that need it.
- Add time-bounded WebSocket receive tests to avoid indefinite hangs.
- Audit other `drain_rationales` callers so the broadcaster is truly the sole owner from this phase forward.
- Schedule ticks against `time.monotonic()` or at least document that "approximately 5Hz" means "work time + 200ms."

### Plan 30-01 Risk Assessment
**MEDIUM.** The async structure is sound, but destructive rationale drain semantics and background-test timing need tightening before this is safe to approve as-is.

---

### Plan 30-02 Summary
This plan covers the missing production wiring and has the right lifecycle shape: start the broadcaster in FastAPI lifespan and cancel it during teardown before closing deeper resources. The manual smoke test is useful, but automated coverage should also exercise the real `create_app()` path so production router and app state wiring cannot drift from the test helper.

### Plan 30-02 Strengths
- Correctly wires the WebSocket router without a prefix, matching `/ws/state`.
- Starts the broadcaster in FastAPI lifespan, matching D-01.
- Cancels and awaits the broadcaster task in teardown, avoiding pending task warnings.
- Manual smoke test is well scoped: one client, two clients, disconnect behavior, server shutdown.
- Uses a human checkpoint appropriately because SC-1 and SC-2 are timing/user-observable behaviors.
- No scope creep into auth, Pydantic models, or simulation start/stop wiring.

### Plan 30-02 Concerns
- **HIGH:** Verify object identity — the broadcaster and WebSocket route must use the same `connection_manager`. If `app_state.connection_manager` and the local `connection_manager` variable in lifespan differ, clients can connect but receive nothing.
- **MEDIUM:** If all tests use `_make_test_app()` instead of `create_app()`, production wiring can be broken while the 11 tests still pass. At least one test should call `create_app()`.
- **MEDIUM:** Cancelling the broadcaster does not necessarily clean up existing per-client writer tasks unless the WebSocket route or `ConnectionManager` handles shutdown cleanly.
- **MEDIUM:** Teardown cancels broadcaster before `graph_manager.close()`, but should also ensure `connection_manager` writer tasks are cleaned up if active clients remain during shutdown.
- **LOW:** `autonomous: false` is appropriate for the smoke test, but the code wiring itself appears safe to make autonomously after 30-01 passes.
- **LOW:** The plan does not mention local-dev-only security documentation. Unauthenticated WebSocket is acceptable per D-10, but should be clearly kept bound to local/dev assumptions.

### Plan 30-02 Suggestions
- Add one automated integration test using the real `create_app()` lifespan to verify `/ws/state` is registered and receives a snapshot.
- In teardown, use `contextlib.suppress(asyncio.CancelledError)` around `await broadcaster_task`.
- If `ConnectionManager` has a close/shutdown method, call it during lifespan teardown after cancelling the broadcaster.
- Confirm the web command binds to localhost for this unauthenticated phase, or add an explicit follow-up to enforce origin/host restrictions.
- In the smoke test, validate message shape minimally: `phase`, `agent_states`, `governor_metrics`, and rationale count behavior.
- Confirm `CancelledError` import behavior under Python 3.10 and catch `asyncio.CancelledError` explicitly.

### Plan 30-02 Risk Assessment
**LOW to MEDIUM.** App wiring is simple, but lifecycle mismatches are common with FastAPI tests and background tasks. The manual smoke test plus one production-app integration test should reduce the risk substantially.

### Overall Codex Assessment
The two-plan split is sound: 30-01 builds and tests the core behavior, while 30-02 wires production lifespan and performs manual validation. The plans are not over-engineered and mostly honor the phase decisions. The main improvements are: adding a rationale-drain test, tightening lifespan parity between tests and production, and being explicit about the 5Hz timing model.

---

## Consensus Summary

### Agreed Strengths
- **Correct `CancelledError` handling** (both reviewers): `except Exception` not `except BaseException` in broadcast loop is the right call and correctly identified as the critical pitfall.
- **Receive loop for disconnect detection** (both reviewers): `while True: receive_text()` is necessary and the plans handle it correctly.
- **Phase 29 infrastructure reuse** (both reviewers): `ConnectionManager` and `StateStore` are consumed, not rebuilt. Clean boundary.
- **Lifespan ownership of broadcaster task** (both reviewers): `asyncio.Task` started in lifespan, stored on `app.state`, cancelled in teardown — correct pattern.
- **TDD Wave 0** (both reviewers): Failing stubs before implementation is a strength.

### Agreed Concerns (Priority Order)

1. **`drain_rationales` destructive semantics need explicit handling in `snapshot_to_json`** (both — Codex HIGH, Gemini LOW-MEDIUM)
   - The `asdict(snap)` call produces a snapshot with rationale_entries from the snapshot itself (empty or stale). The drained rationales must be explicitly overridden: `d["rationale_entries"] = [dataclasses.asdict(r) for r in drain_rationales(5)]`. If this override is omitted, rationale entries are silently dropped. Both reviewers flag this.

2. **Test/production lifespan parity gap** (both — Codex HIGH, Gemini implicitly)
   - All 11 tests pass through `_make_test_app()`. If production `app.py` wiring is broken, tests won't catch it. At least one test should exercise `create_app()` path.

3. **`test_ws_state_receives_snapshot` timing/hang risk** (both — Codex MEDIUM, Gemini MEDIUM)
   - Test depends on a real 200ms broadcaster tick inside `TestClient`. Needs either a time-bounded receive with explicit timeout or test isolation via mock broadcaster.

4. **Rationale drainage rate** (Gemini MEDIUM)
   - 5 per tick (25/second) may not keep up with a 100-agent simulation round. Consider draining more aggressively or tracking drain backpressure.

5. **No `create_app()` integration test** (both — Codex MEDIUM, Gemini implicitly)
   - Production app wiring should be exercised by at least one automated test, not only the manual wscat checkpoint.

### Divergent Views
- **Risk level**: Gemini rates overall LOW; Codex rates MEDIUM. The difference is that Codex places more weight on test/production parity and the rationale drain semantics, while Gemini focuses on the runtime correctness of the happy path.
- **Rationale drain limit**: Gemini suggests increasing the drain limit (20–50); Codex says keep the helper narrow and document the ownership. Both are valid — the 5 limit matches CONTEXT.md D-04 as written; executor discretion.
- **Broadcaster optimization for 0 clients**: Gemini suggests skipping snapshot when `client_count == 0`. Codex does not mention this. It's a nice-to-have, not a requirement.

---

*Reviewed: 2026-04-13 | Plans: 30-01-PLAN.md, 30-02-PLAN.md | Reviewers: Gemini, Codex*
*To incorporate feedback: `/gsd-plan-phase 30 --reviews`*
