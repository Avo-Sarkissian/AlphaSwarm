// Net score mirror of alphaswarm.consensus (docs/DECISIONS.md#adr-consensus-estimators).
// S = sum(w * s * c) / sum(w) over decided agents; s = +1 buy, 0 hold, -1 sell.
// Pending (null), failed (parse_error) and unknown-bracket agents are excluded.
import { bracketSpec } from '../data';
import type { AgentView } from '../types';

export type Weighting = 'headcount' | 'reach' | 'bracket_equal';
type Decided = 'buy' | 'sell' | 'hold';

export interface VoteInput {
  bracket: string;
  signal: Decided;
  confidence: number;
  reach: number;
}

const DIRECTION: Record<Decided, number> = { buy: 1, hold: 0, sell: -1 };
const NET_SCORE_DEADBAND = 0.15;

export function votesFromAgents(agents: readonly AgentView[]): VoteInput[] {
  const votes: VoteInput[] = [];
  for (const agent of agents) {
    const signal = agent.signal;
    if (signal !== 'buy' && signal !== 'sell' && signal !== 'hold') continue;
    const spec = bracketSpec(agent.bracket);
    if (!spec) continue;
    votes.push({ bracket: agent.bracket, signal, confidence: agent.confidence, reach: spec.reach });
  }
  return votes;
}

export function netScoreVotes(votes: readonly VoteInput[], weighting: Weighting): number {
  if (votes.length === 0) return 0;
  const perBracket = new Map<string, number>();
  for (const v of votes) perBracket.set(v.bracket, (perBracket.get(v.bracket) ?? 0) + 1);
  let signed = 0;
  let total = 0;
  for (const v of votes) {
    const w =
      weighting === 'headcount' ? 1 : weighting === 'reach' ? v.reach : 1 / (perBracket.get(v.bracket) ?? 1);
    signed += w * DIRECTION[v.signal] * v.confidence;
    total += w;
  }
  return total > 0 ? signed / total : 0;
}

export function leanOf(score: number): Decided {
  if (score > NET_SCORE_DEADBAND) return 'buy';
  if (score < -NET_SCORE_DEADBAND) return 'sell';
  return 'hold';
}

export function formatScore(score: number): string {
  return `${score >= 0 ? '+' : '-'}${Math.abs(score).toFixed(2)}`;
}
