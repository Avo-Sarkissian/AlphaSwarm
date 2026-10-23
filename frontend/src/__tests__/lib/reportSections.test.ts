import { describe, expect, it } from 'vitest';
import type { ConvergenceRow, InfluenceRow } from '../../api/report';
import { convergenceBars, influenceBars } from '../../lib/reportSections';

const ROWS: ConvergenceRow[] = [
  { round_num: 2, buy_count: 48, sell_count: 24, hold_count: 26, parse_error_count: 2, total: 100 },
  { round_num: 1, buy_count: 40, sell_count: 30, hold_count: 28, parse_error_count: 2, total: 100 },
];

describe('convergenceBars', () => {
  it('sorts by round and takes shares over decided agents', () => {
    const bars = convergenceBars(ROWS);
    expect(bars.map((b) => b.label)).toEqual(['R1', 'R2']);
    expect(bars[0].buyPct + bars[0].sellPct + bars[0].holdPct).toBeCloseTo(100);
    expect(bars[0].buyPct).toBeCloseTo((40 / 98) * 100);
    expect(bars[0].parseError).toBe(2);
  });

  it('handles a round where every agent failed', () => {
    const [bar] = convergenceBars([
      { round_num: 1, buy_count: 0, sell_count: 0, hold_count: 0, parse_error_count: 100, total: 100 },
    ]);
    expect([bar.buyPct, bar.sellPct, bar.holdPct]).toEqual([0, 0, 0]);
  });
});

describe('influenceBars', () => {
  it('scales widths to the top share and keeps citations', () => {
    const rows: InfluenceRow[] = [
      { agent_id: 'sell_side_03', name: 'Sell-Side 3', bracket: 'sell_side', citation_count: 9, influence_share: 0.09 },
      { agent_id: 'narrators_01', name: 'Narrators 1', bracket: 'narrators', citation_count: 6, influence_share: 0.06 },
    ];
    const bars = influenceBars(rows);
    expect(bars[0]).toMatchObject({ agentId: 'sell_side_03', citations: 9, widthPct: 100 });
    expect(bars[1].widthPct).toBeCloseTo(66.67, 1);
    expect(bars[1].sharePct).toBeCloseTo(6);
  });

  it('returns zero widths when nobody was cited', () => {
    expect(influenceBars([{ agent_id: 'a_01', name: 'A 1', bracket: 'a', citation_count: 0, influence_share: 0 }])[0].widthPct).toBe(0);
  });
});
