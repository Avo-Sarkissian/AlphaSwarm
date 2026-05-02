import { useEffect, useState } from 'react';
import { apiFetch } from '../api/client';

// GET /api/edges/{cycle_id}?round=N
// Backend returns { edges: [{source_id, target_id, weight}, ...] } (NR-5).
// Force layout consumes [source, target] tuples — weight ignored for now.
// Only called inside EdgesContext's provider (single call for the app).
// Returns tuples [source, target] to match viz.jsx's expected shape.
export interface UseEdgesResult {
  edges: Array<[string, string]>;
  loading: boolean;
  error: Error | null;
}

interface BackendEdge {
  source_id?: unknown;
  target_id?: unknown;
  weight?: unknown; // accepted but not consumed by force-layout
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
              typeof e?.source_id === 'string' &&
              typeof e?.target_id === 'string',
          )
          .map((e) => [e.source_id as string, e.target_id as string]);
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
