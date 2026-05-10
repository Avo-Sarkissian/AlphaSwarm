---
phase: quick-260510-fdo
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - frontend/src/components/panels.jsx
  - frontend/src/components/v2.tsx
  - frontend/src/hooks/useCurrentCycle.ts
autonomous: true
requirements:
  - W2-POLISH-01  # bracket-bars empty state
  - W2-POLISH-02  # AdvisoryV2 polling-exhausted error UI
  - W2-POLISH-03  # CycleHistory / cycleId polling debounce
must_haves:
  truths:
    - "When summaries array is empty OR all entries have total=0, BracketList shows the same `panel-empty` placeholder used by RationaleFeed (no flat palette chips, no `0` counts)."
    - "When AdvisoryV2 polling exhausts (1200 attempts × 3s = 60min cap), the modal renders a clear, on-tone message that synthesis can take 25–50 min on M1 Max — NOT a blank pane and NOT a generic `Advisory unavailable: polling timed out…` line."
    - "On a fresh page load, only ONE `GET /api/replay/cycles` request fires within the first 3 seconds — not 8."
    - "All three changes pass `npm run check` (tsc -b --noEmit) and `npm run build` (vite build) without new errors or warnings."
  artifacts:
    - path: "frontend/src/components/panels.jsx"
      provides: "BracketList empty-state guard extended to cover all-zero totals"
      contains: "panel-empty"
    - path: "frontend/src/components/v2.tsx"
      provides: "AdvisoryV2 polling-exhausted render branch"
      contains: "isExhausted"
    - path: "frontend/src/hooks/useCurrentCycle.ts"
      provides: "Module-level singleton dedupe for the /api/replay/cycles poll"
      contains: "subscribers"
  key_links:
    - from: "frontend/src/components/app_v2.tsx"
      to: "BracketList"
      via: "summaries prop derived from useBrackets()"
      pattern: "BracketList summaries=\\{summaries\\}"
    - from: "frontend/src/components/v2.tsx (AdvisoryV2)"
      to: "usePolling"
      via: "polled.error.message string-matches `/polling timed out/`"
      pattern: "polling timed out"
    - from: "frontend/src/hooks/useCurrentCycle.ts"
      to: "/api/replay/cycles"
      via: "module-level singleton interval; multiple consumers subscribe instead of each calling usePolling"
      pattern: "subscribers\\.add"
---

<objective>
Three small, surgical UI polish fixes for the React frontend (Phase 41.6 W2 follow-up). All cosmetic / quality-of-life — no new endpoints, no new features. Each fix is one atomic commit with the `fix(41.6-02): …` prefix.

Purpose: Close the three remaining W2 visual fidelity gaps the user observed before W4 starts:
  1. BracketList still shows palette-colored chips + `0` counts when the backend hasn't emitted agent_states (looks like real data).
  2. AdvisoryV2 modal renders an unhelpful `Advisory unavailable: polling timed out after 1200 attempts` line — or worse, blanks out — when the 60-min poll cap is hit.
  3. `GET /api/replay/cycles` fires 8× in rapid succession on page mount (every `useCurrentCycle()` consumer + every direct `listCycles()` caller + StrictMode double-mount = 8 requests).

Output: 3 modified files, 3 atomic commits, build gates green.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/phases/41.6-ui-revamp-alphaswarm-2-quant-terminal-port-and-wire/41.6-HANDOFF.md
@CLAUDE.md
@frontend/src/components/panels.jsx
@frontend/src/components/v2.tsx
@frontend/src/hooks/useCurrentCycle.ts
@frontend/src/hooks/usePolling.ts
@frontend/src/components/history.tsx
@frontend/src/api/replay.ts
@frontend/src/components/app_v2.tsx
@frontend/src/context/BracketContext.tsx
@frontend/src/context/EdgesContext.tsx
@frontend/src/components/ReportModal.tsx
@frontend/src/api/advisory.ts

<interfaces>
<!-- Key signatures the executor must NOT change. Extracted from codebase. -->

From frontend/src/hooks/usePolling.ts:
```typescript
export interface UsePollingResult<T> {
  data: T | null;
  error: Error | null;   // set to `new Error("polling timed out after N attempts")` on cap hit
  attempt: number;
  loading: boolean;       // data === null && error === null
}
```

From frontend/src/components/panels.jsx (current):
```javascript
export function BracketList({ summaries, onClick }) {
  if (!summaries || summaries.length === 0) {
    return <div className="panel-empty">no brackets yet — waiting for first frame</div>;
  }
  // ... renders bracket-row + bracket-bar with bp/sp/hp = count / max(1, total)
}
```
Existing empty-state CSS class `.panel-empty` is defined at styles.css:768. Reuse it — do NOT introduce a new class.

From frontend/src/hooks/useCurrentCycle.ts (current):
```typescript
export function useCurrentCycle(): { cycleId: string | null; loading: boolean; error: Error | null }
```
Public return shape MUST stay byte-identical — multiple consumers (`EdgesContext.tsx:23`, `ReportModal.tsx:37`, `v2.tsx:616`) destructure `cycleId`, `loading`, `error`.

From frontend/src/api/advisory.ts (line 1-7 — DO NOT TOUCH):
```typescript
// Backend auto-fires advisory synthesis on FINAL round (per quick task 260507-19f).
// DO NOT re-introduce advisoryTrigger() POST here — re-creates ~17GB orchestrator-load footgun.
```
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: BracketList empty-state guard for all-zero totals</name>
  <files>frontend/src/components/panels.jsx</files>
  <action>
Extend the existing `BracketList` empty-state guard at `panels.jsx:7-9` so it ALSO triggers when `summaries` is non-empty but every entry has `total === 0` (the case where backend has shipped a frame but `agent_states` is still empty — see 41.6-HANDOFF.md "Critical — backend issue").

Current code:
```javascript
if (!summaries || summaries.length === 0) {
  return <div className="panel-empty">no brackets yet — waiting for first frame</div>;
}
```

New code (replace the guard):
```javascript
const isEmpty =
  !summaries ||
  summaries.length === 0 ||
  summaries.every(s => (s?.total ?? 0) === 0);
if (isEmpty) {
  return <div className="panel-empty">no brackets yet — waiting for first frame</div>;
}
```

Hard rules:
- `panels.jsx` is `.jsx` — NO TypeScript syntax (no `: number`, no `as`, no `?:` for type annotations). The `?.` optional-chaining and `??` nullish-coalescing operators are pure JS and ARE allowed.
- Reuse existing `panel-empty` CSS class (styles.css:768). Do NOT add a new class or design literal.
- Keep the placeholder copy "no brackets yet — waiting for first frame" identical for visual parity with the existing empty branch.
- Do NOT touch `RationaleFeed`, `KpiStrip`, or `ConsensusRing` in this task.

After the edit:
1. `cd frontend && npm run check` — must be green.
2. `cd frontend && npm run build` — must be green.
3. Commit:
   ```
   git -C "/Users/avosarkissian/Documents/VS Code/AlphaSwarm" add frontend/src/components/panels.jsx
   git -C "/Users/avosarkissian/Documents/VS Code/AlphaSwarm" commit -m "fix(41.6-02): BracketList empty state covers all-zero totals"
   ```
  </action>
  <verify>
    <automated>cd "/Users/avosarkissian/Documents/VS Code/AlphaSwarm/frontend" && npm run check && npm run build</automated>
  </verify>
  <done>
- `BracketList` returns the `panel-empty` placeholder when (a) summaries is empty/null OR (b) every summary has `total === 0`.
- `panels.jsx` contains no TypeScript syntax (grep `: number\|: string\| as ` returns no NEW hits in this file).
- `npm run check` and `npm run build` both green.
- One commit landed: `fix(41.6-02): BracketList empty state covers all-zero totals`.
  </done>
</task>

<task type="auto">
  <name>Task 2: AdvisoryV2 polling-exhausted error UI</name>
  <files>frontend/src/components/v2.tsx</files>
  <action>
Add an explicit "polling exhausted" render branch in `AdvisoryV2` (`v2.tsx:615+`) so the 60-min cap (1200 attempts × 3000ms set at lines 633-638) surfaces as an honest, user-tone message instead of the current generic `Advisory unavailable: polling timed out after 1200 attempts` line at lines 772-776.

The `usePolling` hook (hooks/usePolling.ts:55-61) sets `error = new Error("polling timed out after ${maxAttempts} attempts")` when the cap is hit. Detect this string match.

Steps:

1. Just below the existing `hadError` derivation (around line 640):
   ```typescript
   const hadError = polled.error !== null;
   ```
   add:
   ```typescript
   // Detect cap-hit specifically — usePolling sets this exact message at hooks/usePolling.ts:61.
   const isExhausted =
     polled.error !== null && /polling timed out/i.test(polled.error.message);
   ```

2. In the modal body block (currently lines 762-783), REPLACE the existing four mutually-exclusive empty-state cards with this ordered cascade. The new exhausted branch must come BEFORE the generic `hadError` branch so it short-circuits the generic error message:
   ```tsx
   {!cycleId && (
     <div className="advisory-card">
       <div className="label">No completed cycle to advise on.</div>
     </div>
   )}
   {cycleId && polled.loading && !report && !hadError && (
     <div className="advisory-card">
       <div className="label">Loading advisory…</div>
     </div>
   )}
   {cycleId && isExhausted && !report && (
     <div className="advisory-card">
       <div className="label" style={{ marginBottom: 8 }}>
         Advisory not yet generated
       </div>
       <div style={{ color: 'var(--text-2)', fontSize: 13, lineHeight: 1.6 }}>
         Synthesis can take 25–50 min on M1 Max (post-R3 narrative + worker→orchestrator
         model swap + advisory pass). Check back later — backend auto-fires on cycle complete.
       </div>
     </div>
   )}
   {cycleId && hadError && !isExhausted && !report && (
     <div className="advisory-card" style={{ color: 'var(--sell)' }}>
       Advisory unavailable: {polled.error?.message ?? 'unknown error'}
     </div>
   )}
   {cycleId && !polled.loading && !report && !hadError && (
     <div className="advisory-card">
       <div className="label">
         No advisory yet for this cycle (auto-triggered on cycle complete).
       </div>
     </div>
   )}
   ```

Hard rules:
- `v2.tsx` is `.tsx` — TypeScript syntax is fine. Stay TypeScript per codex HIGH-1.
- Use ONLY existing CSS classes (`advisory-card`, `label`) and existing CSS vars (`var(--text-2)`, `var(--sell)`). No new class. No new design literal.
- DO NOT add an `advisoryTrigger()` POST or any new endpoint — `frontend/src/api/advisory.ts:1-7` explicitly forbids it. Pure render branch only.
- Do NOT change the `usePolling` cap (1200 attempts) or interval (3000ms). Those were locked in commit `bd682df` per the inline comment.
- The `isExhausted` regex must match the EXACT message format produced by `hooks/usePolling.ts:61` (`polling timed out after N attempts`). Use case-insensitive flag for safety.
- The branch ordering matters: `isExhausted` MUST short-circuit the generic `hadError` branch by including `!isExhausted` in the generic guard.

After the edit:
1. `cd frontend && npm run check` — must be green (no type errors on the new `isExhausted` const).
2. `cd frontend && npm run build` — must be green.
3. Commit:
   ```
   git -C "/Users/avosarkissian/Documents/VS Code/AlphaSwarm" add frontend/src/components/v2.tsx
   git -C "/Users/avosarkissian/Documents/VS Code/AlphaSwarm" commit -m "fix(41.6-02): AdvisoryV2 polling-exhausted error UI"
   ```
  </action>
  <verify>
    <automated>cd "/Users/avosarkissian/Documents/VS Code/AlphaSwarm/frontend" && npm run check && npm run build</automated>
  </verify>
  <done>
- `AdvisoryV2` renders the new "Advisory not yet generated. Synthesis can take 25–50 min on M1 Max…" card when `polled.error.message` matches `/polling timed out/i`.
- The generic `hadError` branch is gated by `!isExhausted` so it does not fire on cap-hit.
- `frontend/src/api/advisory.ts` is unchanged — no `advisoryTrigger` POST reintroduced (`grep -n advisoryTrigger frontend/src/components/v2.tsx` returns no hits).
- `npm run check` and `npm run build` both green.
- One commit landed: `fix(41.6-02): AdvisoryV2 polling-exhausted error UI`.
  </done>
</task>

<task type="auto">
  <name>Task 3: useCurrentCycle module-level singleton dedupe</name>
  <files>frontend/src/hooks/useCurrentCycle.ts</files>
  <action>
Convert `useCurrentCycle` from a per-consumer `usePolling` invocation into a module-level singleton with a fan-out subscription. Root cause of the 8× rapid-succession `/api/replay/cycles` requests on mount:

  - 4 consumers each call `useCurrentCycle()` independently:
    - `frontend/src/context/EdgesContext.tsx:23`
    - `frontend/src/components/ReportModal.tsx:37`
    - `frontend/src/components/v2.tsx:616` (AdvisoryV2)
    - (any future consumers)
  - Each invocation creates a NEW `usePolling` instance with its own `useEffect` that fires `tick()` IMMEDIATELY on mount (`hooks/usePolling.ts:52`).
  - React StrictMode double-mounts every consumer in dev → 2× per consumer.
  - Plus `history.tsx` and `modals.jsx` each call `listCycles()` directly on mount.
  - 4 hook consumers × 2 (StrictMode) = 8 requests.

Fix: move the polling loop to a module-level singleton; the hook just subscribes to the cached value.

REPLACE the entire body of `frontend/src/hooks/useCurrentCycle.ts` with:

```typescript
import { useEffect, useState } from 'react';
import { apiFetch } from '../api/client';
import type { CycleMeta } from '../types';

// GET /api/simulate/status is NOT implemented. Derive cycleId from the first
// entry of /api/replay/cycles (newest first). Poll every 5s.
//
// Module-level singleton: ONE interval shared by all consumers. Replaces the
// previous per-consumer usePolling() approach (each consumer was creating its
// own interval AND firing an immediate tick on mount, producing 8x rapid
// requests with 4 consumers under React StrictMode double-mount).
//
// Public return shape preserved byte-identical for EdgesContext, ReportModal,
// AdvisoryV2 (the existing destructure consumers).

interface CycleState {
  cycleId: string | null;
  loading: boolean;
  error: Error | null;
}

const INTERVAL_MS = 5000;

let state: CycleState = { cycleId: null, loading: true, error: null };
const subscribers = new Set<(s: CycleState) => void>();
let intervalId: ReturnType<typeof setInterval> | null = null;
let inFlight: Promise<void> | null = null;

function emit() {
  for (const fn of subscribers) fn(state);
}

async function tick() {
  // Dedupe in-flight requests — guards against the immediate tick + interval
  // tick double-fire if a consumer subscribes mid-flight.
  if (inFlight) return inFlight;
  inFlight = (async () => {
    try {
      const data = await apiFetch<{ cycles: CycleMeta[] }>('/api/replay/cycles');
      state = {
        cycleId: data?.cycles?.[0]?.cycle_id ?? null,
        loading: false,
        error: null,
      };
    } catch (e: unknown) {
      state = {
        cycleId: state.cycleId,
        loading: false,
        error: e instanceof Error ? e : new Error(String(e)),
      };
    } finally {
      emit();
      inFlight = null;
    }
  })();
  return inFlight;
}

function ensureLoop() {
  if (intervalId !== null) return;
  // Immediate first fetch ONCE per interval lifecycle.
  void tick();
  intervalId = setInterval(() => void tick(), INTERVAL_MS);
}

function teardownIfIdle() {
  if (subscribers.size > 0) return;
  if (intervalId !== null) {
    clearInterval(intervalId);
    intervalId = null;
  }
}

export function useCurrentCycle() {
  const [snap, setSnap] = useState<CycleState>(state);

  useEffect(() => {
    subscribers.add(setSnap);
    ensureLoop();
    // Sync to the latest state at subscribe time so a late mount does not show
    // stale `loading: true` after the first tick already resolved.
    setSnap(state);
    return () => {
      subscribers.delete(setSnap);
      teardownIfIdle();
    };
  }, []);

  return {
    cycleId: snap.cycleId,
    loading: snap.loading,
    error: snap.error,
  };
}
```

Hard rules:
- Public return shape stays `{ cycleId, loading, error }` — every existing consumer destructures these three fields. Do NOT add or rename fields.
- Module-level state means HMR re-imports MAY duplicate the singleton in dev; that is acceptable and matches the existing `usePolling` HMR behaviour. Do not over-engineer with `globalThis` registries.
- Do NOT modify `hooks/usePolling.ts` — it is still used by `useCurrentCycle`'s siblings (AdvisoryV2 polling). This task touches `useCurrentCycle.ts` ONLY.
- Do NOT touch `history.tsx` or `modals.jsx` — they call `listCycles()` directly (one-shot, not polling) and are correct as-is. The 8x repro included those one-shot calls; deduping the hook is enough to bring the count down to 1 (singleton hook) + 1 (history one-shot if open) + 1 (modals one-shot if open) ≤ 3, well under the observed 8.
- The `inFlight` Promise dedupe guards against StrictMode double-mount: the second mount calls `ensureLoop()` (no-op, interval already running) and `setSnap(state)` (cheap sync). No second network request.
- Keep the comment block at the top documenting why this is a singleton — future maintainers must know NOT to revert to per-consumer `usePolling`.

After the edit:
1. `cd frontend && npm run check` — must be green. Pay attention to whether the existing `import { usePolling } from './usePolling'` is no longer used; remove if so to avoid `noUnusedLocals` errors.
2. `cd frontend && npm run build` — must be green.
3. Manual smoke (optional, only if backend is up): open browser DevTools Network tab, hard-reload `http://localhost:5173/`, filter by `replay/cycles`. Should see 1 request in the first 3 seconds (down from 8).
4. Commit:
   ```
   git -C "/Users/avosarkissian/Documents/VS Code/AlphaSwarm" add frontend/src/hooks/useCurrentCycle.ts
   git -C "/Users/avosarkissian/Documents/VS Code/AlphaSwarm" commit -m "fix(41.6-02): dedupe useCurrentCycle to a module-level singleton (was 8x replay/cycles on mount)"
   ```
  </action>
  <verify>
    <automated>cd "/Users/avosarkissian/Documents/VS Code/AlphaSwarm/frontend" && npm run check && npm run build</automated>
  </verify>
  <done>
- `useCurrentCycle` returns the same `{ cycleId, loading, error }` shape (no API breakage).
- A single module-level interval is created on first subscribe and torn down when subscriber count reaches 0.
- `inFlight` dedupe prevents StrictMode double-mount from firing a duplicate request.
- All 3 existing consumers (`EdgesContext`, `ReportModal`, `v2.tsx AdvisoryV2`) compile without changes.
- `npm run check` and `npm run build` both green.
- One commit landed: `fix(41.6-02): dedupe useCurrentCycle to a module-level singleton (was 8x replay/cycles on mount)`.
  </done>
</task>

</tasks>

<verification>
After all three tasks land, run the full build gate from the frontend directory:

```
cd "/Users/avosarkissian/Documents/VS Code/AlphaSwarm/frontend"
npm run check
npm run build
```

Both must exit zero. Then verify the 3 commits on master:

```
git -C "/Users/avosarkissian/Documents/VS Code/AlphaSwarm" log --oneline -3
```

Expected (most recent first):
- `fix(41.6-02): dedupe useCurrentCycle to a module-level singleton (was 8x replay/cycles on mount)`
- `fix(41.6-02): AdvisoryV2 polling-exhausted error UI`
- `fix(41.6-02): BracketList empty state covers all-zero totals`

Optional manual smoke (only if user has backend + frontend stack running):
1. Hard-reload `http://localhost:5173/` with DevTools Network tab open + filter `replay/cycles`. ≤ 2 requests in the first 3 seconds.
2. With no agents emitted by backend (current handoff state), Brackets panel shows `panel-empty` placeholder, NOT colored bracket-bar rows with `0` counts.
3. Open Advisory modal on a completed-but-no-advisory cycle, wait until `polled.attempt` ≥ 1200 (or temporarily lower the cap to 5 in v2.tsx and revert before commit if you want to manually drive the branch). The "Advisory not yet generated. Synthesis can take 25–50 min…" card renders.
</verification>

<success_criteria>
- 3 files modified: `panels.jsx`, `v2.tsx`, `useCurrentCycle.ts`. No other files touched.
- 3 atomic commits on master with the `fix(41.6-02): …` prefix.
- `npm run check` and `npm run build` both green after each commit (and at the end).
- No new TypeScript syntax in `panels.jsx` (it stays `.jsx`).
- No new endpoints, no `advisoryTrigger` POST reintroduction, no changes to `frontend/src/api/advisory.ts`.
- No new design-token literals; only existing CSS classes (`panel-empty`, `advisory-card`, `label`) and existing CSS vars (`var(--text-2)`, `var(--sell)`) are used.
- `useCurrentCycle()` public return shape unchanged — existing consumers compile without edits.
- Production grep gates for mocks (`mocks/wire`, `mocks/sources`) are NOT affected by this plan (it does not touch any mock-touching code).
- KR register additions: none (these are surgical bug-fixes, not parity deviations).
</success_criteria>

<output>
After completion, create `.planning/quick/260510-fdo-polish-w2-visual-gaps-bracket-bars-empty/260510-fdo-SUMMARY.md` capturing:
  - 3 commits + their SHAs
  - Build gate status
  - Network-tab observation (if backend was up during smoke)
  - Any deviation notes (none expected — this plan is fully spec'd)
</output>
