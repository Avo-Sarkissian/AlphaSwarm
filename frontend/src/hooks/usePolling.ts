import { useEffect, useRef, useState } from 'react';

export interface UsePollingOpts<T> {
  key: string;
  fetchFn: () => Promise<T>;
  intervalMs: number;
  maxAttempts?: number;
  /** Stop the interval once a non-null result has landed (data is kept). */
  stopWhenData?: boolean;
}

export interface UsePollingResult<T> {
  data: T | null;
  error: Error | null;
  attempt: number;
  loading: boolean;
}

// key-driven polling hook. fetchFn is held in a ref so inline arrows
// from callers do NOT restart the interval loop on every render.
export function usePolling<T>(opts: UsePollingOpts<T>): UsePollingResult<T> {
  const { key, fetchFn, intervalMs, maxAttempts, stopWhenData } = opts;

  const fnRef = useRef(fetchFn);
  fnRef.current = fetchFn; // always latest without triggering effect

  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [attempt, setAttempt] = useState(0);

  // Mirror of `data` readable from inside the interval closure — lets the
  // timeout branch skip the error when a successful fetch already landed.
  const dataRef = useRef<T | null>(null);
  // Track the active key so a key change resets state (a new key must never
  // render the previous key's data/error).
  const keyRef = useRef(key);

  useEffect(() => {
    if (keyRef.current !== key) {
      keyRef.current = key;
      dataRef.current = null;
      setData(null);
      setError(null);
      setAttempt(0);
    }

    // maxAttempts <= 0 means polling disabled — no fetch, no interval, and
    // no spurious "polling timed out after 0 attempts" error.
    if (typeof maxAttempts === 'number' && maxAttempts <= 0) {
      return;
    }

    let cancelled = false;
    let n = 0;

    const tick = async () => {
      if (cancelled) return;
      try {
        const result = await fnRef.current();
        if (cancelled) return;
        dataRef.current = result;
        setData(result);
        setError(null);
      } catch (e: unknown) {
        if (cancelled) return;
        setError(e instanceof Error ? e : new Error(String(e)));
      } finally {
        if (!cancelled) {
          n += 1;
          setAttempt(n);
        }
      }
    };

    // immediate first fetch
    void tick();

    const id = setInterval(() => {
      if (stopWhenData && dataRef.current !== null) {
        clearInterval(id);
        return;
      }
      if (typeof maxAttempts === 'number' && n >= maxAttempts) {
        clearInterval(id);
        // D-19: surface polling timeout as Error so consumers can render
        // hadError — but only when no data ever landed (a cap hit with data
        // present is success, not a timeout).
        if (!cancelled && dataRef.current === null) {
          setError(new Error(`polling timed out after ${maxAttempts} attempts`));
        }
        return;
      }
      void tick();
    }, intervalMs);

    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [key, intervalMs, maxAttempts, stopWhenData]);

  return {
    data,
    error,
    attempt,
    loading: data === null && error === null,
  };
}
