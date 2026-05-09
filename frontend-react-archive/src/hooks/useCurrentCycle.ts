import { useCallback } from 'react';
import { apiFetch } from '../api/client';
import type { CycleMeta } from '../types';
import { usePolling } from './usePolling';

// GET /api/simulate/status is NOT implemented. Derive cycleId from the first
// entry of /api/replay/cycles (newest first). Poll every 5s.
export function useCurrentCycle() {
  const fetchFn = useCallback(
    () => apiFetch<{ cycles: CycleMeta[] }>('/api/replay/cycles'),
    [],
  );

  const { data, loading, error } = usePolling({
    key: 'replay-cycles',
    fetchFn,
    intervalMs: 5000,
  });

  return {
    cycleId: data?.cycles?.[0]?.cycle_id ?? null,
    loading,
    error,
  };
}
