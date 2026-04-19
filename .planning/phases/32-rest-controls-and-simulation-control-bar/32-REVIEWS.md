---
phase: 32
reviewers: [gemini, codex]
reviewed_at: 2026-04-14T10:15:00-04:00
plans_reviewed: [32-01-PLAN.md, 32-02-PLAN.md, 32-03-PLAN.md, 32-04-PLAN.md]
---

# Cross-AI Plan Review — Phase 32: REST Controls and Simulation Control Bar

---

## Gemini Review

### Summary

The plans are well-structured and align closely with the project's local-first, async-heavy architecture. The refactoring of `SimulationManager` to use `asyncio.create_task` with a `done-callback` is an idiomatic solution for backgrounding the simulation engine while keeping the FastAPI event loop responsive. The use of HTTP 409 (Conflict) for guardrails (e.g., stopping a non-existent simulation or queuing a second shock) is robust. However, there is a notable gap regarding the edge list endpoint mentioned in the success criteria, and some minor risks around async task cancellation and UI feedback.

### Strengths

- **State Integrity:** Using an `asyncio.Lock` and a `done-callback` in `SimulationManager` ensures that the simulation state (`_is_running`, `_task`, `_pending_shock`) is always cleaned up, even if the task fails or is cancelled.
- **Semantic HTTP Usage:** Using `202 Accepted` for starting simulations and `409 Conflict` for state violations follows REST best practices for long-running processes.
- **Frontend Modularity:** Injecting the `snapshot` ref into `ControlBar.vue` leverages Vue's provide/inject pattern effectively, keeping the control bar reactive to engine state changes without prop-drilling.
- **Safety Guards:** The 503 guard on Replay endpoints when Neo4j is offline prevents crashes during the transition phase.

### Concerns

- **[MEDIUM] Missing Endpoint:** Success Criterion #3 (`GET /api/edges/{cycle_id}?round=N`) is explicitly listed in the Phase goals but is **missing** from the implementation tasks in Plans 32-01 and 32-02.
- **[LOW] Task Cancellation Handling:** If `SimulationManager.stop()` calls `_task.cancel()`, the `run_simulation` logic in `simulation.py` must be checked for how it handles `asyncio.CancelledError`. If it doesn't catch it during long-running Ollama inference, the cleanup in `_on_task_done` will still run, but the engine might leave intermediate files or logs in an inconsistent state.
- **[LOW] Optimistic UI Sync:** `ControlBar.vue` relies on `snapshot.phase` from the WebSocket. There may be a 100–500ms lag between clicking "Start" (POST 202) and the first WebSocket update. Without a local `isStarting` state, the user might click "Start" twice.
- **[LOW] Replay Stub Completeness:** While stubs are expected, ensure the `SimulationManager` is prepared to ignore or handle replay-driven state changes to avoid conflicts with "Live" simulation state logic.

### Suggestions

- **Add the Edge Endpoint:** Update Plan 32-02 to include the `GET /api/edges/{cycle_id}` route. This should query Neo4j for `INFLUENCED_BY` relationships filtered by the `round` property.
- **Improve `_on_task_done` Robustness:** Ensure the callback explicitly checks `task.exception()` and logs it via `structlog`. This is critical because exceptions in backgrounded tasks are silent unless retrieved.
- **Add Local Loading State:** In `ControlBar.vue`, add a `processing` ref that is set to `true` when a POST request is in flight and cleared once the request completes (or when the phase changes).
- **Verify `run_simulation` Entry Point:** Confirm that `simulation.py` can accept an `AppState` object or the specific subset of parameters passed by `SimulationManager` without blocking the loop.

### Risk Assessment: LOW

The core architectural decisions (Task-based backgrounding and Pydantic-validated REST routes) are sound and fit the existing stack. The risks are primarily around minor feature omissions (the edge endpoint) and edge-case error logging, both of which are easily addressed within the current wave structure.

**Overall: Recommended for implementation with the addition of the missing edge endpoint.**

---

## Codex Review

### Summary

The phase is directionally solid and maps well to the backend/UI goals, but I would not run the Wave 1 plans fully autonomously as written. Plans 32-01 and 32-02 both touch the FastAPI app factory and shared web tests, so they have a real merge/integration risk. The biggest product risks are backend task lifecycle cleanup, stop-state reset, replay "completed cycle" semantics, and a frontend event-contract mismatch around opening the shock drawer.

### Plan 32-01: SimulationManager Refactor + Stop/Shock Endpoints + Tests

**Summary:** Good scope and mostly correct backend direction, but this is the highest-risk plan because it changes simulation lifecycle ownership, cancellation, and concurrency guards.

**Strengths:**
- Uses `asyncio.create_task()` and a done-callback, which matches BE-05's "return 202 immediately" requirement.
- Adds explicit stop/shock domain errors instead of leaking implementation details through routes.
- Includes shock double-submit protection, which directly supports the 409 guard criterion.

**Concerns:**
- **[HIGH]** The lock lifecycle must be manual and precise. If `async with lock` remains in `start()`, the lock releases immediately after task creation and concurrent starts can slip through.
- **[HIGH]** Stop/cancel cleanup is underspecified. If cancellation leaves `StateStore.phase` at `round_2` or `round_3`, the UI may never return to idle even though `_is_running` resets.
- **[MEDIUM]** Done-callback must consume task exceptions via `task.result()` or guarded `task.exception()`; otherwise failed background simulations can produce unhandled task warnings.
- **[MEDIUM]** Unit tests must patch `run_simulation()` with a long-lived coroutine. The test app currently creates no Ollama/Neo4j clients, so an unpatched task will fail immediately and make lifecycle assertions flaky.
- **[MEDIUM]** `tests/test_web 2.py` (duplicate file) may still instantiate old manager shape and fail suite collection.

**Suggestions:**
- Add an explicit cancellation cleanup path that sets phase back to `idle` via `state_store.set_phase(SimulationPhase.IDLE)` in `_on_task_done` when cancelled.
- Validate and trim seed/shock text with Pydantic bounds to avoid empty or huge local-model prompts.
- Add tests for task exception cleanup, cancellation cleanup, immediate 202 behavior, and "second start while first task is still pending."
- Coordinate shared edits with Plan 32-02 because both touch `app.py` and `test_web.py`.

**Risk Assessment: HIGH** until cancellation/state reset and test integration are tightened.

---

### Plan 32-02: Replay Router + Registration + Tests

**Summary:** A clean, well-bounded backend plan, but it needs a sharper definition of "completed cycles" and stronger Neo4j failure handling.

**Strengths:**
- Keeps replay routes in a dedicated router, preserving route organization.
- Implements the real cycles query now while leaving replay start/advance logic as Phase 34 stubs.
- Includes 503 behavior for missing Neo4j in the unit-test app.

**Concerns:**
- **[HIGH]** "Completed simulation cycles" is not defined. Cycle nodes can exist before a run completes, so the query should filter by completed evidence (e.g., round 3 decisions or a completion marker).
- **[MEDIUM]** "Neo4j offline" should catch `Neo4jConnectionError`, not only `graph_manager is None`.
- **[MEDIUM]** Neo4j datetime values need explicit conversion to strings before returning JSON.
- **[LOW]** Stub response contracts should be formal Pydantic models so Phase 34 does not accidentally change API shape.
- **[LOW]** Add a production route-registration test, not only `_make_test_app()` coverage.

**Suggestions:**
- Define `read_completed_cycles()` as a query over cycles with at least one round 3 decision, returning sorted newest-first with a sensible limit.
- Decide whether `/api/replay/cycles` returns a raw list or a wrapper like `{cycles: [...]}` and freeze that in tests.
- Add tests for empty cycles, completed versus incomplete cycles, Neo4j exception-to-503 mapping.

**Risk Assessment: MEDIUM** — implementation is small, but eligibility semantics can easily be wrong.

---

### Plan 32-03: ControlBar.vue + ShockDrawer.vue + App.vue Layout

**Summary:** The UI scope is appropriate, but the plan has a concrete event ownership mismatch and needs more request-state/error-state detail.

**Strengths:**
- Uses existing `provide/inject` snapshot flow instead of introducing a second state source.
- Correctly places the drawer below the top bar rather than using a modal overlay.
- Keeps the graph as the main experience and adapts App layout around it.

**Concerns:**
- **[HIGH]** ControlBar both manages `showDrawer` internally and is wired from App via `@shock`. Pick one owner; otherwise the "+Inject Shock" button may not open the actual drawer.
- **[MEDIUM]** Start can be clicked again before the WebSocket phase flips unless there is local `startPending` state.
- **[MEDIUM]** The phase label plan shows raw `round_2` instead of the required "Round 2 / 3" style.
- **[MEDIUM]** The shock success confirmation is not specified; closing the drawer alone does not meet the confirmation criterion.
- **[LOW]** Prefer existing CSS variables over adding a separate dark purple-blue control bar palette.

**Suggestions:**
- Make ControlBar emit `shock` and let App own `showShockDrawer`, OR place ShockDrawer fully inside ControlBar — pick one approach and eliminate the split.
- Add local `pending`/`error`/`success` state for start, stop, and shock submission.
- Use a formatted phase label computed from `snapshot.round_num`, with fallback labels for `seeding` and `complete`.
- Ensure the graph container uses `flex: 1; min-height: 0` so ForceGraph resizing remains correct below the new top strip.

**Risk Assessment: HIGH** as written due to the drawer event-contract issue; MEDIUM after that is corrected.

---

### Plan 32-04: Frontend Build + Human Visual Verification

**Summary:** The checkpoint is useful, but it is too manual and does not fully specify the runtime environment needed for verification.

**Strengths:**
- Includes a real production build gate.
- Adds human checks for the exact UI behavior that automated unit tests may miss.
- Correctly verifies the 409 shock path from a user-flow perspective.

**Concerns:**
- **[MEDIUM]** Vite dev server alone is insufficient; API and WebSocket calls proxy to a FastAPI backend on port 8000.
- **[MEDIUM]** Human verification may accidentally launch a real 100-agent Ollama simulation, which is slow and memory-heavy for a UI smoke check.
- **[LOW]** Does not mention rerunning backend web tests after integrating the Wave 1 changes.

**Suggestions:**
- Add backend test gates before the visual checkpoint: targeted web tests plus replay/simulation tests.
- Specify the dev setup explicitly: backend server plus frontend dev server, or a mocked backend fixture for UI-only verification.

**Risk Assessment: MEDIUM** — build check is good, but the manual verification environment is under-specified.

---

## Consensus Summary

Phase 32 reviewed by 2 AI systems (Gemini, Codex). Claude skipped (current runtime).

### Agreed Strengths

- `asyncio.create_task` + done-callback is the correct pattern for fire-and-forget simulation launch
- HTTP 409 guards for stop/shock with no active simulation are well-designed
- Vue `provide/inject` snapshot approach avoids prop-drilling; correct architectural choice
- 503 fallback for Neo4j offline on replay endpoints is robust
- Dedicated `routes/replay.py` router file maintains clean domain separation

### Agreed Concerns (Priority Order)

1. **[HIGH — both reviewers]** Stop/cancel does not reset `StateStore.phase` to `idle` — UI may stay stuck in `round_2`/`round_3` after a stop. The `_on_task_done` callback resets `_is_running` but doesn't call `state_store.set_phase(IDLE)` on cancellation.

2. **[HIGH — Codex]** Lock lifecycle: if `async with self._lock` is used in `start()`, the lock releases immediately after `create_task()` returns, allowing concurrent starts to proceed. Must use `await self._lock.acquire()` without `async with` and release only in `_on_task_done`.

3. **[HIGH — Codex]** Drawer event ownership split: ControlBar has `showDrawer` internal state AND App.vue wires `@shock` to `showShockDrawer`. These conflict — define a single owner.

4. **[MEDIUM — both reviewers]** Missing edge endpoint: SC-3 (`GET /api/edges/{cycle_id}?round=N`) is in the phase success criteria but not in any plan.

5. **[MEDIUM — Codex]** "Completed cycles" definition: the `read_completed_cycles()` query needs a filter (e.g., cycles with round 3 data) to avoid returning in-progress cycles.

6. **[MEDIUM — both reviewers]** Double-click Start risk: no local `isStarting`/`pending` state in ControlBar, so user can re-click between the POST 202 and the first WebSocket phase update.

7. **[MEDIUM — Codex]** Phase label shows raw enum string (`round_2`) instead of formatted "Round 2 / 3".

### Divergent Views

- **Gemini** rated overall risk as LOW; **Codex** rated Plan 32-01 as HIGH and 32-03 as HIGH. Codex inspected the actual codebase and found additional lock lifecycle and state-reset issues that Gemini assessed as lower risk from a planning-document review. The Codex concerns (items 2–3 above) are concrete code-level bugs that should be addressed before execution.

---

*To incorporate feedback:* `/gsd-plan-phase 32 --reviews`
