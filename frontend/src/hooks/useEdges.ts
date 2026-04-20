import { useEffect, useState } from 'react';
import { apiFetch } from '../api/client';

// GET /api/edges/{cycle_id}?round=N
// Only called inside EdgesContext's provider (single call for the app).
// Returns tuples [source, target] to match viz.jsx's expected shape.
export interface UseEdgesResult {
  edges: Array<[string, string]>;
  loading: boolean;
  error: Error | null;
}

interface BackendEdge {
  source?: unknown;
  target?: unknown;
}

export function useEdges(
  cycleId: string | null,
  round: number | null,
): UseEdgesResult {
  const [edges, setEdges] = useState<Array<[string, string]>>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    if (!cycleId) {
      setEdges([]);
      setLoading(false);
      setError(null);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);

    const roundParam = round != null ? `?round=${round}` : '';
    const path = `/api/edges/${encodeURIComponent(cycleId)}${roundParam}`;

    apiFetch<{ edges: BackendEdge[] }>(path)
      .then((res) => {
        if (cancelled) return;
        const list = Array.isArray(res?.edges) ? res.edges : [];
        const tuples: Array<[string, string]> = list
          .filter(
            (e) =>
              typeof e?.source === 'string' && typeof e?.target === 'string',
          )
          .map((e) => [e.source as string, e.target as string]);
        setEdges(tuples);
        setLoading(false);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setError(e instanceof Error ? e : new Error(String(e)));
        setEdges([]);
        setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [cycleId, round]);

  return { edges, loading, error };
}
