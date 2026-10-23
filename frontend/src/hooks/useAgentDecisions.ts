import { useEffect, useState } from 'react';
import { fetchAgentDecisions, type AgentDecisionRow } from '../api/agents';
import { formatApiError } from '../lib/apiError';

export interface AgentDecisionsState {
  decisions: AgentDecisionRow[];
  error: string | null;
  loading: boolean;
}

interface Stored {
  key: string | null;
  decisions: AgentDecisionRow[];
  error: string | null;
}

/** Stored rounds for one agent; refetches when refreshKey changes (e.g. a new round started). */
export function useAgentDecisions(agentId: string, cycleId: string | null, refreshKey: string): AgentDecisionsState {
  const key = cycleId === null ? null : `${agentId}:${cycleId}`;
  const [state, setState] = useState<Stored>({ key: null, decisions: [], error: null });

  useEffect(() => {
    if (cycleId === null) return;
    const k = `${agentId}:${cycleId}`;
    const controller = new AbortController();
    fetchAgentDecisions(agentId, cycleId, controller.signal)
      .then((body) => setState({ key: k, decisions: body.decisions, error: null }))
      .catch((e: unknown) => {
        if (controller.signal.aborted) return;
        setState((s) => ({ key: k, decisions: s.key === k ? s.decisions : [], error: formatApiError(e) }));
      });
    return () => controller.abort();
  }, [agentId, cycleId, refreshKey]);

  const current = state.key === key ? state : null;
  return { decisions: current?.decisions ?? [], error: current?.error ?? null, loading: key !== null && current === null };
}
