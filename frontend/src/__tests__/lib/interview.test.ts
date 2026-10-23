import { describe, expect, it } from 'vitest';
import type { AgentDecisionRow } from '../../api/agents';
import { didFlip, mergeTrajectory, openingLine, resolveInterviewCycle } from '../../lib/interview';

const stored: AgentDecisionRow[] = [
  { round_num: 1, signal: 'buy', confidence: 0.8, sentiment: 0.4, rationale: 'ZZZT deal looks accretive', cited_agents: [] },
  { round_num: 2, signal: 'sell', confidence: 0.6, sentiment: -0.2, rationale: 'Financing risk on QQQX', cited_agents: ['macro_03'] },
];

describe('mergeTrajectory', () => {
  it('uses stored rows, then the live signal for the round in progress, then missing', () => {
    expect(mergeTrajectory([1, 2, 3], stored, { roundNum: 3, signal: 'hold', confidence: 0.55 })).toEqual([
      { round: 1, signal: 'buy', confidence: 0.8, rationale: 'ZZZT deal looks accretive', source: 'stored' },
      { round: 2, signal: 'sell', confidence: 0.6, rationale: 'Financing risk on QQQX', source: 'stored' },
      { round: 3, signal: 'hold', confidence: 0.55, rationale: null, source: 'live' },
    ]);
  });

  it('never applies the live signal to an earlier round', () => {
    const points = mergeTrajectory([1, 2, 3], [], { roundNum: 3, signal: 'hold', confidence: 0.55 });
    expect(points.map((p) => p.source)).toEqual(['missing', 'missing', 'live']);
  });

  it('leaves a pending live agent as missing', () => {
    expect(mergeTrajectory([1], [], { roundNum: 1, signal: null, confidence: 0 })[0]?.source).toBe('missing');
  });
});

describe('didFlip', () => {
  it('compares the first and last decided signals, ignoring parse errors', () => {
    const p = (signal: 'buy' | 'sell' | 'parse_error' | null) => ({ round: 1, signal, confidence: null, rationale: null, source: 'stored' as const });
    expect(didFlip([p('buy'), p('sell')])).toBe(true);
    expect(didFlip([p('buy'), p('parse_error'), p('buy')])).toBe(false);
    expect(didFlip([p('buy'), p(null)])).toBe(false);
  });
});

describe('openingLine', () => {
  const base = { display: 'Quants', numRounds: 3, confidence: 0.7 };
  it('names the final round when complete', () => {
    expect(openingLine({ ...base, phase: 'complete', roundNum: 3, signal: 'sell' })).toBe(
      'Quants. Final round (R3) close: SELL, confidence 70%. Ask me about my reasoning.',
    );
  });
  it('follows a 2-round cycle', () => {
    expect(openingLine({ ...base, numRounds: 2, phase: 'complete', roundNum: 2, signal: 'buy' })).toContain('Final round (R2)');
  });
  it('speaks about the round in progress', () => {
    expect(openingLine({ ...base, phase: 'round_2', roundNum: 2, signal: 'buy' })).toContain('Round 2 of 3 so far: BUY');
  });
  it('admits it has not decided yet', () => {
    expect(openingLine({ ...base, phase: 'round_1', roundNum: 1, signal: null })).toContain('have not decided yet');
  });
});

describe('resolveInterviewCycle', () => {
  it('prefers the cycle on screen (live or replay) over the latest complete one', () => {
    expect(resolveInterviewCycle('replayed', 'latest')).toBe('replayed');
    expect(resolveInterviewCycle(null, 'latest')).toBe('latest');
    expect(resolveInterviewCycle(null, null)).toBeNull();
  });
});
