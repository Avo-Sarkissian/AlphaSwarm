import { describe, expect, it } from 'vitest';
import { bracketTallies, consensusLeader, tallySignals } from '../../lib/tally';
import { makeAgent } from '../helpers/agents';

describe('tallySignals', () => {
  it('counts pending agents as thinking, never as hold', () => {
    const t = tallySignals([makeAgent('quants_01', null), makeAgent('quants_02', null), makeAgent('degens_01', 'hold')]);
    expect(t).toEqual({ buy: 0, sell: 0, hold: 1, parseError: 0, thinking: 2, resolved: 1, decided: 1 });
  });

  it('keeps failed agents out of decided', () => {
    const t = tallySignals([makeAgent('quants_01', 'buy'), makeAgent('quants_02', 'parse_error')]);
    expect(t.decided).toBe(1);
    expect(t.parseError).toBe(1);
    expect(t.resolved).toBe(2);
  });

  it('returns zeros for an empty list', () => {
    expect(tallySignals([])).toEqual({ buy: 0, sell: 0, hold: 0, parseError: 0, thinking: 0, resolved: 0, decided: 0 });
  });
});

describe('consensusLeader', () => {
  it('has no leader while nobody has decided (a round never opens at HOLD 100%)', () => {
    const agents = Array.from({ length: 100 }, (_, i) => makeAgent(`quants_${String(i + 1).padStart(2, '0')}`, null));
    expect(consensusLeader(tallySignals(agents))).toEqual({ signal: null, pct: 0 });
  });

  it('computes the percentage over decided agents only', () => {
    const agents = [
      makeAgent('a_01', 'buy'), makeAgent('a_02', 'buy'), makeAgent('a_03', 'buy'),
      makeAgent('a_04', 'sell'), makeAgent('a_05', 'hold'),
      makeAgent('a_06', null), makeAgent('a_07', null), makeAgent('a_08', 'parse_error'),
    ];
    expect(consensusLeader(tallySignals(agents))).toEqual({ signal: 'buy', pct: 60 });
  });

  it('breaks ties buy > sell > hold', () => {
    expect(consensusLeader(tallySignals([makeAgent('a_01', 'sell'), makeAgent('a_02', 'hold')])).signal).toBe('sell');
    expect(consensusLeader(tallySignals([makeAgent('a_01', 'buy'), makeAgent('a_02', 'sell')])).signal).toBe('buy');
  });
});

describe('bracketTallies', () => {
  it('groups agents by snake_case bracket in roster order', () => {
    const rows = bracketTallies([
      makeAgent('sell_side_01', 'buy'),
      makeAgent('quants_01', null),
      makeAgent('sell_side_02', null),
    ]);
    expect(rows.map((r) => [r.bracket, r.total, r.tally.buy, r.tally.thinking])).toEqual([
      ['sell_side', 2, 1, 1],
      ['quants', 1, 0, 1],
    ]);
  });
});
