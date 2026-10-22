// useRunGate — the one Run path for onboarding and the dashboard.
//
//   - LOCAL mode: starts at once, no modal.
//   - CLOUD / MIXED mode: shows RunConfirmModal with the cost estimate and
//     starts only on Confirm. When the estimate fails the modal still opens
//     ("estimate unavailable — run anyway?"), so a cloud run never starts
//     without a chance to cancel.
//
// The gate owns simStart. It never rejects: failures become `error` (via
// formatApiError) and every request ends in onSettled(ok) — success, failure
// and cancel alike — so callers can reset their own state.
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { RunConfirmModal } from '../components/run_confirm';
import { getEstimate, type RunEstimate } from '../api/settings';
import { simStart } from '../api/simulation';
import { formatApiError } from '../lib/apiError';
import { gateDecide } from '../lib/runGate';

export interface RunGateOptions {
  onSettled?: (ok: boolean) => void;
}

export interface RunGateState {
  /** Start a run for this seed; the result arrives through error/pending/onSettled. */
  requestRun(seed: string): void;
  /** Render this in the component's JSX (null when no confirmation is open). */
  modal: ReactNode;
  error: string | null;
  pending: boolean;
}

export function useRunGate(opts: RunGateOptions = {}): RunGateState {
  // Latest callbacks for the async flow, refreshed after every render (never
  // written during render).
  const optsRef = useRef(opts);
  useEffect(() => {
    optsRef.current = opts;
  });
  const [confirm, setConfirm] = useState<{ seed: string; estimate: RunEstimate | null } | null>(
    null,
  );
  const [starting, setStarting] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Synchronous re-entrancy guard: `pending` only updates on the next render,
  // so a fast double-click would otherwise start twice in LOCAL mode
  // (docs/DECISIONS.md#f-33).
  const inFlight = useRef(false);

  const settle = useCallback((ok: boolean, failure?: unknown) => {
    inFlight.current = false;
    setPending(false);
    setStarting(false);
    setConfirm(null);
    if (failure !== undefined) setError(formatApiError(failure));
    optsRef.current.onSettled?.(ok);
  }, []);

  const start = useCallback(
    async (seed: string) => {
      setStarting(true);
      try {
        await simStart(seed);
        settle(true);
      } catch (e) {
        settle(false, e);
      }
    },
    [settle],
  );

  const requestRun = useCallback(
    (seed: string) => {
      if (inFlight.current) return;
      inFlight.current = true;
      setPending(true);
      setError(null);
      void (async () => {
        let estimate: RunEstimate | null = null;
        let estimateFailed = false;
        try {
          estimate = await getEstimate();
        } catch {
          estimateFailed = true;
        }
        const decision = gateDecide(estimate, estimateFailed);
        if (decision.action === 'start_direct') {
          await start(seed);
          return;
        }
        setConfirm({ seed, estimate: decision.estimate });
      })();
    },
    [start],
  );

  const modal: ReactNode =
    confirm !== null ? (
      <RunConfirmModal
        estimate={confirm.estimate}
        busy={starting}
        onConfirm={() => void start(confirm.seed)}
        onCancel={() => settle(false)}
      />
    ) : null;

  return { requestRun, modal, error, pending };
}
