// Influence edges for the round on screen, shared by every panel (canvas,
// counters, Top Influencers, deep-dive, interview). The target comes from the
// frame metadata, so the edges always belong to the cycle being shown
// (docs/DECISIONS.md#adr-neo4j-schema).
import { createContext, useContext, useMemo } from 'react';
import type { ReactNode } from 'react';
import { useFrameMeta } from './FrameMetaContext';
import { useCycleEdges, type CycleEdges } from '../hooks/useCycleEdges';
import { edgesTarget, type EdgesTarget } from '../lib/edgesTarget';

export interface EdgesCtxValue extends CycleEdges {
  /** The cycle and round these edges belong to; null when nothing has edges yet. */
  target: EdgesTarget | null;
}

const Ctx = createContext<EdgesCtxValue | null>(null);

export function EdgesProvider({ children }: { children: ReactNode }) {
  const meta = useFrameMeta();
  const target = edgesTarget(meta);
  const cycleId = target?.cycleId ?? null;
  const round = target?.round ?? null;
  const edges = useCycleEdges(cycleId, round);
  const value = useMemo<EdgesCtxValue>(
    () => ({
      ...edges,
      target: cycleId !== null && round !== null ? { cycleId, round } : null,
    }),
    [edges, cycleId, round],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useEdgesCtx(): EdgesCtxValue {
  const v = useContext(Ctx);
  if (!v) throw new Error('useEdgesCtx outside provider');
  return v;
}
