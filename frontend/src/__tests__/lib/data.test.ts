// The one bracket registry, checked against the backend-generated
// fixtures/brackets.json (DEFAULT_BRACKETS, docs/DECISIONS.md#adr-swarm-composition-v2).
import { afterEach, describe, expect, it, vi } from 'vitest';
import { BRACKETS, bracketOf, bracketSpec, isBracketKey, toBracketKey } from '../../data';
import brackets from '../fixtures/brackets.json';

interface FixtureBracket {
  key: string;
  display_name: string;
  count: number;
  influence_weight_base: number;
}
const fixture = brackets as FixtureBracket[];

afterEach(() => vi.restoreAllMocks());

describe('BRACKETS registry vs backend DEFAULT_BRACKETS', () => {
  it('has the same keys in the same order', () => {
    expect(BRACKETS.map((b) => b.key)).toEqual(fixture.map((b) => b.key));
  });

  it('has the same display names and counts', () => {
    expect(BRACKETS.map((b) => [b.display, b.count])).toEqual(fixture.map((b) => [b.display_name, b.count]));
  });

  it('counts sum to 100', () => {
    expect(BRACKETS.reduce((n, b) => n + b.count, 0)).toBe(100);
  });

  it('gives every bracket a distinct hex color', () => {
    const colors = BRACKETS.map((b) => b.color);
    expect(new Set(colors).size).toBe(colors.length);
    for (const c of colors) expect(c).toMatch(/^#[0-9a-f]{6}$/);
  });

  it('carries each bracket reach (influence_weight_base)', () => {
    expect(BRACKETS.map((b) => b.reach)).toEqual(fixture.map((b) => b.influence_weight_base));
  });
});

describe('bracketOf', () => {
  it.each([
    ['institutions_01', 'institutions'],
    ['sell_side_03', 'sell_side'],
    ['event_driven_05', 'event_driven'],
    ['quants_12', 'quants'],
    ['degens_15', 'degens'],
    ['narrators_08', 'narrators'],
    ['algos_04', 'algos'],
    ['macro_07', 'macro'],
    ['shorts_06', 'shorts'],
    ['allocators_05', 'allocators'],
  ] as const)('maps %s -> %s', (id, key) => {
    expect(bracketOf(id)).toBe(key);
  });

  it("maps unknown ids to 'unknown' with one dev warning per id", () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    expect(bracketOf('whales_01')).toBe('unknown');
    expect(bracketOf('whales_01')).toBe('unknown');
    expect(bracketOf('Q-03')).toBe('unknown');
    expect(warn).toHaveBeenCalledTimes(2);
  });
});

describe('lookups', () => {
  it('finds a spec by key and rejects non-keys', () => {
    expect(bracketSpec('sell_side')?.display).toBe('Sell-Side');
    expect(bracketSpec('Sell-Side')).toBeUndefined(); // a display name is not a key
    expect(isBracketKey('macro')).toBe(true);
    expect(isBracketKey('Macro')).toBe(false);
  });

  it("toBracketKey maps non-keys to 'unknown'", () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    expect(toBracketKey('event_driven')).toBe('event_driven');
    expect(toBracketKey('suits')).toBe('unknown');
    expect(toBracketKey(undefined)).toBe('unknown');
  });
});
