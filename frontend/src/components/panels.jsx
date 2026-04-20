// Side panels — brackets list, rationale feed, KPI strip, bracket composition

export function BracketList({ summaries, onClick }) {
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

export function KpiStrip({ agents, tps, mem, slots, elapsed, round }) {
  const buy = agents.filter(a => a.signal === 'buy').length;
  const sell = agents.filter(a => a.signal === 'sell').length;
  const hold = agents.filter(a => a.signal === 'hold').length;
  const total = agents.length;
  const memCls = mem >= 90 ? 'crit' : mem >= 80 ? 'warn' : '';
  const fmt = (s) => `${String(Math.floor(s/60)).padStart(2,'0')}:${String(s%60).padStart(2,'0')}`;
  return (
    <div className="kpi-strip">
      <div className="kpi">
        <span className="kpi-label">Consensus</span>
        <span className="kpi-value">
          {buy >= sell && buy >= hold ? 'BUY' : sell >= hold ? 'SELL' : 'HOLD'}
          <small>{Math.round(Math.max(buy, sell, hold)/total*100)}%</small>
        </span>
        <div className="composition">
          <div className="comp-buy"  style={{ flex: buy  }}>{buy}</div>
          <div className="comp-sell" style={{ flex: sell }}>{sell}</div>
          <div className="comp-hold" style={{ flex: hold }}>{hold}</div>
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
        <span className="kpi-value">{slots}<small>/16</small></span>
        <div className="kpi-bar"><span style={{ width: `${slots/16*100}%` }} /></div>
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
  const buy = agents.filter(a => a.signal === 'buy').length;
  const sell = agents.filter(a => a.signal === 'sell').length;
  const hold = agents.filter(a => a.signal === 'hold').length;
  const total = Math.max(1, agents.length);
  const R = 48, C = 2 * Math.PI * R;
  const buyLen = (buy/total)*C;
  const sellLen = (sell/total)*C;
  const holdLen = (hold/total)*C;
  const leader = buy >= sell && buy >= hold ? 'BUY' : sell >= hold ? 'SELL' : 'HOLD';
  const leadPct = Math.round(Math.max(buy,sell,hold)/total*100);
  const leadColor = leader === 'BUY' ? 'var(--buy)' : leader === 'SELL' ? 'var(--sell)' : 'var(--hold)';
  return (
    <svg className="consensus-ring" viewBox="0 0 120 120">
      <circle cx="60" cy="60" r={R} fill="none" stroke="var(--border)" strokeWidth="8" />
      <g transform="rotate(-90 60 60)" fill="none" strokeWidth="8">
        <circle cx="60" cy="60" r={R} stroke="var(--buy)"  strokeDasharray={`${buyLen} ${C}`} />
        <circle cx="60" cy="60" r={R} stroke="var(--sell)" strokeDasharray={`${sellLen} ${C}`} strokeDashoffset={-buyLen} />
        <circle cx="60" cy="60" r={R} stroke="var(--hold)" strokeDasharray={`${holdLen} ${C}`} strokeDashoffset={-(buyLen+sellLen)} />
      </g>
      <text x="60" y="56" className="mid" fontSize="10" fill="var(--text-3)" letterSpacing="0.14em">CONSENSUS</text>
      <text x="60" y="72" className="mid" fontSize="18" fontWeight="700" fill={leadColor}>{leader}</text>
      <text x="60" y="86" className="mid" fontSize="10" fill="var(--text-2)">{leadPct}%</text>
    </svg>
  );
}
