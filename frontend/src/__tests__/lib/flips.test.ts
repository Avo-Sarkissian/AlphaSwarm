import { afterEach, describe, expect, it } from 'vitest';
import { ROUND_MEMORY_CYCLES, forgetRounds, markFlips, recallRound, rememberRound } from '../../lib/flips';
import type { DecidedSignal } from '../../types';
import { makeAgent } from '../helpers/agents';

afterEach(() => forgetRounds());

describe('round memory', () => {
  it('stores only decided signals', () => {
    rememberRound('c1', 1, [
      makeAgent('quants_01', 'buy'),
      makeAgent('degens_01', null),
      makeAgent('algos_01', 'parse_error'),
    ]);
    expect([...(recallRound('c1', 1) ?? new Map())]).toEqual([['quants_01', 'buy']]);
  });

  it('keeps the stored map when a frame repeats the same signals', () => {
    rememberRound('c1', 1, [makeAgent('quants_01', 'buy')]);
    const first = recallRound('c1', 1);
    rememberRound('c1', 1, [makeAgent('quants_01', 'buy')]);
    expect(recallRound('c1', 1)).toBe(first);
  });

  it('forgets the oldest cycle beyond the limit', () => {
    for (let i = 0; i <= ROUND_MEMORY_CYCLES; i += 1) rememberRound(`c${i}`, 1, [makeAgent('quants_01', 'buy')]);
    expect(recallRound('c0', 1)).toBeUndefined();
    expect(recallRound(`c${ROUND_MEMORY_CYCLES}`, 1)).toBeDefined();
  });
});

describe('markFlips', () => {
  it('returns the same array without a previous round', () => {
    const agents = [makeAgent('quants_01', 'buy')];
    expect(markFlips(agents, undefined)).toBe(agents);
  });

  it('marks only decided-to-decided changes', () => {
    const previous = new Map<string, DecidedSignal>([
      ['quants_01', 'buy'],
      ['degens_01', 'sell'],
      ['algos_01', 'hold'],
    ]);
    const agents = [makeAgent('quants_01', 'sell'), makeAgent('degens_01', null), makeAgent('algos_01', 'parse_error')];
    const [quants, degens, algos] = markFlips(agents, previous);
    expect(quants).toMatchObject({ flipped: 1, flippedFrom: 'buy' });
    expect(degens?.flipped).toBe(0);
    expect(algos?.flipped).toBe(0);
  });
});
