import { describe, expect, it } from 'vitest';
import { extractSubject, interleaveBySource, stripSubject } from '../../features/wire/wireFormat';

describe('wireFormat', () => {
  it('pulls the ticker out of both provider query shapes', () => {
    expect(extractSubject('ZZZT OHLCV', 'yfinance')).toBe('ZZZT');
    expect(extractSubject('headlines:qqqx', 'rss')).toBe('QQQX');
  });

  it('falls back to the source label when the query has no subject', () => {
    expect(extractSubject('', 'rss')).toBe('RSS');
    expect(extractSubject('', 'someprovider')).toBe('SOMEPROVIDER');
  });

  it('drops the subject from the query text', () => {
    expect(stripSubject('ZZZT OHLCV')).toBe('OHLCV');
    expect(stripSubject('headlines:ZZZT')).toBe('headlines');
    expect(stripSubject('ZZZT')).toBe('ZZZT');
  });

  it('round-robins sources, keeping order within a source', () => {
    const entries = [
      { source: 'yfinance', id: 1 },
      { source: 'yfinance', id: 2 },
      { source: 'rss', id: 3 },
      { source: 'yfinance', id: 4 },
    ];
    expect(interleaveBySource(entries).map((e) => e.id)).toEqual([1, 3, 2, 4]);
  });
});
