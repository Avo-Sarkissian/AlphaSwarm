// @vitest-environment happy-dom
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CASCADE_STEP_MS, useCascadePlayer } from '../../hooks/useCascadePlayer';

type Props = { roundNum: number | null; numRounds: number };

function setup(initial: Props, seek = vi.fn(async (_round: number) => ({ status: 'ok' }))) {
  const view = renderHook((p: Props) => useCascadePlayer({ ...p, seek }), { initialProps: initial });
  return { seek, ...view };
}

async function step(): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(CASCADE_STEP_MS);
  });
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe('useCascadePlayer', () => {
  it('plays from Round 1 to the last round, one step per shown frame', async () => {
    const { seek, result, rerender } = setup({ roundNum: 3, numRounds: 3 });
    act(() => result.current.play());
    expect(seek).toHaveBeenLastCalledWith(1);
    rerender({ roundNum: 1, numRounds: 3 });
    await step();
    expect(seek).toHaveBeenLastCalledWith(2);
    rerender({ roundNum: 2, numRounds: 3 });
    await step();
    expect(seek).toHaveBeenLastCalledWith(3);
    rerender({ roundNum: 3, numRounds: 3 });
    expect(result.current.playing).toBe(true);
    await step();
    expect(result.current.playing).toBe(false);
    expect(seek.mock.calls.map(([round]) => round)).toEqual([1, 2, 3]);
  });

  it('starts without a seek when Round 1 is already shown', async () => {
    const { seek, result } = setup({ roundNum: 1, numRounds: 2 });
    act(() => result.current.play());
    expect(seek).not.toHaveBeenCalled();
    await step();
    expect(seek).toHaveBeenLastCalledWith(2);
  });

  it('waits for the frame to show the requested round', async () => {
    const { seek, result } = setup({ roundNum: 1, numRounds: 3 });
    act(() => result.current.play());
    await step();
    expect(seek).toHaveBeenLastCalledWith(2);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(CASCADE_STEP_MS * 4);
    });
    expect(seek).toHaveBeenCalledTimes(1);
  });

  it('stops when the viewer picks a round', async () => {
    const { seek, result } = setup({ roundNum: 1, numRounds: 3 });
    act(() => result.current.play());
    act(() => result.current.seek(3));
    expect(result.current.playing).toBe(false);
    await step();
    expect(seek.mock.calls.map(([round]) => round)).toEqual([3]);
  });

  it('stops and reports a failed seek', async () => {
    const failing = vi.fn(async (_round: number) => {
      throw new Error('boom');
    });
    const { result } = setup({ roundNum: 2, numRounds: 3 }, failing);
    await act(async () => {
      result.current.play();
    });
    expect(result.current.playing).toBe(false);
    expect(result.current.error).toContain('boom');
    act(() => result.current.dismissError());
    expect(result.current.error).toBeNull();
  });

  it('cancels its timer on unmount', async () => {
    const { seek, result, unmount } = setup({ roundNum: 1, numRounds: 3 });
    act(() => result.current.play());
    unmount();
    await step();
    expect(seek).not.toHaveBeenCalled();
  });
});
