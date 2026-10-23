// Pure chart rows for the report modal, built from the backend's structured
// sections (never parsed from markdown).
import type { ConvergenceRow, InfluenceRow } from '../api/report';

export interface ConvergenceBar {
  label: string;
  buy: number;
  hold: number;
  sell: number;
  parseError: number;
  buyPct: number;
  holdPct: number;
  sellPct: number;
}

export function convergenceBars(rows: readonly ConvergenceRow[]): ConvergenceBar[] {
  return [...rows]
    .sort((a, b) => a.round_num - b.round_num)
    .map((row) => {
      const decided = row.buy_count + row.sell_count + row.hold_count;
      const pct = (n: number) => (decided > 0 ? (n / decided) * 100 : 0);
      return {
        label: `R${row.round_num}`,
        buy: row.buy_count,
        hold: row.hold_count,
        sell: row.sell_count,
        parseError: row.parse_error_count,
        buyPct: pct(row.buy_count),
        holdPct: pct(row.hold_count),
        sellPct: pct(row.sell_count),
      };
    });
}

export interface InfluenceBar {
  agentId: string;
  name: string;
  bracket: string;
  citations: number;
  sharePct: number;
  widthPct: number;
}

export function influenceBars(rows: readonly InfluenceRow[]): InfluenceBar[] {
  const top = rows.reduce((max, row) => Math.max(max, row.influence_share), 0);
  return rows.map((row) => ({
    agentId: row.agent_id,
    name: row.name,
    bracket: row.bracket,
    citations: row.citation_count,
    sharePct: row.influence_share * 100,
    widthPct: top > 0 ? (row.influence_share / top) * 100 : 0,
  }));
}
