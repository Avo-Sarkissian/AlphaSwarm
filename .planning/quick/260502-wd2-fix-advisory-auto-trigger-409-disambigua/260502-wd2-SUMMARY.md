---
phase: quick-260502-wd2
plan: 01
subsystem: ui
tags: [react, typescript, advisory, error-handling, idempotency]

# Dependency graph
requires:
  - phase: 41.1-10
    provides: useAdvisoryAutoTrigger hook + module-level cycleId registry (NR-7/NR-8)
provides:
  - Disambiguated 409 handling in useAdvisoryAutoTrigger that distinguishes
    advisory_generation_in_progress (keep mark) from report_generation_in_progress
    or unknown (clear mark + structured warn)
affects: [advisory-modal, taskbanner, report-modal, orchestrator-lock-flows]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Backend 409 disambiguation by parsing ApiError.body.error discriminator on the frontend"
    - "Fail-open mark clearance for unknown 409 codes (prefer recoverable manual retry over silent stuck state)"

key-files:
  created: []
  modified:
    - frontend/src/hooks/useAdvisoryAutoTrigger.ts

key-decisions:
  - "Unknown / missing 409 error code falls into the same branch as report_generation_in_progress (clear mark) to avoid silent lockouts"
  - "Single .catch callback with nested 409 sub-branches retained — no .then/.catch chaining or async/await refactor"

patterns-established:
  - "Pattern: when backend returns the same HTTP status for distinct domain conditions, the FE catch must narrow ApiError + read body.error before deciding mark/state side effects"

requirements-completed: [QUICK-260502-WD2-01]

# Metrics
duration: 1m
completed: 2026-05-03
---

# Quick Task 260502-wd2: Advisory Auto-Trigger 409 Disambiguation Summary

**Auto-trigger 409 in useAdvisoryAutoTrigger now branches on ApiError.body.error so a report-in-flight 409 clears the cycleId mark instead of permanently locking the user out of advisory generation.**

## Performance

- **Duration:** ~1m (54s)
- **Started:** 2026-05-03T03:20:25Z
- **Completed:** 2026-05-03T03:21:19Z
- **Tasks:** 2 (1 code task + 1 deferred human-verify checkpoint)
- **Files modified:** 1

## Accomplishments

- 409 catch branch in `advisoryGenerate(cycleId).catch(...)` now reads `ApiError.body.error`:
  - `advisory_generation_in_progress` → keep mark, return (existing happy path preserved).
  - `report_generation_in_progress` → delete mark + structured warn `[advisory-auto-trigger] 409 cleared mark { cycleId, error: "report_generation_in_progress" }`.
  - Unknown / missing error code → fail-open: delete mark + warn with `error: "unknown"`.
- Non-409 catch path unchanged (delete mark + `[advisory-auto-trigger] dispatch failed` warn).
- Successful 202 path unchanged (mark stays; modal polling picks up the result).
- File-header docstring layer #4 rewritten so future readers cannot re-collapse all 409s into "treated as success" without seeing the explanatory comment about the orchestrator-lock interaction.

## Task Commits

Each task was committed atomically:

1. **Task 1: Disambiguate 409 in advisoryGenerate().catch by parsing ApiError.body.error** — `bd02208` (fix)
2. **Task 2: Manual smoke — report-in-flight no longer locks advisory** — DEFERRED to human UAT per orchestrator constraint (no commit; Task 1 TypeScript check passed and gates the deferral).

## Files Created/Modified

- `frontend/src/hooks/useAdvisoryAutoTrigger.ts` — Replaced the catch callback body with a 409-disambiguating branch (synthesis-in-flight keeps mark; report-in-flight or unknown clears mark + warns). Updated header docstring layer #4 to document the new contract. No new imports, no signature changes, no other files touched.

## Before / After Diff (Catch Block)

**Before:**

```typescript
advisoryGenerate(cycleId).catch((e: unknown) => {
  if (e instanceof ApiError && e.status === 409) {
    // Already running (manual open beat us, or report still in flight).
    // Polling in the modal will pick up the result. Keep the cycleId
    // marked so manual opens are also no-ops.
    return;
  }
  // 503 / 4xx other / network: drop the mark so manual open can retry.
  advisoryAutoTriggered.delete(cycleId);
  // eslint-disable-next-line no-console
  console.warn('[advisory-auto-trigger] dispatch failed', e);
});
```

**After:**

```typescript
advisoryGenerate(cycleId).catch((e: unknown) => {
  if (e instanceof ApiError && e.status === 409) {
    // Backend `POST /api/advisory/{cycle_id}` returns 409 for TWO distinct
    // cases (see backend/api/advisory.py). Disambiguate via body.error so a
    // report-in-flight 409 doesn't permanently lock the cycleId out of
    // advisory generation (manual Advisory open also reads
    // hasAdvisoryBeenTriggered and would no-op if we kept the mark).
    const code =
      typeof e.body === 'object' && e.body !== null
        ? (e.body as { error?: unknown }).error
        : undefined;

    if (code === 'advisory_generation_in_progress') {
      // Synthesis already running (manual open beat us). Polling in the
      // modal will pick up the result. Keep the cycleId marked so manual
      // opens are also no-ops.
      return;
    }

    // 'report_generation_in_progress' OR unknown/missing error code:
    // clear the mark so the user's manual Advisory open can retry the
    // POST once the report run releases the orchestrator lock.
    advisoryAutoTriggered.delete(cycleId);
    // eslint-disable-next-line no-console
    console.warn(
      '[advisory-auto-trigger] 409 cleared mark',
      { cycleId, error: code ?? 'unknown' },
    );
    return;
  }
  // 503 / 4xx other / network: drop the mark so manual open can retry.
  advisoryAutoTriggered.delete(cycleId);
  // eslint-disable-next-line no-console
  console.warn('[advisory-auto-trigger] dispatch failed', e);
});
```

## Decisions Made

- **Body parse uses `typeof === 'object' && e.body !== null` guard before casting to `{ error?: unknown }`.** This handles the `safeBody()` contract (parsed JSON when content-type is JSON, else `string | null`) without throwing when the backend returns a non-JSON 409 (e.g., proxy / generic gateway error masquerading as 409). Unknown codes fall into the fail-open branch.
- **Single `.catch` with nested 409 sub-branches** instead of restructuring to `.then/.catch` chaining or `async/await` inside the effect — preserves the surrounding effect shape and keeps the registry side effects co-located.
- **No new logging key for the unknown branch** — both `report_generation_in_progress` and unknown codes share the `[advisory-auto-trigger] 409 cleared mark` warn line and the `error` field tells observers which sub-case fired (`"unknown"` vs the actual backend code). Halves the log surface vs two separate warns and keeps grep-by-prefix useful.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Adapted verification command to actual frontend npm scripts**
- **Found during:** Task 1 verification step
- **Issue:** Plan specified `cd frontend && npm run typecheck && npm run lint -- src/hooks/useAdvisoryAutoTrigger.ts`. The frontend `package.json` exposes `dev`, `build`, `preview`, and `check` (which is `tsc -b --noEmit`); there is no `typecheck` script and no `lint` script (no ESLint configured in the repo).
- **Fix:** Ran `cd frontend && npm run check` — semantically identical to the requested typecheck (same `tsc -b --noEmit` invocation). Skipped the `lint` step because no linter is wired up in this project (would have required adding ESLint + config, which is architectural — Rule 4 — and out of scope for a single-line catch-block fix).
- **Files modified:** None (verification-only deviation).
- **Verification:** `npm run check` exits 0 with no errors.
- **Committed in:** N/A (no code change).

---

**Total deviations:** 1 auto-fixed (1 blocking — verification command name)
**Impact on plan:** Zero. Verification is functionally equivalent (same tsc invocation). Lint skip is documented; the file is short, was code-reviewed against the plan's exact replacement text, and contains no patterns that would trigger a typical lint rule.

## Issues Encountered

None.

## User Setup Required

None.

## Manual Smoke (Task 2 — DEFERRED)

Per orchestrator constraint, Task 2 (`checkpoint:human-verify`) is marked complete after Task 1 passed `npm run check`. The smoke test below is **deferred to human UAT** and not blocking this plan's completion:

1. Start the stack (Ollama + backend + frontend dev server).
2. Run a full simulation cycle to FINAL.
3. Click the **Report** button immediately on cycle complete (NOT Advisory) so the report POST grabs the orchestrator lock first.
4. Confirm browser console shows: `[advisory-auto-trigger] 409 cleared mark { cycleId: "...", error: "report_generation_in_progress" }`.
5. After the report modal renders (lock releases), click the **Advisory** button. Verify a fresh `POST /api/advisory/{cycle_id}` fires (Network tab → 202) and synthesis renders within ~30s.
6. Regression: run a second cycle, click Advisory FIRST. Verify exactly ONE POST per cycleId (the `advisory_generation_in_progress` 409 path keeps the mark — auto + manual collapse to one dispatch).

## Next Phase Readiness

- Hook fix is live for the next interactive UAT pass against Phase 41.1's wired Advisory + Report modals.
- No new dependencies, no signature changes — call sites (App.tsx via `useAdvisoryAutoTrigger()`, AdvisoryModal/TaskBanner via `hasAdvisoryBeenTriggered` / `unmarkAdvisoryTriggered`) are unaffected.
- No follow-up backlog items spawned by this fix.

## Self-Check: PASSED

- FOUND: `frontend/src/hooks/useAdvisoryAutoTrigger.ts` (modified, contains `advisory_generation_in_progress` discriminator at lines 24 + 92)
- FOUND: `.planning/quick/260502-wd2-fix-advisory-auto-trigger-409-disambigua/260502-wd2-SUMMARY.md`
- FOUND: commit `bd02208` (`fix(quick-260502-wd2-01): disambiguate advisory auto-trigger 409 by body.error`)
- TypeScript: `npm run check` exits 0

---
*Phase: quick-260502-wd2*
*Completed: 2026-05-03*
