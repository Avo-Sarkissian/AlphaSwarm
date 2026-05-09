import { createContext, useContext, useMemo } from 'react';
import type { ReactNode } from 'react';
import type { AgentView, StateFrame } from '../types';

export interface AgentsCtxValue {
  agents: AgentView[];
  consensus: number | null;
}

const Ctx = createContext<AgentsCtxValue | null>(null);

export function AgentsProvider({
  frame,
  children,
}: {
  frame: StateFrame;
  children: ReactNode;
}) {
  const value = useMemo<AgentsCtxValue>(
    () => ({ agents: frame.agents, consensus: frame.consensus }),
    [frame.agents, frame.consensus],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAgents(): AgentsCtxValue {
  const v = useContext(Ctx);
  if (!v) throw new Error('useAgents outside provider');
  return v;
}
