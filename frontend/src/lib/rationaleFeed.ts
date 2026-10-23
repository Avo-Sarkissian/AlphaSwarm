import type { AgentSignal, AgentView, RationaleView } from '../types';

export interface FeedRow {
  seq: number;
  agentId: string;
  bracketDisplay: string;
  signal: AgentSignal;
  round: number;
  text: string;
  cites: string[];
}

export function indexAgents(agents: readonly AgentView[]): Map<string, AgentView> {
  return new Map(agents.map((a) => [a.id, a]));
}

/** Newest first (docs/DECISIONS.md#p10-d-04); seq is the stable row key. */
export function buildFeed(rationales: readonly RationaleView[], agentsById: ReadonlyMap<string, AgentView>): FeedRow[] {
  return [...rationales]
    .sort((a, b) => b.seq - a.seq)
    .map((r) => ({
      seq: r.seq,
      agentId: r.agentId,
      bracketDisplay: agentsById.get(r.agentId)?.bracketDisplay ?? '',
      signal: r.signal,
      round: r.round,
      text: r.text,
      cites: r.citations,
    }));
}
