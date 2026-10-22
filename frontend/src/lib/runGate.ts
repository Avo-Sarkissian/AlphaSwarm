// Decision behind the Run button (hooks/useRunGate.tsx). Local runs start at once;
// cloud or mixed runs, and runs whose cost estimate failed, wait for an explicit
// confirmation, so a cloud run never starts without a chance to cancel.
import type { RunEstimate } from '../api/settings';

export type GateDecision =
  | { action: 'start_direct' }
  | { action: 'show_modal'; estimate: RunEstimate | null };

export function gateDecide(estimate: RunEstimate | null, estimateFailed: boolean): GateDecision {
  if (estimateFailed || estimate === null) return { action: 'show_modal', estimate: null };
  if (estimate.mode === 'local') return { action: 'start_direct' };
  return { action: 'show_modal', estimate };
}
