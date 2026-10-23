// GET /api/agents/{agent_id}/decisions?cycle_id= — one agent's stored rounds.
import { request } from './client';

export interface AgentDecisionRow {
  round_num: number;
  signal: string; // lowercase: buy | sell | hold | parse_error
  confidence: number;
  sentiment: number;
  rationale: string;
  cited_agents: string[];
}

export interface AgentDecisionsResponse {
  agent_id: string;
  cycle_id: string;
  decisions: AgentDecisionRow[];
}

export function fetchAgentDecisions(agentId: string, cycleId: string, signal?: AbortSignal): Promise<AgentDecisionsResponse> {
  const params = new URLSearchParams({ cycle_id: cycleId });
  return request<AgentDecisionsResponse>(`/api/agents/${encodeURIComponent(agentId)}/decisions?${params.toString()}`, {
    signal,
  });
}
