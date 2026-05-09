import { useEffect, useRef, useState } from 'react';

export interface UsePollingOpts<T> {
  key: string;
  fetchFn: () => Promise<T>;
  intervalMs: number;
  maxAttempts?: number;
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
  const { key, fetchFn, intervalMs, maxAttempts } = opts;

  const fnRef = useRef(fetchFn);
  fnRef.current = fetchFn; // always latest without triggering effect

  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let n = 0;

    const tick = async () => {
      if (cancelled) return;
      try {
        const result = await fnRef.current();
        if (cancelled) return;
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
      if (typeof maxAttempts === 'number' && n >= maxAttempts) {
        clearInterval(id);
        return;
      }
      void tick();
    }, intervalMs);

    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [key, intervalMs, maxAttempts]);

  return {
    data,
    error,
    attempt,
    loading: data === null && error === null,
  };
}
