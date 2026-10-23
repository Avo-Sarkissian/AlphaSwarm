import type { CycleItem } from '../api/replay';

export type CycleConsensus = { signal: 'buy' | 'sell' | 'hold' | 'mixed'; pct: number };

/** Final-round leader and its share of decided agents; null when not recorded or nobody decided. */
export function consensusOf(c: Pick<CycleItem, 'final_buy' | 'final_sell' | 'final_hold'>): CycleConsensus | null {
  const { final_buy: buy, final_sell: sell, final_hold: hold } = c;
  if (buy === null || sell === null || hold === null) return null;
  const decided = buy + sell + hold;
  if (decided <= 0) return null;
  const top = Math.max(buy, sell, hold);
  const counts = { buy, sell, hold };
  const leaders = (['buy', 'sell', 'hold'] as const).filter((k) => counts[k] === top);
  const [first] = leaders;
  return { signal: leaders.length === 1 && first ? first : 'mixed', pct: Math.round((top / decided) * 100) };
}

export interface CycleSummary {
  loaded: number;
  buy: number;
  sell: number;
  hold: number;
  mixed: number;
  avgFlips: number | null;
  avgSeconds: number | null;
}

export function summarizeCycles(cycles: readonly CycleItem[]): CycleSummary {
  const summary: CycleSummary = { loaded: cycles.length, buy: 0, sell: 0, hold: 0, mixed: 0, avgFlips: null, avgSeconds: null };
  let flips = 0;
  let flipsN = 0;
  let seconds = 0;
  let secondsN = 0;
  for (const c of cycles) {
    const signal = consensusOf(c)?.signal;
    if (signal) summary[signal] += 1;
    if (c.total_flips !== null) {
      flips += c.total_flips;
      flipsN += 1;
    }
    if (c.total_seconds !== null) {
      seconds += c.total_seconds;
      secondsN += 1;
    }
  }
  summary.avgFlips = flipsN > 0 ? flips / flipsN : null;
  summary.avgSeconds = secondsN > 0 ? seconds / secondsN : null;
  return summary;
}

/** Neo4j returns 9 fractional digits; some engines only parse 3. */
export function parseIsoInstant(iso: string): Date {
  return new Date(iso.replace(/(\.\d{3})\d+/, '$1'));
}

export function isSameLocalDay(iso: string, now: Date): boolean {
  const d = parseIsoInstant(iso);
  if (Number.isNaN(d.getTime())) return false;
  return d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && d.getDate() === now.getDate();
}

export function mergeCycles(prev: readonly CycleItem[], next: readonly CycleItem[]): CycleItem[] {
  const seen = new Set(prev.map((c) => c.cycle_id));
  return [...prev, ...next.filter((c) => !seen.has(c.cycle_id))];
}
