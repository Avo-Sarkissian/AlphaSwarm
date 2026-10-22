// One cached loader for INFLUENCED_BY edges, keyed by (cycle, round, edges
// version). EdgesProvider is its only caller; every panel reads the
// result through useEdgesCtx(), so the canvas, counters, Top Influencers, the
// deep-dive and the interview always agree on one cycle and one round.
//
// The returned value always belongs to the current key: a response for an
// older key is cached but never rendered, and errors are not cached so a
// remount retries.
import { useEffect, useState } from 'react';
import { fetchEdges, type Edge } from '../api/edges';
import { useFrameMeta } from '../context/FrameMetaContext';

export type EdgesStatus = 'idle' | 'loading' | 'ready' | 'error';

export interface CycleEdges {
  edges: Edge[];
  inDegree: Map<string, number>;
  outDegree: Map<string, number>;
  citedBy: Map<string, string[]>;
  cites: Map<string, string[]>;
  status: EdgesStatus;
}

const CACHE_LIMIT = 32;
const cache = new Map<string, CycleEdges>();
const inflight = new Map<string, Promise<CycleEdges>>();

function emptyEdges(status: EdgesStatus): CycleEdges {
  return {
    edges: [],
    inDegree: new Map(),
    outDegree: new Map(),
    citedBy: new Map(),
    cites: new Map(),
    status,
  };
}

const IDLE = emptyEdges('idle');
const LOADING = emptyEdges('loading');
const FAILED = emptyEdges('error');

export function edgesCacheKey(cycleId: string, round: number, edgesVersion: number): string {
  return `${cycleId}:${round}:${edgesVersion}`;
}

/** Index edges by direction: source_id is the citing agent, target_id the cited one. */
export function indexEdges(edges: readonly Edge[]): CycleEdges {
  const inDegree = new Map<string, number>();
  const outDegree = new Map<string, number>();
  const citedBy = new Map<string, string[]>();
  const cites = new Map<string, string[]>();
  for (const e of edges) {
    outDegree.set(e.source_id, (outDegree.get(e.source_id) ?? 0) + 1);
    inDegree.set(e.target_id, (inDegree.get(e.target_id) ?? 0) + 1);
    cites.set(e.source_id, [...(cites.get(e.source_id) ?? []), e.target_id]);
    citedBy.set(e.target_id, [...(citedBy.get(e.target_id) ?? []), e.source_id]);
  }
  return { edges: [...edges], inDegree, outDegree, citedBy, cites, status: 'ready' };
}

function remember(key: string, value: CycleEdges): void {
  cache.set(key, value);
  while (cache.size > CACHE_LIMIT) {
    const oldest = cache.keys().next().value;
    if (oldest === undefined) break;
    cache.delete(oldest);
  }
}

function load(key: string, cycleId: string, round: number): Promise<CycleEdges> {
  const pending = inflight.get(key);
  if (pending) return pending;
  const promise = fetchEdges(cycleId, round)
    .then((list) => {
      const value = indexEdges(list);
      remember(key, value);
      return value;
    })
    .finally(() => {
      inflight.delete(key);
    });
  inflight.set(key, promise);
  return promise;
}

export function useCycleEdges(cycleId: string | null, round: number | null): CycleEdges {
  const { edgesVersion } = useFrameMeta();
  const key =
    cycleId !== null && round !== null && round >= 1
      ? edgesCacheKey(cycleId, round, edgesVersion)
      : null;
  const [loaded, setLoaded] = useState<{ key: string; value: CycleEdges } | null>(null);

  useEffect(() => {
    if (key === null || cycleId === null || round === null || cache.has(key)) return;
    let cancelled = false;
    load(key, cycleId, round).then(
      (value) => {
        if (!cancelled) setLoaded({ key, value });
      },
      () => {
        if (!cancelled) setLoaded({ key, value: FAILED });
      },
    );
    return () => {
      cancelled = true;
    };
  }, [key, cycleId, round]);

  if (key === null) return IDLE;
  const cached = cache.get(key);
  if (cached) return cached;
  if (loaded !== null && loaded.key === key) return loaded.value;
  return LOADING;
}
