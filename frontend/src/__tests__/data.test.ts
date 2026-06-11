// Wire-contract tests for the BRACKETS constant and normalizeBracketKey().
// BRACKETS mirrors DEFAULT_BRACKETS in src/alphaswarm/config.py (v2
// composition); the 10 wire values mirror types.py BracketType.

import { describe, expect, it } from 'vitest';
import { BRACKETS, normalizeBracketKey } from '../data';

const V2_WIRE_VALUES = [
  'institutions',
  'sell_side',
  'event_driven',
  'quants',
  'degens',
  'narrators',
  'algos',
  'macro',
  'shorts',
  'allocators',
];

describe('BRACKETS — v2 composition', () => {
  it('agent counts sum to exactly 100', () => {
    expect(BRACKETS.reduce((acc, b) => acc + b.count, 0)).toBe(100);
  });

  it('covers exactly the 10 v2 wire bracket values', () => {
    expect(BRACKETS.map((b) => b.value)).toEqual(V2_WIRE_VALUES);
  });
});

describe('normalizeBracketKey', () => {
  it('normalizes PascalCase frontend keys to snake_case wire values', () => {
    expect(normalizeBracketKey('SellSide')).toBe('sell_side');
    expect(normalizeBracketKey('EventDriven')).toBe('event_driven');
    expect(normalizeBracketKey('Institutions')).toBe('institutions');
  });

  it('is idempotent on already-snake_case wire values', () => {
    expect(normalizeBracketKey('sell_side')).toBe('sell_side');
    expect(normalizeBracketKey('event_driven')).toBe('event_driven');
    expect(normalizeBracketKey('quants')).toBe('quants');
  });

  it('returns empty string for non-string input', () => {
    expect(normalizeBracketKey(null)).toBe('');
    expect(normalizeBracketKey(undefined)).toBe('');
    expect(normalizeBracketKey(42)).toBe('');
  });
});
