// useRunGate — shared gate for the Run action across onboarding and app_v2.
//
// Design rationale (Task 20):
//   - LOCAL mode: calls simStartFn immediately, no modal, no extra blocking.
//   - CLOUD / MIXED mode: fetches a cost estimate, shows RunConfirmModal, and
//     only calls simStartFn after the user confirms.
//
// Estimate-failure UX choice:
//   On getEstimate() failure we show the RunConfirmModal with an
//   "estimate unavailable, run anyway?" message instead of proceeding silently.
//   Rationale: a cloud run should never start without giving the user a chance
//   to cancel — a hidden estimate failure that auto-launches could incur
//   unexpected cost. Logging a console.warn is sufficient telemetry; blocking
//   the user on a network error is not acceptable, so the modal still allows
//   Confirm. If the user is confident, they can still run.
import { ReactNode, useState } from 'react';
import { RunConfirmModal } from '../components/run_confirm';
import { getEstimate, RunEstimate } from '../api/settings';

export interface RunGateState {
  /** Call this instead of simStart directly. */
  requestRun: (seed: string) => Promise<void>;
  /** Render this in the component's JSX (null when no modal is needed). */
  modal: ReactNode;
}

/**
 * Wraps a simStartFn with an optional pre-run cost confirmation step.
 *
 * LOCAL mode → simStartFn called immediately, modal is always null.
 * CLOUD/MIXED mode → modal shown with estimate; Confirm → simStartFn called.
 * Estimate failure → modal shown with "estimate unavailable" message.
 */
export function useRunGate(
  simStartFn: (seed: string) => Promise<unknown>,
): RunGateState {
  // null = closed; non-null = modal open with this estimate (or undefined for failed estimate)
  const [pending, setPending] = useState<{
    seed: string;
    estimate: RunEstimate | null;
  } | null>(null);
  const [busy, setBusy] = useState(false);

  const requestRun = async (seed: string): Promise<void> => {
    let estimate: RunEstimate | null = null;
    try {
      estimate = await getEstimate();
    } catch (err) {
      // Estimate failure: show modal with null estimate so user can still cancel.
      // eslint-disable-next-line no-console
      console.warn('[useRunGate] getEstimate failed; showing modal without estimate', err);
      setPending({ seed, estimate: null });
      return;
    }

    if (estimate.mode === 'local') {
      // Local mode: start immediately without a modal.
      await simStartFn(seed);
      return;
    }

    // Cloud or mixed: open confirmation modal.
    setPending({ seed, estimate });
  };

  const handleConfirm = async (): Promise<void> => {
    if (!pending) return;
    setBusy(true);
    try {
      await simStartFn(pending.seed);
    } finally {
      setBusy(false);
      setPending(null);
    }
  };

  const handleCancel = (): void => {
    setPending(null);
  };

  const modal: ReactNode =
    pending !== null ? (
      <RunConfirmModal
        estimate={pending.estimate}
        onConfirm={() => void handleConfirm()}
        onCancel={handleCancel}
        busy={busy}
      />
    ) : null;

  return { requestRun, modal };
}
