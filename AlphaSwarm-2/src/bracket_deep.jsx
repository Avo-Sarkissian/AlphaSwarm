// Bracket Deep-Dive — full-screen takeover showing bracket internals
const { useState: useBD, useMemo: useBM } = React;

const BRACKET_COLORS = {
  quants:'#6aa9ff', degens:'#ff5b6b', sovereigns:'#b080ff',
  macro:'#5be7b8', suits:'#ffb84d', insiders:'#ff9d5c',
  agents:'#8a93a0', doom_posters:'#ff4d7a', policy_wonks:'#42d690', whales:'#d4a843'
};

function BracketDeepDive({ bracket, agents, onClose, onAgentInterview }) {
  const members = useBM(() => agents.filter(a => a.bracket === bracket.bracket), [agents, bracket]);
  const [sortBy, setSortBy] = useBD('confidence');

  const sorted = useBM(() => [...members].sort((a,b) => {
    if (sortBy === 'confidence') return b.confidence - a.confidence;
    if (sortBy === 'signal') return (a.signal||'').localeCompare(b.signal||'');
    return a.id.localeCompare(b.id);
  }), [members, sortBy]);

  const buy  = members.filter(a => a.signal === 'buy').length;
  const sell = members.filter(a => a.signal === 'sell').length;
  const hold = members.filter(a => a.signal === 'hold').length;
  const total = members.length || 1;
  const flipped = members.filter(a => a.flipped).length;
  const avgConf = members.reduce((s,a) => s + a.confidence, 0) / total;

  // Confidence histogram buckets: 0-25, 25-50, 50-75, 75-100
  const buckets = [0,25,50,75].map(lo => ({
    lo, hi: lo+25,
    count: members.filter(a => a.confidence*100 >= lo && a.confidence*100 < lo+25).length
  }));
  const maxBucket = Math.max(...buckets.map(b => b.count), 1);

  const color = BRACKET_COLORS[bracket.bracket] || 'var(--accent)';
  const sigColor = s => s === 'buy' ? 'var(--buy)' : s === 'sell' ? 'var(--sell)' : 'var(--hold)';

  // Mock influence data per agent
  const influences = { 'Q-03': {out:31,in:4}, 'D-14':{out:2,in:6}, 'P-02':{out:22,in:3}, 'M-06':{out:14,in:5} };

  return (
    <div className="bd-takeover">
      <div className="bd-head">
        <button className="btn ghost-btn" onClick={onClose}><Icon name="close" /></button>
        <div className="bd-bracket-pill" style={{background: color, color:'#000'}}>{bracket.display_name}</div>
        <div className="bd-head-meta">
          <span className="label">{total} AGENTS</span>
          <span className="label">·</span>
          <span className="label" style={{color:'var(--buy)'}}>{buy} BUY</span>
          <span className="label" style={{color:'var(--sell)'}}>{sell} SELL</span>
          <span className="label" style={{color:'var(--hold)'}}>{hold} HOLD</span>
          <span className="label">·</span>
          <span className="label">{flipped} FLIPPED</span>
        </div>
      </div>

      <div className="bd-body">
        {/* Left: stats */}
        <div className="bd-left">
          {/* Signal distribution */}
          <div className="bd-stat-section">
            <div className="label" style={{marginBottom:10}}>SIGNAL DISTRIBUTION</div>
            <div className="bd-signal-bars">
              {[{sig:'buy',n:buy},{sig:'sell',n:sell},{sig:'hold',n:hold}].map(({sig,n}) => (
                <div key={sig} className="bd-sig-row">
                  <span className={`rationale-signal sig-${sig}`}>{sig.toUpperCase()}</span>
                  <div className="bd-sig-bar">
                    <div className="bd-sig-fill" style={{width:`${n/total*100}%`, background: sigColor(sig)}} />
                  </div>
                  <span className="mono" style={{fontSize:13, color: sigColor(sig)}}>{n}</span>
                  <span className="label">{(n/total*100).toFixed(0)}%</span>
                </div>
              ))}
            </div>
          </div>

          {/* Confidence histogram */}
          <div className="bd-stat-section">
            <div className="label" style={{marginBottom:10}}>CONFIDENCE HISTOGRAM</div>
            <div className="bd-histogram">
              {buckets.map(b => (
                <div key={b.lo} className="bd-hist-col">
                  <div className="bd-hist-bar-wrap">
                    <div className="bd-hist-bar" style={{
                      height: `${(b.count/maxBucket)*100}%`,
                      background: color,
                    }} />
                  </div>
                  <div className="bd-hist-label label">{b.lo}–{b.hi}%</div>
                  <div className="bd-hist-n mono">{b.count}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Summary stats */}
          <div className="bd-stat-section">
            <div className="bd-mini-stats">
              <BdStat label="AVG CONF" value={`${(avgConf*100).toFixed(0)}%`} />
              <BdStat label="FLIPPED" value={`${flipped}/${total}`} />
              <BdStat label="CONSENSUS" value={buy>=sell&&buy>=hold?'BUY':sell>=hold?'SELL':'HOLD'}
                tone={buy>=sell&&buy>=hold?'buy':sell>=hold?'sell':'hold'} />
            </div>
          </div>
        </div>

        {/* Right: agent roster */}
        <div className="bd-right">
          <div className="bd-roster-head">
            <span className="label">ROSTER · {total} AGENTS</span>
            <div className="bd-sort">
              <span className="label">SORT</span>
              {['confidence','signal','id'].map(s => (
                <button key={s} className="bd-sort-btn" data-active={sortBy===s} onClick={() => setSortBy(s)}>
                  {s.toUpperCase()}
                </button>
              ))}
            </div>
          </div>
          <div className="bd-roster">
            {sorted.map(a => {
              const inf = influences[a.id];
              return (
                <div key={a.id} className="bd-agent-row" onClick={() => onAgentInterview(a)}>
                  <div className="bd-agent-id mono" style={{color}}>{a.id}</div>
                  <div className={`bd-agent-sig rationale-signal sig-${a.signal}`}>{a.signal?.toUpperCase()}</div>
                  <div className="bd-agent-conf">
                    <div className="bd-conf-bar">
                      <div className="bd-conf-fill" style={{width:`${a.confidence*100}%`, background: sigColor(a.signal)}} />
                    </div>
                    <span className="mono" style={{fontSize:10}}>{(a.confidence*100).toFixed(0)}%</span>
                  </div>
                  {inf && (
                    <div className="bd-agent-inf label">
                      <span style={{color:'var(--accent)'}}>↗{inf.out}</span>
                      <span style={{color:'var(--text-3)'}}>↙{inf.in}</span>
                    </div>
                  )}
                  {a.flipped && <div className="bd-flip-tag label">FLIP</div>}
                  <div className="bd-agent-chat-icon"><Icon name="chat" size={12} /></div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

function BdStat({ label, value, tone }) {
  return (
    <div className="bd-mini-stat" data-tone={tone}>
      <div className="label">{label}</div>
      <div className="bd-mini-val">{value}</div>
    </div>
  );
}

Object.assign(window, { BracketDeepDive });
