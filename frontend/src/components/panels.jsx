// Side panels — brackets list, rationale feed, KPI strip, bracket composition.
// Lifted from AlphaSwarm-2/src/panels.jsx (W2 Plan 41.6-02 task 1) and converted
// to native ES modules per D-03 (panel components were attached as globals
// before the conversion).

import { consensusLeader, tallySignals } from '../lib/tally';

export function BracketList({ summaries, onClick }) {
  const isEmpty =
    !summaries ||
    summaries.length === 0 ||
    summaries.every(s => (s?.total ?? 0) === 0);
  if (isEmpty) {
    return <div className="panel-empty">no brackets yet — waiting for first frame</div>;
  }
  return (
    <div>
      {summaries.map(s => {
        const bp = s.buy_count / Math.max(1, s.total);
        const sp = s.sell_count / Math.max(1, s.total);
        const hp = s.hold_count / Math.max(1, s.total);
        return (
          <div key={s.bracket} className="bracket-row" onClick={() => onClick && onClick(s)}>
            <span className="bracket-chip" style={{ background: 'var(--accent)' }} />
            <span className="bracket-name">{s.display_name}</span>
            <span className="bracket-count num">{s.total}</span>
            <div className="bracket-bar">
              <span className="b-buy"  style={{ width: `${bp*100}%` }} />
              <span className="b-sell" style={{ width: `${sp*100}%` }} />
              <span className="b-hold" style={{ width: `${hp*100}%` }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function RationaleFeed({ rationales, onAgentClick, onCiteClick }) {
  // Highlight entity-style words
  const render = (text) => {
    return text.split(/(\$[A-Z]+|\d+(?:\.\d+)?%|\b[A-Z]{2,5}\b|\$\d+[BMK]?)/g).map((frag, i) =>
      /^(\$[A-Z]+|\d+(?:\.\d+)?%|\b[A-Z]{2,5}\b|\$\d+[BMK]?)$/.test(frag)
        ? <span key={i} className="highlight">{frag}</span>
        : frag
    );
  };
  if (!rationales || rationales.length === 0) {
    return <div className="panel-empty">no rationales yet — agents thinking…</div>;
  }
  return (
    <div>
      {rationales.map((r, i) => (
        <div key={i} className="rationale-item">
          <div className="rationale-head">
            <span className="rationale-agent" onClick={() => onAgentClick && onAgentClick(r.agent)} style={{cursor:'pointer'}}>{r.agent}</span>
            <span className="rationale-bracket">{r.bracket}</span>
            <span className={`rationale-signal sig-${r.signal}`}>{r.signal.toUpperCase()}</span>
            <span className="rationale-round">R{r.round}</span>
          </div>
          <div className="rationale-body">
            {render(r.text)}
            {r.cites && r.cites.length > 0 && (
              <>
                {' '}
                {r.cites.map((c, j) => (
                  <span key={j} className="cite" onClick={() => onCiteClick && onCiteClick(c)}>↳ {c}</span>
                ))}
              </>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

export function KpiStrip({ agents, tps, mem, slots, slotsMax, elapsed, round }) {
  // Pending (null) and failed (parse_error) agents are never HOLD; the share is
  // over decided agents only (docs/DECISIONS.md#adr-streaming-state).
  const tally = tallySignals(agents);
  const lead = consensusLeader(tally);
  const failed = tally.parseError > 0 ? ` · ${tally.parseError} failed` : '';
  // Live governor slot budget (governor_metrics.current_slots) when present;
  // fall back to the design default of 16 before the first real frame.
  const slotCap = slotsMax > 0 ? slotsMax : 16;
  const memCls = mem >= 90 ? 'crit' : mem >= 80 ? 'warn' : '';
  const fmt = (s) => `${String(Math.floor(s/60)).padStart(2,'0')}:${String(s%60).padStart(2,'0')}`;
  return (
    <div className="kpi-strip">
      <div className="kpi">
        <span className="kpi-label">Consensus · {tally.decided}/{agents.length} decided{failed}</span>
        <span className="kpi-value">
          {lead.signal ? lead.signal.toUpperCase() : '—'}
          <small>{lead.signal ? `${lead.pct}%` : 'pending'}</small>
        </span>
        <div className="composition">
          <div className="comp-buy"  style={{ flex: tally.buy  }}>{tally.buy}</div>
          <div className="comp-sell" style={{ flex: tally.sell }}>{tally.sell}</div>
          <div className="comp-hold" style={{ flex: tally.hold }}>{tally.hold}</div>
        </div>
      </div>
      <div className="kpi">
        <span className="kpi-label">Tokens / sec</span>
        <span className="kpi-value">{tps.toFixed(1)}<small>tps</small></span>
        <div className="spark">
          {Array.from({length: 22}).map((_, i) => {
            const h = 6 + ((i*13 + Math.floor(tps))%16);
            return <span key={i} style={{ height: h }} className={i>17?'hi':''} />;
          })}
        </div>
      </div>
      <div className="kpi">
        <span className="kpi-label">Memory</span>
        <span className={`kpi-value ${memCls}`}>{mem}<small>%</small></span>
        <div className="kpi-bar"><span style={{ width: `${mem}%`, background: memCls === 'crit' ? 'var(--sell)' : memCls === 'warn' ? 'var(--accent)' : 'var(--buy)' }} /></div>
      </div>
      <div className="kpi">
        <span className="kpi-label">Parallel slots</span>
        <span className="kpi-value">{slots}<small>/{slotCap}</small></span>
        <div className="kpi-bar"><span style={{ width: `${slots/slotCap*100}%` }} /></div>
      </div>
      <div className="kpi">
        <span className="kpi-label">Elapsed · R{round}/3</span>
        <span className="kpi-value">{fmt(elapsed)}</span>
        <div className="kpi-bar"><span style={{ width: `${(round/3)*100}%` }} /></div>
      </div>
    </div>
  );
}

export function ConsensusRing({ agents }) {
  const tally = tallySignals(agents);
  const lead = consensusLeader(tally);
  // Arcs span the whole roster, so agents still thinking leave a visible gap.
  const total = Math.max(1, agents.length);
  const R = 48, C = 2 * Math.PI * R;
  const buyLen = (tally.buy/total)*C;
  const sellLen = (tally.sell/total)*C;
  const holdLen = (tally.hold/total)*C;
  const leadColor = lead.signal ? `var(--${lead.signal})` : 'var(--text-3)';
  return (
    <svg className="consensus-ring" viewBox="0 0 120 120">
      <circle cx="60" cy="60" r={R} fill="none" stroke="var(--border)" strokeWidth="8" />
      <g transform="rotate(-90 60 60)" fill="none" strokeWidth="8">
        <circle cx="60" cy="60" r={R} stroke="var(--buy)"  strokeDasharray={`${buyLen} ${C}`} />
        <circle cx="60" cy="60" r={R} stroke="var(--sell)" strokeDasharray={`${sellLen} ${C}`} strokeDashoffset={-buyLen} />
        <circle cx="60" cy="60" r={R} stroke="var(--hold)" strokeDasharray={`${holdLen} ${C}`} strokeDashoffset={-(buyLen+sellLen)} />
      </g>
      {/* The text block sits a little high: lower down, the ring's inner chord is
          too narrow for "100/100 decided" (it would run into the arcs). */}
      <text x="60" y="47" className="mid" fontSize="10" fill="var(--text-3)" letterSpacing="0.14em">CONSENSUS</text>
      <text x="60" y="64" className="mid" fontSize={lead.signal ? 18 : 13} fontWeight="700" fill={leadColor}>
        {lead.signal ? lead.signal.toUpperCase() : 'PENDING'}
      </text>
      <text x="60" y="77" className="mid" fontSize="10" fill="var(--text-2)">{lead.signal ? `${lead.pct}%` : '—'}</text>
      <text x="60" y="88" className="mid" fontSize="7" fill="var(--text-3)">{tally.decided}/{agents.length} decided</text>
    </svg>
  );
}
