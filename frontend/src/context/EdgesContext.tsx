// WAVE-1-NOTE: Minimal stub so viz.jsx can import `useEdgesCtx` and compile.
// Task 2 of this plan rewrites this file with the real EdgesProvider that
// owns the single useEdges() fetch and broadcasts `[source, target]` tuples.
// For Wave 1, the stub ships an empty tuple list so Viz renders the graph
// without any edge overlays.
import { createContext, useContext } from 'react';
import type { ReactNode } from 'react';

export interface EdgesCtxValue {
  edges: Array<[string, string]>;
  cycleId: string | null;
  round: number | null;
  status: 'idle' | 'loading' | 'ready' | 'error';
  error: Error | null;
  refresh: () => void;
}

const defaultValue: EdgesCtxValue = {
  edges: [],
  cycleId: null,
  round: null,
  status: 'idle',
  error: null,
  refresh: () => {},
};

const EdgesContext = createContext<EdgesCtxValue>(defaultValue);

export function EdgesProvider({ children }: { children: ReactNode }) {
  return (
    <EdgesContext.Provider value={defaultValue}>
      {children}
    </EdgesContext.Provider>
  );
}

export function useEdgesCtx(): EdgesCtxValue {
  return useContext(EdgesContext);
}
