// Advisory building blocks: a headline stat and one holding row.
import { evidenceLabel, sentimentWidths, type HoldingView } from '../../lib/advisoryView';

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

export function AdvHoldingRow({ h }: { h: HoldingView }) {
  const bar = sentimentWidths(h.swarmSentiment);
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
        {h.divergent && (
          <span
            className="adv-divergent-tag label"
            title={`Orchestrator read ${h.llmSignal}; swarm agents lean ${h.swarmSignal}`}
          >
            DIVERGES
          </span>
        )}
      </div>
      <div className="adv-qh-shares mono">{evidenceLabel(h)}</div>
      <div className="adv-qh-val mono" title="Cost basis, not market value">
        ${(h.costBasis / 1000).toFixed(0)}K
      </div>
      <div className="adv-qh-weight mono">{h.costBasisPct.toFixed(1)}%</div>
      <div
        className="adv-qh-sent-bar"
        title={h.swarmSentiment === null ? 'no swarm sentiment' : `swarm sentiment ${h.swarmSentiment.toFixed(2)}`}
      >
        <div className="adv-qs-neg" style={{ width: bar.neg }} />
        <div className="adv-qs-mid" />
        <div className="adv-qs-pos" style={{ width: bar.pos }} />
      </div>
      <div className={`adv-qh-signal mono sig-${h.signal.toLowerCase()}`}>{h.signal}</div>
      <div className={`adv-qh-rec adv-rec-${h.recTone}`}>{h.rec}</div>
    </div>
  );
}
