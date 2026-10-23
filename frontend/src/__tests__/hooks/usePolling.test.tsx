// @vitest-environment happy-dom
import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { usePolling } from '../../hooks/usePolling';

afterEach(() => vi.useRealTimers());

describe('usePolling', () => {
  it("never renders the previous key's data under a new key", async () => {
    const seen: Array<[string, unknown]> = [];
    const fetchers: Record<string, () => Promise<string>> = {
      a: () => Promise.resolve('A'),
      b: () => new Promise<string>(() => {}),
    };
    const { result, rerender } = renderHook(
      ({ k }: { k: string }) => {
        const fetchFn = fetchers[k];
        if (!fetchFn) throw new Error(`no fetcher for ${k}`);
        const r = usePolling<string>({ key: k, fetchFn, intervalMs: 60_000 });
        seen.push([k, r.data]);
        return r;
      },
      { initialProps: { k: 'a' } },
    );
    await waitFor(() => expect(result.current.data).toBe('A'));

    rerender({ k: 'b' });

    expect(seen.filter(([k]) => k === 'b').map(([, d]) => d)).not.toContain('A');
    expect(result.current.data).toBeNull();
  });

  it('does not fetch while disabled and starts once enabled', async () => {
    const fetchFn = vi.fn().mockResolvedValue('X');
    const { result, rerender } = renderHook(
      ({ on }: { on: boolean }) => usePolling<string>({ key: 'k', fetchFn, intervalMs: 60_000, enabled: on }),
      { initialProps: { on: false } },
    );
    expect(fetchFn).not.toHaveBeenCalled();
    expect(result.current).toMatchObject({ data: null, error: null, loading: false, attempt: 0 });

    rerender({ on: true });

    await waitFor(() => expect(result.current.data).toBe('X'));
    expect(fetchFn).toHaveBeenCalledTimes(1);
  });

  it('never reports "polling timed out" while disabled', async () => {
    vi.useFakeTimers();
    const fetchFn = vi.fn().mockResolvedValue(null);
    const { result } = renderHook(() =>
      usePolling<null>({ key: 'advisory:none', fetchFn, intervalMs: 3000, maxAttempts: 2, enabled: false }),
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(fetchFn).not.toHaveBeenCalled();
    expect(result.current.error).toBeNull();
  });

  it('still surfaces the timeout when enabled and no data lands', async () => {
    vi.useFakeTimers();
    const fetchFn = vi.fn().mockResolvedValue(null);
    const { result } = renderHook(() =>
      usePolling<null>({ key: 'advisory:c1', fetchFn, intervalMs: 3000, maxAttempts: 2 }),
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(12_000);
    });
    expect(result.current.error?.message).toMatch(/polling timed out after 2 attempts/);
  });
});
