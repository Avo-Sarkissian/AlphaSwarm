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
