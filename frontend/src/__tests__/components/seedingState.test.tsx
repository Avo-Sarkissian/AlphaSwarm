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
    expect(text).toMatch(/parsing the seed/i);
    expect(text).not.toMatch(/\/100|spawn|persona loaded|context primed/i);
  });
});
