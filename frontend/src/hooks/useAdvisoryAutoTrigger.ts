// NR-6 fix: auto-dispatch advisoryGenerate(cycleId) on the FRAME where a
// cycle first transitions to phase='complete' (or 'done').
//
// Why a hook + module-level registry (not inline useEffect in App.tsx):
//   - The de-dup registry must survive AdvisoryModal mount/unmount and any
//     provider re-render. React state would reset on unmount; useRef is
//     scoped to a single component instance. A module-scope Set<string>
//     persists for the lifetime of the bundle (i.e., the browser tab).
//   - AdvisoryModal (frontend/src/components/modals.jsx) reads the same
//     registry to short-circuit its own kick effect, so manual opens after
//     auto-trigger never produce a duplicate POST.
//   - A future plan (Plan 11 connection-state banner) can hook the same
//     registry to surface "advisory queued automatically" affordance
//     without re-deriving cycle state from frames.
//
// Idempotency layers (all required):
//   1. Module-level Set<cycleId> — cross-mount + cross-component de-dup.
//   2. useRef<lastSeenPhase> — only fires on the TRANSITION non-complete
//      → complete; not every FINAL frame (phase stays 'complete' for
//      many frames after the cycle ends).
//   3. Mark BEFORE awaiting POST — synchronous re-renders during the
//      same effect tick can't double-dispatch.
//   4. 409 from POST is treated as success (synthesis already running);
//      registry mark stays so manual opens are also no-ops.
//   5. Non-409 failures clear the mark so the user's manual click can
//      retry the dispatch.
import { useEffect, useRef } from 'react';
import { useConnection } from '../context/ConnectionContext';
import { useCurrentCycle } from './useCurrentCycle';
import { advisoryGenerate } from '../api/advisory';
import { ApiError } from '../api/client';

// Module-level registry: cycles for which advisoryGenerate has been
// dispatched (auto OR manual). Survives modal mount/unmount + provider
// re-renders. Cleared on page reload only.
const advisoryAutoTriggered = new Set<string>();

export function hasAdvisoryBeenTriggered(cycleId: string): boolean {
  return advisoryAutoTriggered.has(cycleId);
}

export function markAdvisoryTriggered(cycleId: string): void {
  advisoryAutoTriggered.add(cycleId);
}

export function useAdvisoryAutoTrigger(): void {
  const { lastFrame } = useConnection();
  const { cycleId } = useCurrentCycle();
  const lastPhaseRef = useRef<string | null>(null);

  useEffect(() => {
    if (!lastFrame || !cycleId) return;
    const phase = lastFrame.phase;
    const wasComplete =
      lastPhaseRef.current === 'complete' || lastPhaseRef.current === 'done';
    const isComplete = phase === 'complete' || phase === 'done';
    lastPhaseRef.current = phase;

    // Only fire on the TRANSITION from non-complete → complete.
    if (!isComplete || wasComplete) return;
    if (advisoryAutoTriggered.has(cycleId)) return;

    // Mark BEFORE dispatch so a synchronous re-render can't double-fire.
    advisoryAutoTriggered.add(cycleId);

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
  }, [lastFrame, cycleId]);
}
