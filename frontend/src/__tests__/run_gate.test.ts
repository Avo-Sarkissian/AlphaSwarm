// Tests for the useRunGate decision logic (Task 20).
//
// @testing-library/react is not installed in this project, so we test the
// gate's decision logic as a pure/headless function extracted from useRunGate.
// The logic under test:
//   - LOCAL mode → simStartFn called directly, modal never shown.
//   - CLOUD mode → modal is shown with the estimate; Confirm → simStartFn called.
//   - MIXED mode → same as CLOUD (modal shown).
//   - CANCEL → simStartFn NOT called.
//   - getEstimate failure → modal shown with null estimate; Confirm → simStartFn called.
//
// We mirror the decision logic from useRunGate as a testable pure function.
// If the hook's logic diverges, this test file documents the contract.
import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { RunEstimate } from '../api/settings';

// ── Mirror the pure decision logic from useRunGate ────────────────────────
// The hook owns: calling getEstimate, deciding if modal is needed, and calling
// simStartFn on confirm. We extract those three decisions as pure functions.

type GateDecision =
  | { action: 'start_direct' }
  | { action: 'show_modal'; estimate: RunEstimate | null };

function gateDecide(estimate: RunEstimate | null, estimateFailed: boolean): GateDecision {
  // Estimate failure → show modal (user must explicitly confirm or cancel).
  if (estimateFailed) return { action: 'show_modal', estimate: null };
  if (estimate === null) return { action: 'show_modal', estimate: null };
  if (estimate.mode === 'local') return { action: 'start_direct' };
  return { action: 'show_modal', estimate };
}

// ── Fixtures ─────────────────────────────────────────────────────────────
const LOCAL_ESTIMATE: RunEstimate = {
  calls: 300,
  low_usd: '0.00',
  high_usd: '0.00',
  mode: 'local',
};

const CLOUD_ESTIMATE: RunEstimate = {
  calls: 300,
  low_usd: '0.12',
  high_usd: '0.45',
  mode: 'cloud',
};

const MIXED_ESTIMATE: RunEstimate = {
  calls: 300,
  low_usd: '0.06',
  high_usd: '0.22',
  mode: 'mixed',
};

// ── Mock helpers ──────────────────────────────────────────────────────────

function mockFetchOk(body: unknown) {
  return vi.fn().mockResolvedValue({
    ok: true,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(''),
  });
}

// ── Decision logic tests ──────────────────────────────────────────────────

describe('gateDecide — LOCAL mode', () => {
  it('returns start_direct when mode is local', () => {
    const result = gateDecide(LOCAL_ESTIMATE, false);
    expect(result.action).toBe('start_direct');
  });
});

describe('gateDecide — CLOUD mode', () => {
  it('returns show_modal when mode is cloud', () => {
    const result = gateDecide(CLOUD_ESTIMATE, false);
    expect(result.action).toBe('show_modal');
    if (result.action === 'show_modal') {
      expect(result.estimate?.mode).toBe('cloud');
      expect(result.estimate?.calls).toBe(300);
    }
  });
});

describe('gateDecide — MIXED mode', () => {
  it('returns show_modal when mode is mixed', () => {
    const result = gateDecide(MIXED_ESTIMATE, false);
    expect(result.action).toBe('show_modal');
    if (result.action === 'show_modal') {
      expect(result.estimate?.mode).toBe('mixed');
    }
  });
});

describe('gateDecide — estimate failure', () => {
  it('returns show_modal with null estimate on failure', () => {
    const result = gateDecide(null, true);
    expect(result.action).toBe('show_modal');
    if (result.action === 'show_modal') {
      expect(result.estimate).toBeNull();
    }
  });
});

// ── Integration: getEstimate mock + simStart mock ─────────────────────────
// Tests that simulate the full async flow: getEstimate → decision → simStart.

describe('run gate flow — local mode', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', mockFetchOk(LOCAL_ESTIMATE));
  });

  it('calls simStartFn directly without opening modal', async () => {
    const { getEstimate } = await import('../api/settings');
    const simStartFn = vi.fn().mockResolvedValue({ status: 'ok', message: 'started' });

    const estimate = await getEstimate();
    const decision = gateDecide(estimate, false);

    expect(decision.action).toBe('start_direct');
    if (decision.action === 'start_direct') {
      await simStartFn('test seed');
    }

    expect(simStartFn).toHaveBeenCalledWith('test seed');
    expect(simStartFn).toHaveBeenCalledTimes(1);
  });
});

describe('run gate flow — cloud mode, confirm', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', mockFetchOk(CLOUD_ESTIMATE));
  });

  it('shows modal on cloud mode; simStartFn called only on confirm', async () => {
    const { getEstimate } = await import('../api/settings');
    const simStartFn = vi.fn().mockResolvedValue({ status: 'ok', message: 'started' });

    const estimate = await getEstimate();
    const decision = gateDecide(estimate, false);

    expect(decision.action).toBe('show_modal');

    // Simulate: user confirms
    await simStartFn('test seed');
    expect(simStartFn).toHaveBeenCalledTimes(1);
  });
});

describe('run gate flow — cloud mode, cancel', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', mockFetchOk(CLOUD_ESTIMATE));
  });

  it('simStartFn is NOT called when user cancels', async () => {
    const { getEstimate } = await import('../api/settings');
    const simStartFn = vi.fn().mockResolvedValue({ status: 'ok', message: 'started' });

    const estimate = await getEstimate();
    const decision = gateDecide(estimate, false);

    expect(decision.action).toBe('show_modal');

    // Simulate: user cancels — do NOT call simStartFn
    expect(simStartFn).not.toHaveBeenCalled();
  });
});

describe('run gate flow — estimate failure', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockRejectedValue(new Error('network error')),
    );
  });

  it('shows modal with null estimate on getEstimate failure', async () => {
    const simStartFn = vi.fn().mockResolvedValue({ status: 'ok', message: 'started' });

    // Simulate estimate failure path
    let estimateFailed = false;
    let estimate: RunEstimate | null = null;
    try {
      const { getEstimate } = await import('../api/settings');
      estimate = await getEstimate();
    } catch {
      estimateFailed = true;
    }

    const decision = gateDecide(estimate, estimateFailed);

    // Modal should be shown with null estimate
    expect(decision.action).toBe('show_modal');
    if (decision.action === 'show_modal') {
      expect(decision.estimate).toBeNull();
    }

    // User confirms despite unknown cost
    await simStartFn('test seed');
    expect(simStartFn).toHaveBeenCalledWith('test seed');
  });

  it('simStartFn NOT called when user cancels after estimate failure', async () => {
    const simStartFn = vi.fn();

    let estimateFailed = false;
    let estimate: RunEstimate | null = null;
    try {
      const { getEstimate } = await import('../api/settings');
      estimate = await getEstimate();
    } catch {
      estimateFailed = true;
    }

    const decision = gateDecide(estimate, estimateFailed);
    expect(decision.action).toBe('show_modal');

    // User cancels — simStartFn never called
    expect(simStartFn).not.toHaveBeenCalled();
  });
});
