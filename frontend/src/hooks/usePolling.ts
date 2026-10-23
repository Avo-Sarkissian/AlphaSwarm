import { useEffect, useRef, useState } from 'react';

export interface UsePollingOpts<T> {
  key: string;
  fetchFn: () => Promise<T>;
  intervalMs: number;
  /** <= 0 disables polling (no fetch, no timeout error). */
  maxAttempts?: number;
  /** Stop the interval once a non-null result has landed (data is kept). */
  stopWhenData?: boolean;
  /** false = do not poll at all, e.g. while there is no cycle id. Default true. */
  enabled?: boolean;
}

export interface UsePollingResult<T> {
  data: T | null;
  error: Error | null;
  attempt: number;
  loading: boolean;
}

interface PollState<T> {
  key: string;
  data: T | null;
  error: Error | null;
  attempt: number;
}

// Key-driven polling. Results are stored together with the key they belong to,
// so the first render under a new key never shows the previous key's data.
// fetchFn is held in a ref so inline arrows do not restart the loop.
export function usePolling<T>(opts: UsePollingOpts<T>): UsePollingResult<T> {
  const { key, fetchFn, intervalMs, maxAttempts, stopWhenData, enabled = true } = opts;

  const fnRef = useRef(fetchFn);
  fnRef.current = fetchFn;

  const [state, setState] = useState<PollState<T>>({ key, data: null, error: null, attempt: 0 });
  // Mirror of the latest data readable from inside the interval closure.
  const dataRef = useRef<T | null>(null);

  useEffect(() => {
    dataRef.current = null;
    setState({ key, data: null, error: null, attempt: 0 });

    if (!enabled || (typeof maxAttempts === 'number' && maxAttempts <= 0)) return;

    let cancelled = false;
    let n = 0;
    // In-flight guard: never stack requests when fetchFn is slower than the
    // interval (docs/DECISIONS.md#f-16).
    let running = false;

    const tick = async () => {
      if (cancelled || running) return;
      running = true;
      try {
        const result = await fnRef.current();
        if (cancelled) return;
        dataRef.current = result;
        setState((s) => ({ ...s, key, data: result, error: null }));
      } catch (e: unknown) {
        if (cancelled) return;
        setState((s) => ({ ...s, key, error: e instanceof Error ? e : new Error(String(e)) }));
      } finally {
        running = false;
        if (!cancelled) {
          n += 1;
          setState((s) => ({ ...s, key, attempt: n }));
        }
      }
    };

    void tick();

    const id = setInterval(() => {
      if (stopWhenData && dataRef.current !== null) {
        clearInterval(id);
        return;
      }
      if (typeof maxAttempts === 'number' && n >= maxAttempts) {
        clearInterval(id);
        // docs/DECISIONS.md#p41-6-d-19: a cap hit without data is a timeout error.
        if (!cancelled && dataRef.current === null) {
          setState((s) => ({ ...s, key, error: new Error(`polling timed out after ${maxAttempts} attempts`) }));
        }
        return;
      }
      void tick();
    }, intervalMs);

    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [key, intervalMs, maxAttempts, stopWhenData, enabled]);

  const current = state.key === key ? state : null;
  const data = current?.data ?? null;
  const error = current?.error ?? null;
  return {
    data,
    error,
    attempt: current?.attempt ?? 0,
    loading: enabled && data === null && error === null,
  };
}
