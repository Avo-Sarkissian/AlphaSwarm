// Run-gate decision used by useRunGate (src/lib/runGate.ts).
import { describe, expect, it } from 'vitest';
import type { RunEstimate } from '../../api/settings';
import { gateDecide } from '../../lib/runGate';

const estimate = (mode: RunEstimate['mode']): RunEstimate => ({
  calls: 300,
  low_usd: mode === 'local' ? '0.00' : '0.12',
  high_usd: mode === 'local' ? '0.00' : '0.45',
  mode,
});

describe('gateDecide', () => {
  it('starts a local run directly', () => {
    expect(gateDecide(estimate('local'), false)).toEqual({ action: 'start_direct' });
  });

  it.each(['cloud', 'mixed'] as const)('asks for confirmation in %s mode', (mode) => {
    expect(gateDecide(estimate(mode), false)).toEqual({
      action: 'show_modal',
      estimate: estimate(mode),
    });
  });

  it('asks for confirmation without an estimate when the estimate failed', () => {
    expect(gateDecide(null, true)).toEqual({ action: 'show_modal', estimate: null });
  });

  it('never starts directly after a failed estimate, even with a stale local estimate', () => {
    expect(gateDecide(estimate('local'), true)).toEqual({ action: 'show_modal', estimate: null });
  });

  it('asks for confirmation when no estimate is available', () => {
    expect(gateDecide(null, false)).toEqual({ action: 'show_modal', estimate: null });
  });
});
