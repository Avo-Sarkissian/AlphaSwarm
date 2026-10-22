// Top Influencers: agents ranked by how many distinct peers cited them
// (in-degree on target_id; source_id is the citing agent). Ranking
// by citations made would pick the most influenced agents instead
// (docs/DECISIONS.md#adr-neo4j-schema). Only agents cited at least once are
// ranked, so the panel never pads with "0" rows (docs/DECISIONS.md#f-35).
import type { Edge } from '../api/edges';
import type { AgentView } from '../types';

export interface InfluencerRank {
  agentId: string;
  citedBy: number;
}

export function rankInfluencers(
  agents: readonly AgentView[],
  edges: readonly Edge[],
): InfluencerRank[] {
  const known = new Set(agents.map((a) => a.id));
  const citers = new Map<string, Set<string>>();
  for (const e of edges) {
    if (e.source_id === e.target_id || !known.has(e.target_id)) continue;
    const set = citers.get(e.target_id) ?? new Set<string>();
    set.add(e.source_id);
    citers.set(e.target_id, set);
  }
  return [...citers.entries()]
    .map(([agentId, set]) => ({ agentId, citedBy: set.size }))
    .sort((a, b) => b.citedBy - a.citedBy || (a.agentId < b.agentId ? -1 : 1));
}
