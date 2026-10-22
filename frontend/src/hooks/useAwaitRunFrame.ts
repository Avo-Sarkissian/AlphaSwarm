// The gap between "POST /api/simulate/start answered" and "the frame shows the
// run". The frame keeps reading idle or complete until run_simulation reaches
// SEEDING and the next 5 Hz frame lands, so for a moment Run would be enabled
// again and a second click would get 409 simulation_already_running
// (docs/DECISIONS.md#f-33). arm() starts the wait after a successful start; it
// ends at the next lifecycle change, or after AWAIT_RUN_FRAME_MS when no run
// frame arrives (a run that fails before SEEDING).
import { useCallback, useEffect, useState } from 'react';
import type { Lifecycle } from '../lib/lifecycle';

export const AWAIT_RUN_FRAME_MS = 10_000;

interface WaitState {
  /** The lifecycle of the last render. */
  seen: Lifecycle;
  /** Lifecycle changes seen so far. */
  changes: number;
  /** `changes` when arm() ran, or null when not armed. */
  armedAt: number | null;
}

export function useAwaitRunFrame(lifecycle: Lifecycle): { awaiting: boolean; arm: () => void } {
  const [wait, setWait] = useState<WaitState>({ seen: lifecycle, changes: 0, armedAt: null });
  if (wait.seen !== lifecycle) {
    // Count the change while rendering, so the frame that shows the run ends
    // the wait in the same render.
    setWait((w) => ({ ...w, seen: lifecycle, changes: w.changes + 1 }));
  }

  const { armedAt } = wait;
  useEffect(() => {
    if (armedAt === null) return;
    const timer = setTimeout(
      () => setWait((w) => (w.armedAt === armedAt ? { ...w, armedAt: null } : w)),
      AWAIT_RUN_FRAME_MS,
    );
    return () => clearTimeout(timer);
  }, [armedAt]);

  const arm = useCallback(() => setWait((w) => ({ ...w, armedAt: w.changes })), []);
  // A start answered after the run already reached the frame has nothing to wait for.
  const atRest = lifecycle === 'idle' || lifecycle === 'complete';
  return { awaiting: atRest && armedAt !== null && armedAt === wait.changes, arm };
}
