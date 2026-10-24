// Influence edges of one round, from GET /api/cycles/{id}/citations?round=N.
// Direction: source_id is the CITING agent, target_id the CITED agent
// (docs/DECISIONS.md#adr-neo4j-schema). cited_signal is what the citing agent
// saw: the cited agent's signal in the previous round. Every citation weighs 1;
// an agent's influence is its in-degree (node size), not an edge weight.
// The only caller is hooks/useCycleEdges.ts.
import { apiFetch, ApiError } from './client';
import { toWireSignal } from '../lib/wireSignal';
import type { WireSignal } from '../types';

export interface Edge {
  /** The citing agent. */
  source_id: string;
  /** The cited agent. */
  target_id: string;
  weight: number;
  /** The cited agent's previous-round signal; absent when unknown. */
  cited_signal?: WireSignal;
}

interface RoundCitation {
  source_id: string;
  target_id: string;
  cited_signal: string;
}

interface RoundCitationsResponse {
  cycle_id: string;
  round_num: number;
  citations: RoundCitation[];
}

function citationToEdge(c: RoundCitation): Edge {
  const seen = toWireSignal(c.cited_signal);
  return {
    source_id: c.source_id,
    target_id: c.target_id,
    weight: 1,
    ...(seen !== undefined ? { cited_signal: seen } : {}),
  };
}

/** One round's citations as edges. 404 (no such cycle) and 503 (Neo4j down) mean no edges. */
export async function fetchEdges(cycleId: string, round: number): Promise<Edge[]> {
  const params = new URLSearchParams({ round: String(round) });
  try {
    const body = await apiFetch<RoundCitationsResponse>(
      `/api/cycles/${encodeURIComponent(cycleId)}/citations?${params.toString()}`,
    );
    return (body.citations ?? []).map(citationToEdge);
  } catch (e) {
    if (e instanceof ApiError && (e.status === 404 || e.status === 503)) return [];
    throw e;
  }
}
