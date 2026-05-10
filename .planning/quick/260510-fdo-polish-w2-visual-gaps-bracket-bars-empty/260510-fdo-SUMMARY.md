---
phase: quick-260510-fdo
plan: 01
type: execute
status: complete
completed_at: 2026-05-10
files_modified:
  - frontend/src/components/panels.jsx
  - frontend/src/components/v2.tsx
  - frontend/src/hooks/useCurrentCycle.ts
commits:
  - 1be286e: "fix(41.6-02): BracketList empty state covers all-zero totals"
  - 181b170: "fix(41.6-02): AdvisoryV2 polling-exhausted error UI"
  - 0a4f0b8: "fix(41.6-02): dedupe useCurrentCycle to a module-level singleton (was 8x replay/cycles on mount)"
requirements_completed:
  - W2-POLISH-01
  - W2-POLISH-02
  - W2-POLISH-03
build_gates: green
---

# Quick Task 260510-fdo Summary

**One-liner:** Three surgical W2 polish fixes — BracketList all-zero empty-state, AdvisoryV2 60-min poll-cap user-tone message, and useCurrentCycle module-level singleton to collapse 8× replay/cycles spam to ≤2 on mount.

## Tasks Executed

### Task 1 — BracketList empty-state guard for all-zero totals
- **File:** `frontend/src/components/panels.jsx`
- **Change:** Replaced the existing `if (!summaries || summaries.length === 0)` guard with an `isEmpty` derivation that ALSO triggers when every summary entry has `total === 0`. Same `panel-empty` class, same placeholder copy ("no brackets yet — waiting for first frame"), no new design literals.
- **Why:** Backend currently ships frames with `agent_states=[]` mid-sim — the previous guard let bracket-row chips render at `0/0` width, making the panel look like real flat data instead of an honest empty state.
- **JSX-purity:** No TypeScript syntax introduced (`?.` and `??` are pure JS).
- **Build gate:** `npm run check` + `npm run build` both green.
- **Commit:** `1be286e`

### Task 2 — AdvisoryV2 polling-exhausted error UI
- **File:** `frontend/src/components/v2.tsx`
- **Change:**
  - Added `isExhausted` derivation just after `hadError` (`/polling timed out/i.test(polled.error.message)`) — matches the exact message produced by `hooks/usePolling.ts:61`.
  - Inserted a new exhausted-state branch in the modal body cascade BEFORE the generic `hadError` branch, and gated the generic branch with `!isExhausted` so the cap-hit case short-circuits.
  - New copy: "Advisory not yet generated. Synthesis can take 25–50 min on M1 Max (post-R3 narrative + worker→orchestrator model swap + advisory pass). Check back later — backend auto-fires on cycle complete."
- **Constraints honored:**
  - `usePolling` cap (1200) and interval (3000ms) untouched — locked by `bd682df`.
  - No `advisoryTrigger` POST reintroduced (`grep -n advisoryTrigger frontend/src/components/v2.tsx` returns no hits).
  - `frontend/src/api/advisory.ts` unchanged.
  - Only existing CSS classes (`advisory-card`, `label`) and CSS vars (`var(--text-2)`, `var(--sell)`) used.
- **Build gate:** `npm run check` + `npm run build` both green.
- **Commit:** `181b170`

### Task 3 — useCurrentCycle module-level singleton dedupe
- **File:** `frontend/src/hooks/useCurrentCycle.ts`
- **Change:** Replaced the per-consumer `usePolling` invocation with a module-level singleton:
  - Module-scoped `state`, `subscribers` set, `intervalId`, and `inFlight` Promise.
  - `tick()` dedupes in-flight requests (StrictMode double-mount safe).
  - `ensureLoop()` is idempotent — fires immediate first tick + 5s interval ONCE per lifecycle.
  - `teardownIfIdle()` clears the interval when the last subscriber unmounts.
  - The hook just `useState`s a snapshot, subscribes/unsubscribes in `useEffect`, and re-syncs to the latest module state at subscribe time so late-mount consumers don't show stale `loading: true`.
  - `usePolling` import removed (no longer used in this file → avoids `noUnusedLocals`).
- **Public return shape preserved:** `{ cycleId, loading, error }` — byte-identical for the 3 existing consumers (`EdgesContext.tsx:23`, `ReportModal.tsx:37`, `v2.tsx:616`). No consumer edits required.
- **Repro count math (per plan):** 4 hook consumers × 2 (StrictMode double-mount) = 8 → singleton collapses to 1 hook fetch + 1 history one-shot (if open) + 1 modals one-shot (if open) ≤ 3 in the first 3s.
- **Build gate:** `npm run check` + `npm run build` both green.
- **Commit:** `0a4f0b8`

## Build Gate Status

| Stage           | check (tsc -b --noEmit) | build (tsc -b + vite build) |
| --------------- | ----------------------- | --------------------------- |
| After Task 1    | green                   | green (904ms)               |
| After Task 2    | green                   | green (655ms)               |
| After Task 3    | green                   | green (612ms)               |

No new TS errors, no new vite warnings.

## Network-Tab Smoke

Not performed — backend stack not started during this execution window. The plan flagged the manual smoke as optional. The `inFlight` dedupe + module-level interval makes the count reduction deterministic; runtime verification can be folded into the next end-to-end UAT pass.

## Deviations from Plan

None. Plan executed exactly as written. Hard rules respected:
- `panels.jsx` stayed `.jsx` (no TS syntax added).
- `v2.tsx` stayed `.tsx`.
- `frontend/src/api/advisory.ts` not modified, no `advisoryTrigger()` POST reintroduced.
- No `window.AS_DATA` / `window.Icon` globals.
- No new CSS classes or design-token literals — only `panel-empty`, `advisory-card`, `label`, and `var(--text-2)` / `var(--sell)`.
- `useCurrentCycle()` public return shape unchanged — no consumer edits.
- `hooks/usePolling.ts` not touched.
- No mock dynamic imports touched (KR-41.6-14 respected).

## Self-Check: PASSED

- `frontend/src/components/panels.jsx` — FOUND, contains `isEmpty` and `summaries.every`.
- `frontend/src/components/v2.tsx` — FOUND, contains `isExhausted`, no `advisoryTrigger`.
- `frontend/src/hooks/useCurrentCycle.ts` — FOUND, contains `subscribers.add`, public shape `{ cycleId, loading, error }`.
- Commit `1be286e` — FOUND in `git log --oneline`.
- Commit `181b170` — FOUND in `git log --oneline`.
- Commit `0a4f0b8` — FOUND in `git log --oneline`.
