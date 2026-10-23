// @vitest-environment happy-dom
import { act, render } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { SeedingState } from '../../components/states';

const SEED = 'ZZZT Holdings is in late-stage talks to acquire QQQX Robotics for $4.2B in cash.';

afterEach(() => vi.useRealTimers());

describe('SeedingState', () => {
  it('describes the real seeding work without a fake spawn counter', () => {
    vi.useFakeTimers();
    render(<SeedingState seed={SEED} elapsedSeconds={65} />);
    act(() => {
      vi.advanceTimersByTime(3000);
    });
    const text = document.body.textContent ?? '';
    expect(text).toContain('1:05');
    expect(text).toContain(SEED);
    expect(text).toMatch(/parses the seed/i);
    expect(text).not.toMatch(/\/100|spawn|persona loaded|context primed/i);
  });

  it('names the worker model load that ends the phase', () => {
    // The worker loads once, before Round 1, while the phase is still SEEDING
    // (docs/DECISIONS.md#adr-round-runner): often the longest wait of the phase.
    render(<SeedingState seed={SEED} elapsedSeconds={240} />);
    const text = document.body.textContent ?? '';
    expect(text).toMatch(/worker model loads/i);
    expect(text).toMatch(/Round 1 starts when the worker is ready/i);
    expect(text).not.toMatch(/orchestrator is parsing/i);
  });
});
