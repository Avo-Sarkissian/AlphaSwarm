import { useEffect, useState } from 'react';
import { fetchEdges } from '../api/edges';

// GET /api/edges/{cycle_id}?round=N
// Only called inside EdgesContext's provider (single call for the app).
// Returns tuples [source, target] to match viz.jsx's expected shape.
// Wire shape is { source_id, target_id, weight } (see api/edges.ts) —
// fetchEdges handles the envelope + 404/503 → [] semantics.
export interface UseEdgesResult {
  edges: Array<[string, string]>;
  loading: boolean;
  error: Error | null;
}

export function useEdges(
  cycleId: string | null,
  round: number | null,
): UseEdgesResult {
  const [edges, setEdges] = useState<Array<[string, string]>>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    // Skip fetch during SEEDING (round=0) — backend requires round ∈ [1,3] (422 otherwise).
    if (!cycleId || round == null || round < 1) {
      setEdges([]);
      setLoading(false);
      setError(null);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);

    fetchEdges(cycleId, round)
      .then((list) => {
        if (cancelled) return;
        const tuples: Array<[string, string]> = list
          .filter(
            (e) =>
              typeof e?.source_id === 'string' &&
              typeof e?.target_id === 'string',
          )
          .map((e) => [e.source_id, e.target_id]);
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
