import { describe, expect, it } from 'vitest';
import type { AdvisoryItemPayload, AdvisoryReportPayload } from '../../api/advisory';
import { isPlaceholder, overviewStats, recLabel } from '../../lib/advisoryView';

const item = (
  ticker: string,
  signal: 'BUY' | 'SELL' | 'HOLD',
  confidence: number,
  source?: 'swarm' | 'placeholder',
): AdvisoryItemPayload => ({
  ticker,
  consensus_signal: signal,
  confidence,
  rationale_summary: 'x',
  position_exposure: '1234.56',
  source,
});

describe('overviewStats', () => {
  it('uses the backend stats when present', () => {
    const report: AdvisoryReportPayload = {
      cycle_id: 'c',
      items: [item('ZZZT', 'BUY', 0.8, 'swarm'), item('QQQX', 'HOLD', 0.3, 'placeholder')],
      stats: {
        conviction_count: 1,
        placeholder_count: 1,
        buy_count: 1,
        sell_count: 0,
        hold_count: 0,
        avg_confidence: 0.8,
        dominant_signal: 'BUY',
        dominant_share: 1,
      },
    };
    expect(overviewStats(report)).toEqual({
      avgConfidence: 0.8,
      dominant: 'BUY',
      dominantPct: 100,
      convictionCount: 1,
      placeholderCount: 1,
    });
  });

  it('excludes placeholders when computing a report without stats', () => {
    const report: AdvisoryReportPayload = {
      cycle_id: 'c',
      items: [
        item('ZZZT', 'SELL', 0.6, 'swarm'),
        item('XQZW', 'BUY', 0.6, 'swarm'),
        item('QQQX', 'HOLD', 0.3, 'placeholder'),
      ],
      stats: null,
    };
    const stats = overviewStats(report);
    expect(stats.avgConfidence).toBeCloseTo(0.6);
    expect(stats.dominant).toBe('SELL'); // tie-break SELL > BUY > HOLD, as the backend
    expect([stats.convictionCount, stats.placeholderCount]).toEqual([2, 1]);
  });

  it('legacy report without stats or sources counts every item', () => {
    const report: AdvisoryReportPayload = { cycle_id: 'c', items: [item('ZZZT', 'HOLD', 0.5)] };
    expect(overviewStats(report)).toMatchObject({
      avgConfidence: 0.5,
      dominant: 'HOLD',
      dominantPct: 100,
    });
  });

  it('no conviction items means no averages', () => {
    const report: AdvisoryReportPayload = {
      cycle_id: 'c',
      items: [item('QQQX', 'HOLD', 0.3, 'placeholder')],
    };
    expect(overviewStats(report)).toMatchObject({ avgConfidence: null, dominant: null, dominantPct: 0 });
  });
});

describe('row helpers', () => {
  it('marks placeholders and labels recommendations', () => {
    expect(isPlaceholder(item('QQQX', 'HOLD', 0.3, 'placeholder'))).toBe(true);
    expect(isPlaceholder(item('ZZZT', 'BUY', 0.8))).toBe(false);
    expect([recLabel('BUY'), recLabel('SELL'), recLabel('HOLD')]).toEqual([
      'CONSIDER ADDING',
      'CONSIDER TRIMMING',
      'NO ACTION',
    ]);
  });
});
