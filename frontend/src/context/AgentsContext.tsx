import { createContext, useContext, useMemo } from 'react';
import type { ReactNode } from 'react';
import { useFlipMarkedAgents } from '../hooks/useFlipMarkedAgents';
import type { AgentView, StateFrame } from '../types';

export interface AgentsCtxValue {
  agents: AgentView[];
}

const Ctx = createContext<AgentsCtxValue | null>(null);

export function AgentsProvider({
  frame,
  children,
}: {
  frame: StateFrame;
  children: ReactNode;
}) {
  const agents = useFlipMarkedAgents(frame);
  const value = useMemo<AgentsCtxValue>(() => ({ agents }), [agents]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAgents(): AgentsCtxValue {
  const v = useContext(Ctx);
  if (!v) throw new Error('useAgents outside provider');
  return v;
}
