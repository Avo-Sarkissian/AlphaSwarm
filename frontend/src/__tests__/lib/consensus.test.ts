// The TypeScript net score must match alphaswarm.consensus (docs/DECISIONS.md#adr-consensus-estimators).
import { describe, expect, it } from 'vitest';
import cases from '../fixtures/consensus_cases.json';
import { formatScore, leanOf, netScoreVotes, votesFromAgents, type VoteInput, type Weighting } from '../../lib/consensus';
import { makeAgent } from '../helpers/agents';

interface Case { name: string; votes: VoteInput[]; expected: Record<Weighting, number> }
const WEIGHTINGS: readonly Weighting[] = ['headcount', 'reach', 'bracket_equal'];

describe('netScoreVotes mirrors the Python estimator', () => {
  for (const c of cases as Case[]) {
    it(c.name, () => {
      for (const w of WEIGHTINGS) expect(netScoreVotes(c.votes, w)).toBeCloseTo(c.expected[w], 5);
    });
  }
});

describe('votesFromAgents', () => {
  it('keeps decided agents of known brackets with their reach', () => {
    const votes = votesFromAgents([
      makeAgent('sell_side_01', 'buy', 0.8),
      makeAgent('shorts_01', 'sell', 0.6),
      makeAgent('quants_01', null),
      makeAgent('degens_01', 'parse_error'),
    ]);
    expect(votes).toEqual([
      { bracket: 'sell_side', signal: 'buy', confidence: 0.8, reach: 0.75 },
      { bracket: 'shorts', signal: 'sell', confidence: 0.6, reach: 0.6 },
    ]);
  });
});

describe('lean and format', () => {
  it('uses the 0.15 deadband', () => {
    expect(leanOf(0.15)).toBe('hold');
    expect(leanOf(0.16)).toBe('buy');
    expect(leanOf(-0.5)).toBe('sell');
  });
  it('formats signed scores', () => {
    expect(formatScore(0.36)).toBe('+0.36');
    expect(formatScore(-0.05)).toBe('-0.05');
    expect(formatScore(0)).toBe('+0.00');
  });
});
