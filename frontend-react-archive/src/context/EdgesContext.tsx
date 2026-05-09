import { createContext, useContext, useMemo } from 'react';
import type { ReactNode } from 'react';
import { useCurrentCycle } from '../hooks/useCurrentCycle';
import { useEdges } from '../hooks/useEdges';

// Viz consumes `edges` as [source, target] tuples — preserve that shape.
export interface EdgesCtxValue {
  edges: Array<[string, string]>;
  cycleId: string | null;
  round: number | null;
  loading: boolean;
}

const Ctx = createContext<EdgesCtxValue | null>(null);

export function EdgesProvider({
  round,
  children,
}: {
  round: number | null;
  children: ReactNode;
}) {
  const { cycleId, loading: cycleLoading } = useCurrentCycle();
  const { edges, loading: edgesLoading } = useEdges(cycleId, round);

  const value = useMemo<EdgesCtxValue>(
    () => ({
      edges,
      cycleId,
      round,
      loading: cycleLoading || edgesLoading,
    }),
    [edges, cycleId, round, cycleLoading, edgesLoading],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useEdgesCtx(): EdgesCtxValue {
  const v = useContext(Ctx);
  if (!v) throw new Error('useEdgesCtx outside provider');
  return v;
}
