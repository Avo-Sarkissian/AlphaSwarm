// Pure advisory view helpers. Stats come from the backend (conviction items only);
// files written before that existed are computed here, still excluding placeholders.
import type { AdvisoryItemPayload, AdvisoryReportPayload, AdvisorySignal } from '../api/advisory';

// Tie-break order for the dominant signal, matching the backend.
const DOMINANCE_ORDER: readonly AdvisorySignal[] = ['SELL', 'BUY', 'HOLD'];

export interface OverviewStats {
  avgConfidence: number | null;
  dominant: AdvisorySignal | null;
  dominantPct: number;
  convictionCount: number;
  placeholderCount: number;
}

export function isPlaceholder(item: AdvisoryItemPayload): boolean {
  return item.source === 'placeholder';
}

export function recLabel(signal: AdvisorySignal): string {
  if (signal === 'BUY') return 'CONSIDER ADDING';
  if (signal === 'SELL') return 'CONSIDER TRIMMING';
  return 'NO ACTION';
}

export function overviewStats(report: AdvisoryReportPayload): OverviewStats {
  const stats = report.stats;
  if (stats) {
    return {
      avgConfidence: stats.avg_confidence,
      dominant: stats.dominant_signal,
      dominantPct: stats.dominant_share === null ? 0 : Math.round(stats.dominant_share * 100),
      convictionCount: stats.conviction_count,
      placeholderCount: stats.placeholder_count,
    };
  }
  const items = report.items ?? [];
  const conviction = items.filter((item) => !isPlaceholder(item));
  const counts: Record<AdvisorySignal, number> = { BUY: 0, SELL: 0, HOLD: 0 };
  for (const item of conviction) counts[item.consensus_signal] += 1;
  let dominant: AdvisorySignal | null = null;
  if (conviction.length > 0) {
    for (const signal of DOMINANCE_ORDER) {
      if (dominant === null || counts[signal] > counts[dominant]) dominant = signal;
    }
  }
  return {
    avgConfidence: conviction.length
      ? conviction.reduce((sum, item) => sum + item.confidence, 0) / conviction.length
      : null,
    dominant,
    dominantPct: dominant === null ? 0 : Math.round((counts[dominant] / conviction.length) * 100),
    convictionCount: conviction.length,
    placeholderCount: items.length - conviction.length,
  };
}

// Per-holding view of the grounded advisory (docs/DECISIONS.md#adr-grounded-advisory).
export interface HoldingView {
  ticker: string;
  signal: AdvisorySignal;
  recTone: 'buy' | 'sell' | 'hold';
  rec: string;
  rationale: string;
  costBasis: number;
  costBasisPct: number;
  swarmSupport: number;
  swarmSignal: AdvisorySignal | null;
  swarmSentiment: number | null;
  llmSignal: AdvisorySignal | null;
  divergent: boolean;
  evidenceAgentIds: readonly string[];
  insufficientEvidence: boolean;
  placeholder: boolean;
  risk: string | null;
  upside: string | null;
}

export function costBasisOf(item: AdvisoryItemPayload): number {
  const value = Number(item.cost_basis_exposure ?? item.position_exposure ?? 0);
  return Number.isFinite(value) ? value : 0;
}

export function holdingView(item: AdvisoryItemPayload, totalCostBasis: number): HoldingView {
  const costBasis = costBasisOf(item);
  const swarmSupport = item.swarm_support ?? 0;
  const swarmSignal = item.swarm_signal ?? null;
  return {
    ticker: item.ticker,
    signal: item.consensus_signal,
    recTone: item.consensus_signal.toLowerCase() as 'buy' | 'sell' | 'hold',
    rec: recLabel(item.consensus_signal),
    rationale: item.rationale_summary,
    costBasis,
    costBasisPct: totalCostBasis > 0 ? (costBasis / totalCostBasis) * 100 : 0,
    swarmSupport,
    swarmSignal,
    swarmSentiment: item.swarm_sentiment ?? null,
    llmSignal: item.llm_signal ?? null,
    divergent: item.divergent ?? false,
    evidenceAgentIds: item.evidence_agent_ids ?? [],
    insufficientEvidence: swarmSupport > 0 && swarmSignal === null,
    placeholder: isPlaceholder(item),
    risk: item.risk ?? null,
    upside: item.upside ?? null,
  };
}

export function evidenceLabel(view: HoldingView): string {
  if (view.swarmSignal !== null) return `${view.swarmSupport} agents · swarm ${view.swarmSignal}`;
  if (view.swarmSupport > 0) {
    return `${view.swarmSupport} agent${view.swarmSupport === 1 ? '' : 's'} · insufficient swarm evidence`;
  }
  return 'no swarm evidence';
}

export function sentimentWidths(sentiment: number | null): { neg: string; pos: string } {
  if (sentiment === null) return { neg: '0%', pos: '0%' };
  const clamped = Math.max(-1, Math.min(1, sentiment));
  return { neg: `${Math.max(0, -clamped) * 50}%`, pos: `${Math.max(0, clamped) * 50}%` };
}
