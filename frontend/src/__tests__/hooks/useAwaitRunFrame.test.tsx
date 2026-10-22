// @vitest-environment happy-dom
import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AWAIT_RUN_FRAME_MS, useAwaitRunFrame } from '../../hooks/useAwaitRunFrame';
import type { Lifecycle } from '../../lib/lifecycle';

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

function setup(initial: Lifecycle) {
  return renderHook(({ lifecycle }) => useAwaitRunFrame(lifecycle), {
    initialProps: { lifecycle: initial },
  });
}

describe('useAwaitRunFrame', () => {
  it('is not awaiting until armed', () => {
    expect(setup('idle').result.current.awaiting).toBe(false);
  });

  it.each(['idle', 'complete'] as const)(
    'waits from a successful start at %s until the run reaches the frame',
    (rest) => {
      const view = setup(rest);
      act(() => view.result.current.arm());
      expect(view.result.current.awaiting).toBe(true);
      view.rerender({ lifecycle: 'seeding' });
      expect(view.result.current.awaiting).toBe(false);
    },
  );

  it('does not wait again when a fast-failing run drops back to idle', () => {
    const view = setup('idle');
    act(() => view.result.current.arm());
    view.rerender({ lifecycle: 'seeding' });
    view.rerender({ lifecycle: 'idle' });
    expect(view.result.current.awaiting).toBe(false);
  });

  it('gives up after the timeout when no run frame arrives', () => {
    vi.useFakeTimers();
    const view = setup('idle');
    act(() => view.result.current.arm());
    act(() => vi.advanceTimersByTime(AWAIT_RUN_FRAME_MS - 1));
    expect(view.result.current.awaiting).toBe(true);
    act(() => vi.advanceTimersByTime(1));
    expect(view.result.current.awaiting).toBe(false);
  });

  it('does not wait when the run reached the frame before the start answer', () => {
    const view = setup('seeding');
    act(() => view.result.current.arm());
    expect(view.result.current.awaiting).toBe(false);
    view.rerender({ lifecycle: 'idle' });
    expect(view.result.current.awaiting).toBe(false);
  });
});
