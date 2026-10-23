// Derived data for the dashboard panels: each hook reads its contexts and
// returns exactly the shape its panel renders, memoised per frame.
import { useMemo } from 'react';
import { useAgents } from '../../context/AgentsContext';
import { useEdgesCtx } from '../../context/EdgesContext';
import { useRationales } from '../../context/RationalesContext';
import { bracketSpec } from '../../data';
import { rankInfluencers } from '../../lib/influence';
import { buildFeed, indexAgents, type FeedRow } from '../../lib/rationaleFeed';
import { bracketTallies } from '../../lib/tally';
import type { BracketRow } from './panels';

export interface InfluencerRow {
  id: string;
  bracket: string;
  citedBy: number;
  barPct: number;
}

/** Agents cited by the most distinct peers in the round on screen. */
export function useTopInfluencers(limit = 5): InfluencerRow[] {
  const { agents } = useAgents();
  const { edges } = useEdgesCtx();
  return useMemo(() => {
    const byId = new Map(agents.map((a) => [a.id, a]));
    const ranked = rankInfluencers(agents, edges).slice(0, limit);
    const max = Math.max(1, ...ranked.map((r) => r.citedBy));
    return ranked.map((r) => ({
      id: r.agentId,
      bracket: byId.get(r.agentId)?.bracketDisplay ?? '',
      citedBy: r.citedBy,
      barPct: Math.round((r.citedBy / max) * 100),
    }));
  }, [agents, edges, limit]);
}

/**
 * Rows for the Brackets panel. They come from the agents on screen, so they
 * always describe the current round (wire bracket_summaries only arrive after
 * a round ends); pending agents leave the rest of the bar blank.
 */
export function useBracketRows(): BracketRow[] {
  const { agents } = useAgents();
  return useMemo(
    () =>
      bracketTallies(agents).map((b) => ({
        bracket: b.bracket,
        color: bracketSpec(b.bracket)?.color ?? 'var(--accent)',
        display_name: b.display,
        total: b.total,
        buy_count: b.tally.buy,
        sell_count: b.tally.sell,
        hold_count: b.tally.hold,
      })),
    [agents],
  );
}

/**
 * Rows for the Rationale Feed. Each row carries the per-entry wire signal, not
 * the agent's current one, so a flip never retags old entries. Citations are
 * stubbed [] in the adapter (docs/DECISIONS.md#kr-41-1-10).
 */
export function useFeedRows(): FeedRow[] {
  const { agents } = useAgents();
  const { rationales } = useRationales();
  const agentsById = useMemo(() => indexAgents(agents), [agents]);
  return useMemo(() => buildFeed(rationales, agentsById), [rationales, agentsById]);
}
