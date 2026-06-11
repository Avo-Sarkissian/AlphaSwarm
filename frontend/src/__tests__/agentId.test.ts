// Wire-contract tests for agentIdToBracket() — backend agent IDs are
// `{bracket}_{NN}` snake_case over the v2 bracket taxonomy (types.py
// BracketType). Multi-word brackets (sell_side, event_driven) are the
// regression trap: the old first-char prefix table misclassified them.

import { describe, expect, it } from 'vitest';
import { agentIdToBracket } from '../adapter/agentId';

describe('agentIdToBracket — v2 bracket taxonomy', () => {
  it.each([
    ['institutions_01', 'Institutions'],
    ['sell_side_03', 'SellSide'],
    ['event_driven_05', 'EventDriven'],
    ['quants_12', 'Quants'],
    ['degens_15', 'Degens'],
    ['narrators_08', 'Narrators'],
    ['algos_04', 'Algos'],
    ['macro_07', 'Macro'],
    ['shorts_06', 'Shorts'],
    ['allocators_05', 'Allocators'],
  ] as const)('maps %s -> %s', (id, expected) => {
    expect(agentIdToBracket(id)).toBe(expected);
  });

  it('falls back to Quants for unknown or v1-era IDs', () => {
    expect(agentIdToBracket('suits_03')).toBe('Quants'); // v1 bracket, retired
    expect(agentIdToBracket('Q-03')).toBe('Quants'); // design-era grammar
    expect(agentIdToBracket('whales_01')).toBe('Quants'); // v1 bracket, retired
    expect(agentIdToBracket('')).toBe('Quants');
  });
});
