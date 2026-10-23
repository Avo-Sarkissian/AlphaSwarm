import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import type { CycleItem } from '../../api/replay';
import { consensusOf, isSameLocalDay, mergeCycles, parseIsoInstant, summarizeCycles } from '../../lib/cycles';

const LEGACY: CycleItem = {
  cycle_id: 'legacy',
  created_at: '2026-10-03T08:00:00.000000000+00:00',
  seed_rumor: 'ZZZT Holdings is in late-stage talks to acquire QQQX Robotics for $4.2B in cash.',
  round_count: 3,
  status: 'complete',
  final_buy: null,
  final_sell: null,
  final_hold: null,
  total_flips: null,
  total_seconds: null,
  agent_count: null,
};
const metrics = (id: string, b: number, s: number, h: number, flips: number, secs: number): CycleItem => ({
  ...LEGACY,
  cycle_id: id,
  final_buy: b,
  final_sell: s,
  final_hold: h,
  total_flips: flips,
  total_seconds: secs,
  agent_count: b + s + h,
});

describe('consensusOf', () => {
  it('picks the leader with its share of decided agents', () => {
    expect(consensusOf(metrics('a', 60, 25, 10, 7, 754))).toEqual({ signal: 'buy', pct: 63 });
  });
  it('calls a tie mixed', () => expect(consensusOf(metrics('a', 40, 40, 15, 0, 1))?.signal).toBe('mixed'));
  it('is null when metrics were not recorded', () => expect(consensusOf(LEGACY)).toBeNull());
  it('is null when nobody decided', () => expect(consensusOf(metrics('a', 0, 0, 0, 0, 1))).toBeNull());
});

describe('summarizeCycles', () => {
  it('counts consensus and averages only cycles that recorded metrics', () => {
    expect(summarizeCycles([metrics('a', 60, 25, 10, 7, 754), metrics('b', 10, 70, 15, 3, 600), LEGACY])).toEqual({
      loaded: 3,
      buy: 1,
      sell: 1,
      hold: 0,
      mixed: 0,
      avgFlips: 5,
      avgSeconds: 677,
    });
  });
  it('has no averages without metrics', () => {
    expect(summarizeCycles([LEGACY])).toMatchObject({ avgFlips: null, avgSeconds: null });
  });
});

describe('time helpers', () => {
  const originalTz = process.env.TZ;
  beforeAll(() => {
    process.env.TZ = 'America/Los_Angeles';
  });
  afterAll(() => {
    if (originalTz === undefined) delete process.env.TZ;
    else process.env.TZ = originalTz;
  });

  it('parses the server timestamp with nanoseconds', () => {
    expect(parseIsoInstant('2026-10-03T12:34:56.123456789+00:00').toISOString()).toBe('2026-10-03T12:34:56.123Z');
  });

  it('compares local calendar days, not UTC date prefixes', () => {
    const now = new Date('2026-10-03T22:00:00Z'); // 15:00 on Oct 3 in Los Angeles
    expect(isSameLocalDay('2026-10-03T08:00:00.000000000+00:00', now)).toBe(true); // 01:00 Oct 3 local
    expect(isSameLocalDay('2026-10-03T03:00:00.000000000+00:00', now)).toBe(false); // 20:00 Oct 2 local
  });

  it('is false for an unparseable timestamp', () => expect(isSameLocalDay('not a date', new Date())).toBe(false));
});

describe('mergeCycles', () => {
  it('appends the next page without repeating the boundary row', () => {
    const a = metrics('a', 1, 0, 0, 0, 1);
    const b = metrics('b', 1, 0, 0, 0, 1);
    const c = metrics('c', 1, 0, 0, 0, 1);
    expect(mergeCycles([a, b], [b, c]).map((x) => x.cycle_id)).toEqual(['a', 'b', 'c']);
  });
});
