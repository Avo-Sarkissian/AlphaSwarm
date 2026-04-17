---
phase: 36
reviewers: [gemini, codex]
reviewed_at: 2026-04-17T02:37:14Z
plans_reviewed: [36-01-PLAN.md, 36-02-PLAN.md]
---

# Cross-AI Plan Review — Phase 36

## Gemini Review

# Plan Review: Phase 36 — Report Viewer

This review covers **Plan 01 (Backend)** and **Plan 02 (Frontend)** for Phase 36 of the AlphaSwarm project.

## Summary

The proposed plans for Phase 36 are exceptionally well-structured and provide a comprehensive path to implementing the Report Viewer. Plan 01 correctly mirrors the established ReACT report generation logic from the CLI into a FastAPI background task, while Plan 02 provides a high-fidelity Vue 3 implementation that adheres strictly to the project's existing modal and styling patterns. The integration of security measures (XSS sanitization and path traversal guards) and resource management (Ollama model lifecycle) demonstrates a deep understanding of the project's constraints and best practices.

## Strengths

- **Pattern Consistency:** The plans reuse proven architectural patterns from `CyclePicker.vue`, `interview.py`, and `replay.py`, minimizing the risk of "reinventing the wheel" and ensuring a cohesive user experience.
- **Robust Resource Management:** Plan 01 explicitly handles the loading and unloading of the orchestrator model within a `finally` block, preventing model lock leaks in the event of generation failures.
- **Security-First Approach:** The proactive inclusion of `DOMPurify` for client-side sanitization and regex validation for `cycle_id` to prevent path traversal follows industry best practices and the project's specific security mandates.
- **Comprehensive Testing:** Plan 01 includes a detailed TDD approach with 10 specific test cases covering various edge cases (404, 409, 503, 400 errors), ensuring the backend is resilient before frontend integration begins.
- **Polling Lifecycle Management:** Plan 02 correctly addresses potential memory leaks by ensuring `setInterval` is cleared on component unmount (`onUnmounted`) and includes a sensible 10-minute timeout cap.

## Concerns

- **Atomic File Writes (LOW):** Plan 01 mirrors the CLI's `write_report` logic, which writes directly to the destination path. There is a theoretical (though small) race condition where the frontend polling might hit a file that has been created but not yet fully written, resulting in a blank or truncated render.
- **Phase Transition Race (LOW):** If a user starts a new simulation while a report is generating for a previous cycle, both the report task and the simulation will compete for Ollama resources. While the governor should handle this, the UI might feel sluggish.
- **Markdown Header Hierarchy (LOW):** The report's `h1` might conflict with the modal's `h2` title. While the plan addresses this with scoped CSS, it's a minor semantic inconsistency.

## Suggestions

- **Enhance File Writing:** Consider modifying `src/alphaswarm/report.py` (or the logic in the new route) to write the report to a `.tmp` file first and then rename it to the final destination to prevent partial-read races.
- **Polling Feedback:** If polling hits the 10-minute cap, also provide a "Retry Polling" button in the error state to allow resumption without closing the modal.
- **Simultaneous Task Guard:** Consider warning the user if they try to start a simulation while a report is generating, as this will significantly impact M1 Max performance.

## Risk Assessment

**Overall Risk: LOW**

The plans are grounded in existing, verified code and patterns. The dependencies (`marked`, `dompurify`) are standard and well-understood. The technical risks regarding concurrency and memory are well-mitigated by the phase guards and model manager locks.

**Status: APPROVED**

---

## Codex Review

## Plan 01: Backend

**Summary**
Plan 01 is mostly solid and well-aligned with the phase goal. It reuses the existing Phase 15 report pipeline, keeps the backend additive, adds meaningful endpoint tests, and includes the important guards: missing services, wrong phase, duplicate generation, invalid `cycle_id`, and model unload in `finally`. The main risks are around background task lifecycle, strict async compliance, and the decision to tie report generation to the current in-memory simulation phase.

**Strengths**

- Reuses existing `ReportEngine`, `ReportAssembler`, `write_report`, and `write_sentinel` instead of duplicating report logic.
- Good security posture on `cycle_id` path traversal with a strict allowlist regex.
- Good TDD coverage for GET/POST success and failure cases.
- Correctly preserves the orchestrator model lifecycle with unload in `finally`.
- Mirrors the CLI report sequence, including shock pre-seeding.
- Router registration and `app.state.report_task` wiring are explicitly covered.
- The 503/409/404 error shapes follow existing route conventions.

**Concerns**

- **MEDIUM:** Background task exceptions are re-raised but not observed by the route layer. A failed task may produce "Task exception was never retrieved," while the frontend polls until timeout with no failure signal.
- **MEDIUM:** `Path.exists()` and `Path.stat()` are synchronous filesystem calls inside async endpoints. Small files make this low practical risk, but it violates the project's "no blocking I/O on the main event loop" constraint.
- **MEDIUM:** The phase guard uses current `state_store.snapshot().phase == COMPLETE`. After a backend restart, a completed cycle may exist in Neo4j but the in-memory phase will be `idle`, blocking web generation.
- **LOW/MEDIUM:** The in-progress guard is global, not per cycle — acceptable for the current UI but doesn't exactly match the "already running for this cycle" behavior.
- **LOW:** `REPORTS_DIR = Path("reports")` depends on uvicorn process working directory — fragile if launch context changes.
- **LOW:** Planning text alternates between `ReactEngine` and `ReportEngine`; the repo uses `ReportEngine`. The executable plan uses the right class, but naming drift can confuse implementers.

**Suggestions**

- Add a `task.add_done_callback(...)` that consumes/logs exceptions and optionally stores `app.state.report_generation_error[cycle_id]`.
- Use `aiofiles.os.path.exists` / `aiofiles.os.stat`, or wrap stat calls with `asyncio.to_thread`.
- Store `app.state.report_task_cycle_id` alongside `report_task`; return 409 only when the active task is for the same cycle.
- Consider validating "completed cycle exists" from Neo4j instead of only checking in-memory phase, or explicitly document that web generation only works immediately after an in-session completion.
- Centralize report path construction in one helper to avoid CLI/web drift later.

**Risk Assessment: MEDIUM**
The backend plan should achieve the required API behavior, but async filesystem calls, background task error handling, and in-memory phase coupling are meaningful risks.

---

## Plan 02: Frontend

**Summary**
Plan 02 has the right overall shape: ControlBar trigger, App-level modal mount, client-side markdown rendering with DOMPurify, polling, cleanup on unmount, and a thorough manual verification checkpoint. The largest issue is a state-machine bug: during generation, a 404 poll response changes the UI back to `empty`, stopping the "Generating report..." state even though the backend task is still running.

**Strengths**

- Correctly follows the existing `CyclePicker.vue` modal pattern.
- Good XSS defense: `marked.parse()` output is sanitized before `v-html`.
- Handles 202, 404, 409, and 503 cases explicitly.
- Includes polling cleanup on unmount, preventing stale intervals.
- Identifies and fixes the existing ControlBar branch-ordering issue.
- Keeps the implementation additive and isolated to minimal files.
- The 10-minute polling cap is sensible for local model generation.

**Concerns**

- **HIGH:** `loadReport()` sets `viewState = 'empty'` on 404 even while polling. After the first 3-second poll, the spinner disappears and the Generate button re-enables — a direct functional failure of success criterion 4.
- **MEDIUM:** D-09 says resolve with `GET /api/replay/cycles?limit=1`, but the existing backend route may not support `limit` — the component fetches all cycles. Small cost but a contract mismatch.
- **MEDIUM:** The Report button is visible only when `snapshot.phase === 'complete'`. After page reload, backend restart, or replay mode, existing reports may be inaccessible.
- **MEDIUM:** `marked@18` requires Node 20 per research notes, but the frontend package does not declare an engine. This can break installs on Node 18 environments.
- **LOW/MEDIUM:** The XSS manual test is not executable as written — a synthetic report file isn't selectable unless represented as a completed cycle.
- **LOW:** `viewState` mixes content state and generation state. Regenerating hides the current rendered report and shows "No report generated yet," which is misleading.

**Suggestions**

- Split state into `loadState`/`hasReport` plus `isGenerating`, or change 404 handling so polling keeps `viewState = 'generating'` while a generation is active.
- Call `loadReport()` immediately after 202 before starting the 3-second interval; continue polling if still 404.
- Either add `limit` support to `/api/replay/cycles` or update D-09 to state the frontend fetches the full list and selects index 0.
- Keep the previous report visible during regeneration — only change the footer/status.
- Replace the XSS checkpoint with: "overwrite `reports/{actual_cycle_id}_report.md` for the latest completed cycle, then reload the modal."

**Risk Assessment: MEDIUM-HIGH**
The frontend plan is close, but the polling state bug is a direct functional failure of success criterion 4. Once fixed, risk drops to medium.

---

## Consensus Summary

Phase 36 reviewed by 2 independent AI systems (Gemini, Codex). Both confirm the architecture is sound and the backend plan is well-grounded in existing patterns.

### Agreed Strengths

- Pattern reuse from `CyclePicker.vue`, `interview.py`, `replay.py` minimizes risk
- `ReportEngine`/`ReportAssembler`/`write_report`/`write_sentinel` reuse — zero duplication
- Orchestrator model lifecycle managed correctly with `finally` unload
- `cycle_id` path-traversal guard via allowlist regex — explicit security
- DOMPurify XSS mitigation before `v-html` rendering
- Polling cleanup on `onUnmounted` prevents memory leaks
- TDD approach for backend with 10 specific test cases

### Agreed Concerns

1. **Atomic file write race (LOW, both):** `write_report()` writes directly to the destination. A poll tick landing during the write window could return a partial file. Fix: write to `.tmp` then rename atomically.
2. **Polling state bug (HIGH, Codex):** `loadReport()` sets `viewState = 'empty'` on 404 even during active generation — the spinner disappears after the first poll, and the Generate button re-enables. This is a direct failure of success criterion 4 and must be fixed before execution.
3. **Async blocking I/O (MEDIUM, Codex):** `Path.exists()` / `Path.stat()` are sync calls inside async endpoints — violates CLAUDE.md's "no blocking I/O on event loop" constraint. Fix: use `aiofiles.os.path.exists` / `asyncio.to_thread`.

### Divergent Views

- **Overall risk level:** Gemini rates LOW (APPROVED), Codex rates MEDIUM/MEDIUM-HIGH — gap driven by the polling state bug and async I/O concern that Gemini did not identify. Codex's MEDIUM-HIGH reflects the functional bug in criterion 4; Gemini's LOW reflects the architectural soundness once bugs are addressed.
- **Backend restart scenario:** Codex flags that web generation is blocked after restart (in-memory phase reset to `idle` while cycle exists in Neo4j) — Gemini does not mention this. The existing context marks this as out-of-scope for v1 but worth documenting.
