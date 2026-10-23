import { describe, expect, it } from 'vitest';
import { buildFeed, indexAgents } from '../../lib/rationaleFeed';
import type { AgentView, RationaleView } from '../../types';

const agent = { id: 'quants_01', bracket: 'quants', bracketDisplay: 'Quants', signal: 'buy', confidence: 0.8, flipped: 0, roundLastSpoke: null, thinking: false } as unknown as AgentView;
const entry = (seq: number, agentId: string, text: string): RationaleView =>
  ({ seq, agentId, signal: 'buy', round: 2, text, citations: [], sources: [], ts: 0 }) as unknown as RationaleView;

describe('buildFeed', () => {
  it('orders newest first by seq and looks up the bracket once per agent', () => {
    const rows = buildFeed([entry(1, 'quants_01', 'old'), entry(3, 'ghost_99', 'new'), entry(2, 'quants_01', 'mid')], indexAgents([agent]));
    expect(rows.map((r) => [r.seq, r.text, r.bracketDisplay])).toEqual([
      [3, 'new', ''],
      [2, 'mid', 'Quants'],
      [1, 'old', 'Quants'],
    ]);
  });
});
