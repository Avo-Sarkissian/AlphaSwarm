---
phase: quick-260503-2zp
plan: 01
subsystem: frontend/advisory-auto-trigger
tags: [bugfix, frontend, advisory, retry, NR-9]
requires: []
provides:
  - "dispatchAdvisory(): module-level helper with 503 holdings_unavailable retry-with-backoff"
affects:
  - frontend/src/hooks/useAdvisoryAutoTrigger.ts
tech_stack:
  added: []
  patterns:
    - "Async retry-with-linear-backoff (1.5s/3s/4.5s) for transient 503 races"
key_files:
  created: []
  modified:
    - frontend/src/hooks/useAdvisoryAutoTrigger.ts
decisions:
  - "Linear backoff (1.5s × attempt) chosen over exponential — backend race typically clears in 1-2s; total worst-case wait of 9s is acceptable for a background dispatch"
  - "Helper rethrows non-matching errors so the existing 409 disambiguation + mark-clearing logic in .catch() stays byte-for-byte unchanged"
  - "Helper placed at module scope (not inside hook) so it doesn't re-allocate per render and so retry recursion has a stable identity"
metrics:
  duration: ~5m
  completed: "2026-05-03"
  tasks_completed: 2
  files_changed: 1
requirements:
  - NR-9
---

# Quick Task 260503-2zp: Fix NR-9 Advisory Auto-Trigger 503 Race Summary

**One-liner:** Added retry-with-backoff (3 attempts, 1.5s/3s/4.5s) for 503 `holdings_unavailable` on the advisory auto-trigger path so transient `portfolio_snapshot=None` races no longer surface a user-visible failure.

## What Changed

`frontend/src/hooks/useAdvisoryAutoTrigger.ts`:

1. Added a module-level `dispatchAdvisory(cycleId, attempt = 1)` helper between `unmarkAdvisoryTriggered` and `useAdvisoryAutoTrigger`.
2. Defined `MAX_503_RETRIES = 3` and `RETRY_STEP_MS = 1500` constants alongside the helper.
3. Replaced the single call site `advisoryGenerate(cycleId).catch(...)` inside the hook's `useEffect` with `dispatchAdvisory(cycleId).catch(...)` — the `.catch()` body is byte-for-byte unchanged.

## Retry Policy

| Attempt | Trigger condition                                                                      | Wait before next attempt |
|---------|----------------------------------------------------------------------------------------|--------------------------|
| 1       | initial dispatch                                                                       | 1500 ms (on 503 holdings_unavailable) |
| 2       | retry after 1st 503 holdings_unavailable                                               | 3000 ms (on 503 holdings_unavailable) |
| 3       | retry after 2nd 503 holdings_unavailable                                               | 4500 ms (on 503 holdings_unavailable) |
| 4       | final attempt; any error (including 503 holdings_unavailable) is rethrown to `.catch()` | n/a                      |

Total worst-case backoff before exhaustion: 9.0 seconds (1.5 + 3.0 + 4.5).

Match condition for retry: `e instanceof ApiError && e.status === 503 && (typeof body === 'object' && body !== null && body.error === 'holdings_unavailable')`. All other errors (any other 503 body, any 4xx/5xx, network errors) are rethrown immediately so the existing `.catch()` handler runs.

## 409 Disambiguation Preserved Unchanged

The pre-existing `.catch()` body — including the `'advisory_generation_in_progress'` keep-mark branch and the `'report_generation_in_progress'` / unknown clear-mark branch with its `console.warn('[advisory-auto-trigger] 409 cleared mark', ...)` — is byte-for-byte identical to the pre-edit version. Confirmed via `git diff HEAD~1 HEAD -- frontend/src/hooks/useAdvisoryAutoTrigger.ts` showing only:
- 36-line insertion of the new helper block (lines 60–95)
- One-line replacement: `advisoryGenerate(cycleId).catch(...)` → `dispatchAdvisory(cycleId).catch(...)`

The 503/4xx-other/network fallback comment (`// 503 / 4xx other / network: drop the mark so manual open can retry.`) and the subsequent `delete(cycleId)` + `console.warn('[advisory-auto-trigger] dispatch failed', e)` are unchanged — they remain the correct fallback after retries exhaust.

## Verification

| Check                                            | Result      |
|--------------------------------------------------|-------------|
| `cd frontend && npm run check` (tsc -b --noEmit) | exit 0      |
| `cd frontend && npm run build` (tsc + vite build)| exit 0; 67 modules transformed, built in 585ms |
| `dispatchAdvisory` present at module scope       | yes (line 72) |
| `MAX_503_RETRIES = 3`                            | yes (line 69) |
| `RETRY_STEP_MS = 1500`                           | yes (line 70) |
| `body.error === 'holdings_unavailable'` guard    | yes (line 85) |
| useEffect calls `dispatchAdvisory(cycleId)`      | yes (line 116) |
| `.catch()` body byte-for-byte unchanged          | yes (verified via diff) |
| HEAD commit subject                              | `fix(41.1-NR-9): retry advisory auto-trigger on 503 holdings_unavailable` |
| Commit touches exactly 1 file                    | yes — `frontend/src/hooks/useAdvisoryAutoTrigger.ts` |

## Deviations from Plan

None — plan executed exactly as written.

## Commits

| Task | Description                                                          | SHA       |
|------|----------------------------------------------------------------------|-----------|
| 1+2  | fix(41.1-NR-9): retry advisory auto-trigger on 503 holdings_unavailable | dc40cd3   |

(Tasks 1 and 2 were combined into a single commit per the plan's Task 2 instructions, which specified committing the patched file with one fix commit.)

## Self-Check: PASSED

- File modified: `frontend/src/hooks/useAdvisoryAutoTrigger.ts` — FOUND
- Commit `dc40cd3` — FOUND in `git log`
- Required identifiers (`dispatchAdvisory`, `MAX_503_RETRIES`, `holdings_unavailable`) — all present
- Frontend type-check + build — both exit 0
