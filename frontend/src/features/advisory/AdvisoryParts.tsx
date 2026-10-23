// Advisory building blocks: a headline stat and one holding row.


export interface HoldingAnalysis {
  ticker: string;
  swarmSignal: 'BUY' | 'SELL' | 'HOLD';
  recTone: 'buy' | 'sell' | 'hold';
  rec: string;
  rationale: string;
  value: number;
  weight: number;
  agents: number;
  shares: string | null;
  basis: string | null;
  last: string | null;
  sentiment: number;
  risk: string | null;
  upside: string | null;
  placeholder: boolean;
}

export function AdvStat({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: 'buy' | 'sell' | 'hold';
}) {
  return (
    <div className="adv-stat" data-tone={tone}>
      <div className="label">{label}</div>
      <div className="adv-stat-v">{value}</div>
      {sub && <div className="adv-stat-sub">{sub}</div>}
    </div>
  );
}

export function AdvHoldingRow({
  h,
  totalValue,
}: {
  h: HoldingAnalysis;
  totalValue: number;
}) {
  // Sentiment is stubbed (docs/DECISIONS.md#kr-41-6-01): render the midline bar.
  return (
    <div className="adv-qh-row">
      <div className="adv-qh-ticker">
        {h.ticker}
        {h.placeholder && (
          <span
            className="adv-placeholder-tag label"
            title="No strong swarm view this cycle; shown as HOLD placeholder"
          >
            PLACEHOLDER
          </span>
        )}
      </div>
      <div className="adv-qh-shares mono">{h.shares ?? '—'} sh</div>
      <div className="adv-qh-val mono">${(h.value / 1000).toFixed(0)}K</div>
      <div className="adv-qh-weight mono">
        {totalValue > 0 ? ((h.value / totalValue) * 100).toFixed(1) : '0.0'}%
      </div>
      <div className="adv-qh-sent-bar">
        <div className="adv-qs-neg" style={{ width: '0%' }} />
        <div className="adv-qs-mid" />
        <div className="adv-qs-pos" style={{ width: '0%' }} />
      </div>
      <div className={`adv-qh-signal mono sig-${h.swarmSignal.toLowerCase()}`}>
        {h.swarmSignal}
      </div>
      <div className={`adv-qh-rec adv-rec-${h.recTone}`}>{h.rec}</div>
    </div>
  );
}
