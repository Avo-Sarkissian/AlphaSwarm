// The adapter keeps "no decision yet" (null) distinct from HOLD.
import { describe, expect, it } from 'vitest';
import { adaptSnapshot } from '../../adapter/frame';

const frame = adaptSnapshot({
  phase: 'round_2',
  round_num: 2,
  agent_states: {
    sell_side_03: { signal: null, confidence: 0 },
    quants_01: { signal: 'buy', confidence: 0.8 },
    degens_07: { signal: 'parse_error', confidence: 0 },
    macro_02: { signal: 'SELL', confidence: 0.4 },
    algos_01: { signal: 'maybe', confidence: 0.1 },
    narrators_01: {},
  },
});
const byId = Object.fromEntries(frame.agents.map((a) => [a.id, a]));

describe('adaptSnapshot agent signals', () => {
  it('keeps a null signal as pending, never hold', () => {
    expect(byId.sell_side_03.signal).toBeNull();
    expect(byId.sell_side_03.thinking).toBe(true);
  });

  it('treats a missing or unknown signal as pending', () => {
    expect(byId.narrators_01.signal).toBeNull();
    expect(byId.algos_01.signal).toBeNull();
  });

  it('keeps decided and failed signals, lower-cased', () => {
    expect(byId.quants_01.signal).toBe('buy');
    expect(byId.macro_02.signal).toBe('sell');
    expect(byId.degens_07.signal).toBe('parse_error');
    expect(byId.degens_07.thinking).toBe(false);
  });

  it('keeps the roster order of the wire', () => {
    expect(frame.agents.map((a) => a.id)).toEqual([
      'sell_side_03', 'quants_01', 'degens_07', 'macro_02', 'algos_01', 'narrators_01',
    ]);
  });
});
