import { describe, expect, it } from 'vitest';
import type { AdvisoryItemPayload, AdvisoryReportPayload } from '../../api/advisory';
import {
  costBasisOf,
  evidenceLabel,
  holdingView,
  isPlaceholder,
  overviewStats,
  recLabel,
  sentimentWidths,
} from '../../lib/advisoryView';

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
  cost_basis_exposure: '1234.56',
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

describe('holdingView', () => {
  const grounded: AdvisoryItemPayload = {
    ticker: 'ZZZT', consensus_signal: 'BUY', confidence: 0.62, rationale_summary: 'LLM view',
    cost_basis_exposure: '1234.56', source: 'swarm', swarm_signal: 'BUY', swarm_support: 4,
    swarm_sentiment: 0.35, evidence_agent_ids: ['quants_01', 'quants_02', 'quants_03', 'quants_04'],
    llm_signal: 'SELL', divergent: true,
  };

  it('maps the swarm fields and the cost-basis share', () => {
    const view = holdingView(grounded, 2469.12);
    expect(view.costBasis).toBeCloseTo(1234.56);
    expect(view.costBasisPct).toBeCloseTo(50);
    expect([view.swarmSignal, view.llmSignal, view.divergent]).toEqual(['BUY', 'SELL', true]);
    expect(view.insufficientEvidence).toBe(false);
    expect(evidenceLabel(view)).toBe('4 agents · swarm BUY');
  });

  it('flags thin evidence without a swarm signal', () => {
    const view = holdingView({ ...grounded, swarm_signal: null, swarm_support: 2, divergent: false }, 0);
    expect(view.insufficientEvidence).toBe(true);
    expect(view.costBasisPct).toBe(0);
    expect(evidenceLabel(view)).toBe('2 agents · insufficient swarm evidence');
  });

  it('reads a legacy file that has position_exposure and no swarm fields', () => {
    const legacy: AdvisoryItemPayload = {
      ticker: 'QQQX', consensus_signal: 'HOLD', confidence: 0.3, rationale_summary: 'x', position_exposure: '617.28',
    };
    const view = holdingView(legacy, 617.28);
    expect(costBasisOf(legacy)).toBeCloseTo(617.28);
    expect([view.swarmSupport, view.swarmSignal, view.llmSignal, view.divergent]).toEqual([0, null, null, false]);
    expect(view.evidenceAgentIds).toEqual([]);
    expect(evidenceLabel(view)).toBe('no swarm evidence');
  });

  it('turns sentiment into bar widths', () => {
    expect(sentimentWidths(null)).toEqual({ neg: '0%', pos: '0%' });
    expect(sentimentWidths(0.5)).toEqual({ neg: '0%', pos: '25%' });
    expect(sentimentWidths(-1)).toEqual({ neg: '50%', pos: '0%' });
  });
});
