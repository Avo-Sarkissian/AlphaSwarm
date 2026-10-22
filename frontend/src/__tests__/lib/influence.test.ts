import { describe, expect, it } from 'vitest';
import type { Edge } from '../../api/edges';
import { rankInfluencers } from '../../lib/influence';
import { makeAgent } from '../helpers/agents';

const e = (source_id: string, target_id: string): Edge => ({ source_id, target_id, weight: 0.01 });
const AGENTS = [makeAgent('quants_01'), makeAgent('sell_side_03'), makeAgent('macro_02')];

describe('rankInfluencers', () => {
  it('ranks by citations received, not citations made (three edges)', () => {
    const edges = [e('quants_01', 'sell_side_03'), e('macro_02', 'sell_side_03'), e('sell_side_03', 'quants_01')];
    expect(rankInfluencers(AGENTS, edges)).toEqual([
      { agentId: 'sell_side_03', citedBy: 2 },
      { agentId: 'quants_01', citedBy: 1 },
    ]);
  });

  it('breaks ties by agent id', () => {
    const edges = [e('quants_01', 'sell_side_03'), e('quants_01', 'macro_02')];
    expect(rankInfluencers(AGENTS, edges).map((r) => r.agentId)).toEqual(['macro_02', 'sell_side_03']);
  });

  it('counts a citing agent once, and ignores self-citations and unknown agents', () => {
    const edges = [
      e('quants_01', 'sell_side_03'),
      e('quants_01', 'sell_side_03'),
      e('macro_02', 'macro_02'),
      e('quants_01', 'not_in_roster_99'),
    ];
    expect(rankInfluencers(AGENTS, edges)).toEqual([{ agentId: 'sell_side_03', citedBy: 1 }]);
  });

  it('returns nothing without edges', () => {
    expect(rankInfluencers(AGENTS, [])).toEqual([]);
  });
});
