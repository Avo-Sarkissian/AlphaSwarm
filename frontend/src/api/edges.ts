// src/api/edges.ts
// Wraps GET /api/edges/{cycle_id}?round=N for InterviewV2 citation graph + BracketDeepDive influences.
// Edges land in Neo4j during simulation and are queryable post-cycle (NOT during live view —
// see KR-41.6-13). Returns empty array on 404/503 (no edges yet for this cycle/round).
//
// codex MEDIUM-7 — verified semantics + envelope (2026-05-09):
//   Backend: src/alphaswarm/web/routes/edges.py returns EdgesResponse {edges: EdgeItem[]} (NOT flat array).
//   Backend: src/alphaswarm/graph.py:942 Cypher writes (author)-[:INFLUENCED_BY]->(cited).
//   Therefore source_id = the citing agent (author), target_id = the cited agent (being-cited).
//
//   Convenience accessors (USE THESE in components — do not infer direction at the call site):
//     - For agent A: agents A CITED        → edges.filter(e => e.source_id === A).map(e => e.target_id)
//     - For agent A: agents WHO CITED A    → edges.filter(e => e.target_id === A).map(e => e.source_id)
//   "in-degree" / "out-degree" naming is ambiguous when read against a relationship called
//   INFLUENCED_BY (the arrow direction is opposite from the colloquial "X influences Y"
//   intuition). Use the cited / cited-by accessors to avoid bugs.

import { apiFetch, ApiError } from './client';

/**
 * INFLUENCED_BY edge between two agents during a given cycle/round.
 *
 * Direction semantic (verified against src/alphaswarm/graph.py:942-974):
 *   `source_id`: the CITING agent (author of the decision that contained the citation)
 *   `target_id`: the CITED agent (the agent whose post was referenced)
 *
 * The Neo4j relationship is `(source)-[:INFLUENCED_BY]->(target)` — read as
 * "source was influenced by target" (i.e., source cited target).
 */
export interface Edge {
  /** Agent ID of the citing agent (author of the decision). */
  source_id: string;
  /** Agent ID of the cited agent (being referenced / influencing). */
  target_id: string;
  /** Edge weight (typically normalized citations / total_agents). */
  weight: number;
}

/** Backend response envelope per src/alphaswarm/web/routes/edges.py:22-25. */
interface EdgesResponse {
  edges: Edge[];
}

/**
 * Fetch INFLUENCED_BY edges for a cycle and round.
 * @returns Edge[] (extracted from `{edges:[...]}` envelope). 404 / 503 → empty array.
 *
 * USAGE:
 *   const edges = await fetchEdges('current', 3);  // 'current' resolves to latest cycle backend-side
 *   // For agent A (e.g., 'Q-03'):
 *   const cited = edges.filter(e => e.source_id === 'Q-03').map(e => e.target_id);
 *   const citedBy = edges.filter(e => e.target_id === 'Q-03').map(e => e.source_id);
 */
export async function fetchEdges(cycleId: string, round: number): Promise<Edge[]> {
  try {
    const resp = await apiFetch<EdgesResponse>(
      `/api/edges/${encodeURIComponent(cycleId)}?round=${encodeURIComponent(String(round))}`
    );
    return resp.edges ?? [];
  } catch (e) {
    if (e instanceof ApiError && (e.status === 404 || e.status === 503)) return [];
    throw e;
  }
}
