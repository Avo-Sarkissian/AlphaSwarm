// Report charts drawn from the backend's structured report sections.
import { useMemo } from 'react';
import type { ConvergenceRow, InfluenceRow } from '../../api/report';
import { convergenceBars, influenceBars } from '../../lib/reportSections';

export function ConvergenceFlow({ rows }: { rows: ConvergenceRow[] }) {
  const bars = useMemo(() => convergenceBars(rows), [rows]);
  return (
    <div className="cv-flow">
      {bars.map((bar) => (
        <div key={bar.label} className="cv-col">
          <div className="cv-bar">
            <div className="cv-seg buy" style={{ height: `${bar.buyPct}%` }}>
              <span className="cv-n">{bar.buy}</span>
            </div>
            <div className="cv-seg hold" style={{ height: `${bar.holdPct}%` }}>
              <span className="cv-n">{bar.hold}</span>
            </div>
            <div className="cv-seg sell" style={{ height: `${bar.sellPct}%` }}>
              <span className="cv-n">{bar.sell}</span>
            </div>
          </div>
          <div className="cv-r label">{bar.label}</div>
        </div>
      ))}
      <div className="cv-legend">
        <div>
          <span className="cv-dot buy" /> BUY
        </div>
        <div>
          <span className="cv-dot hold" /> HOLD
        </div>
        <div>
          <span className="cv-dot sell" /> SELL
        </div>
      </div>
    </div>
  );
}

export function InfluenceChart({ rows }: { rows: InfluenceRow[] }) {
  const bars = useMemo(() => influenceBars(rows), [rows]);
  return (
    <div className="infl-chart">
      {bars.map((bar) => (
        <div key={bar.agentId} className="infl-row">
          <span className="infl-id mono">{bar.agentId}</span>
          <span className="infl-bracket label">{bar.bracket}</span>
          <div className="infl-bar-wrap">
            <div className="infl-bar" style={{ width: `${bar.widthPct}%` }} />
          </div>
          <span className="infl-n mono">
            {bar.citations} · {bar.sharePct.toFixed(1)}%
          </span>
        </div>
      ))}
    </div>
  );
}
