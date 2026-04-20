// Cycle History — list of past cycles, compare mode.
// Full-screen takeover triggered from topbar.
// WAVE-1-NOTE: CYCLE_ARCHIVE remains an inline local constant per plan.
// Plan 03 wires this module to /api/replay/cycles (see HistoryContext work).
// The data here is UI-scaffolding to keep the shell renderable until then.
import { useState, useMemo } from 'react';
import { Icon } from './icons';

// Mock cycle archive
const CYCLE_ARCHIVE = [
  { id: 'C_2026_0418_A1', date: '2026-04-18 09:42', seed: 'Apple acquiring Anthropic for $500B', consensus: 'SELL', pct: 58, flips: 18, dur: '4:18', shocks: 0, starred: true },
  { id: 'C_2026_0418_A0', date: '2026-04-18 08:12', seed: 'Fed cuts 50bp at emergency session', consensus: 'BUY', pct: 71, flips: 24, dur: '3:52', shocks: 1, starred: false },
  { id: 'C_2026_0417_B2', date: '2026-04-17 16:30', seed: 'NVDA earnings beat, forward guidance cut 12%', consensus: 'SELL', pct: 47, flips: 15, dur: '4:02', shocks: 0, starred: true },
  { id: 'C_2026_0417_B1', date: '2026-04-17 11:15', seed: 'Treasury yields spike 40bp on inflation print', consensus: 'SELL', pct: 64, flips: 22, dur: '3:44', shocks: 0, starred: false },
  { id: 'C_2026_0417_A3', date: '2026-04-17 09:08', seed: 'DOJ files antitrust complaint against Apple-Anthropic', consensus: 'SELL', pct: 73, flips: 31, dur: '4:51', shocks: 1, starred: true },
  { id: 'C_2026_0416_B1', date: '2026-04-16 15:22', seed: 'OpenAI announces $40B secondary at $500B valuation', consensus: 'HOLD', pct: 42, flips: 11, dur: '3:28', shocks: 0, starred: false },
  { id: 'C_2026_0416_A2', date: '2026-04-16 10:47', seed: 'BOJ unexpectedly raises rates 25bp', consensus: 'SELL', pct: 55, flips: 19, dur: '4:07', shocks: 0, starred: false },
  { id: 'C_2026_0416_A1', date: '2026-04-16 09:03', seed: 'Microsoft internal memo leaks — AI capex cut 30%', consensus: 'SELL', pct: 68, flips: 27, dur: '4:34', shocks: 1, starred: false },
  { id: 'C_2026_0415_B3', date: '2026-04-15 17:44', seed: 'Ethereum ETF approval granted by SEC', consensus: 'BUY', pct: 61, flips: 17, dur: '3:38', shocks: 0, starred: false },
  { id: 'C_2026_0415_B2', date: '2026-04-15 14:12', seed: 'Taiwan earthquake 7.2 magnitude, TSMC fab offline', consensus: 'SELL', pct: 81, flips: 38, dur: '5:02', shocks: 2, starred: true },
  { id: 'C_2026_0415_A1', date: '2026-04-15 08:55', seed: 'Anthropic denies Apple acquisition talks', consensus: 'BUY', pct: 52, flips: 14, dur: '3:49', shocks: 0, starred: false },
  { id: 'C_2026_0414_B2', date: '2026-04-14 16:18', seed: 'China announces rare-earth export restrictions', consensus: 'SELL', pct: 59, flips: 21, dur: '4:15', shocks: 0, starred: false },
  { id: 'C_2026_0414_B1', date: '2026-04-14 11:02', seed: 'Tesla robotaxi launch delayed to 2027', consensus: 'SELL', pct: 48, flips: 13, dur: '3:31', shocks: 0, starred: false },
  { id: 'C_2026_0413_A1', date: '2026-04-13 10:30', seed: 'Ukraine ceasefire announced, effective Monday', consensus: 'BUY', pct: 66, flips: 20, dur: '3:58', shocks: 0, starred: true },
];

export function CycleHistory({ onClose, onOpenReport }) {
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('all'); // all | starred | today
  const [selected, setSelected] = useState(new Set());
  const [compareOpen, setCompareOpen] = useState(false);

  const filtered = useMemo(() => {
    return CYCLE_ARCHIVE.filter(c => {
      if (filter === 'starred' && !c.starred) return false;
      if (filter === 'today' && !c.date.startsWith('2026-04-18')) return false;
      if (query && !c.seed.toLowerCase().includes(query.toLowerCase()) && !c.id.toLowerCase().includes(query.toLowerCase())) return false;
      return true;
    });
  }, [query, filter]);

  const toggleSelect = (id) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else if (next.size < 2) next.add(id);
      return next;
    });
  };

  const compareA = [...selected][0];
  const compareB = [...selected][1];

  // stats
  const stats = useMemo(() => {
    const total = CYCLE_ARCHIVE.length;
    const sell = CYCLE_ARCHIVE.filter(c => c.consensus === 'SELL').length;
    const buy  = CYCLE_ARCHIVE.filter(c => c.consensus === 'BUY').length;
    const hold = CYCLE_ARCHIVE.filter(c => c.consensus === 'HOLD').length;
    const avgFlips = Math.round(CYCLE_ARCHIVE.reduce((a,c) => a+c.flips, 0) / total);
    return { total, sell, buy, hold, avgFlips };
  }, []);

  return (
    <div className="ch-takeover">
      <div className="ch-head">
        <div className="ch-head-left">
          <button className="btn ghost-btn" onClick={onClose} title="Back to dashboard">
            <Icon name="close" />
          </button>
          <span className="ch-title">Cycle History</span>
          <span className="label ch-count">{filtered.length} OF {CYCLE_ARCHIVE.length}</span>
        </div>
        <div className="ch-head-right">
          <div className="ch-search">
            <Icon name="search" size={13} />
            <input placeholder="Filter by seed or cycle ID…"
                   value={query} onChange={e => setQuery(e.target.value)} />
          </div>
          <div className="seg ch-filter">
            <button data-active={filter==='all'} onClick={() => setFilter('all')}>All</button>
            <button data-active={filter==='today'} onClick={() => setFilter('today')}>Today</button>
            <button data-active={filter==='starred'} onClick={() => setFilter('starred')}>Starred</button>
          </div>
        </div>
      </div>

      {/* summary strip */}
      <div className="ch-summary">
        <ChStat label="TOTAL CYCLES" value={stats.total} />
        <ChStat label="SELL CONSENSUS" value={stats.sell} sub={`${Math.round(stats.sell/stats.total*100)}%`} tone="sell" />
        <ChStat label="BUY CONSENSUS"  value={stats.buy}  sub={`${Math.round(stats.buy/stats.total*100)}%`}  tone="buy" />
        <ChStat label="HOLD"           value={stats.hold} sub={`${Math.round(stats.hold/stats.total*100)}%`} tone="hold" />
        <ChStat label="AVG FLIPS"      value={stats.avgFlips} sub="per cycle" />
        <div className="ch-compare-cta">
          {selected.size === 0 && (
            <span className="label" style={{color: 'var(--text-3)'}}>Select two cycles to compare</span>
          )}
          {selected.size === 1 && (
            <span className="label" style={{color: 'var(--accent)'}}>1 selected · pick one more</span>
          )}
          {selected.size === 2 && (
            <button className="btn primary" onClick={() => setCompareOpen(true)}>
              <Icon name="graph" /> Compare {compareA} vs {compareB}
            </button>
          )}
          {selected.size > 0 && (
            <button className="btn ghost" onClick={() => setSelected(new Set())} title="Clear selection" style={{marginLeft: 6}}>Clear</button>
          )}
        </div>
      </div>

      {/* table */}
      <div className="ch-table-wrap">
        <div className="ch-row ch-row-head">
          <div></div>
          <div className="label">CYCLE ID</div>
          <div className="label">DATE</div>
          <div className="label">SEED</div>
          <div className="label" style={{textAlign:'center'}}>CONSENSUS</div>
          <div className="label" style={{textAlign:'right'}}>FLIPS</div>
          <div className="label" style={{textAlign:'right'}}>DURATION</div>
          <div className="label" style={{textAlign:'center'}}>SHOCKS</div>
          <div></div>
        </div>
        {filtered.map(c => {
          const isSel = selected.has(c.id);
          return (
            <div key={c.id} className="ch-row" data-selected={isSel}>
              <button className="ch-check" data-checked={isSel} onClick={() => toggleSelect(c.id)} title="Select for compare">
                {isSel && <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M1 5 L4 8 L9 2"/></svg>}
              </button>
              <div className="ch-id mono" onClick={() => onOpenReport(c)}>
                {c.starred && <span className="ch-star">★</span>}
                {c.id}
              </div>
              <div className="ch-date mono">{c.date}</div>
              <div className="ch-seed" onClick={() => onOpenReport(c)} title={c.seed}>"{c.seed}"</div>
              <div className="ch-consensus">
                <span className="ch-pill" data-tone={c.consensus.toLowerCase()}>{c.consensus} {c.pct}%</span>
              </div>
              <div className="ch-flips mono">{c.flips}</div>
              <div className="ch-dur mono">{c.dur}</div>
              <div className="ch-shocks">{c.shocks > 0 ? <span className="ch-shock-pill">⚡ {c.shocks}</span> : <span className="ch-dash">—</span>}</div>
              <button className="ch-open-btn" onClick={() => onOpenReport(c)} title="Open report">
                <Icon name="doc" />
              </button>
            </div>
          );
        })}
      </div>

      {compareOpen && compareA && compareB && (
        <CompareModal a={compareA} b={compareB} onClose={() => setCompareOpen(false)} />
      )}
    </div>
  );
}

function ChStat({ label, value, sub, tone }) {
  return (
    <div className="ch-stat" data-tone={tone || 'default'}>
      <div className="label">{label}</div>
      <div className="ch-stat-v">{value}</div>
      {sub && <div className="ch-stat-sub mono">{sub}</div>}
    </div>
  );
}

// Compare two cycles side-by-side
export function CompareModal({ a, b, onClose }) {
  const cA = CYCLE_ARCHIVE.find(c => c.id === a);
  const cB = CYCLE_ARCHIVE.find(c => c.id === b);
  if (!cA || !cB) return null;

  const roundsA = [
    { r: 'R1', buy: 44, sell: 31, hold: 25 },
    { r: 'R2', buy: 32, sell: 45, hold: 23 },
    { r: 'R3', buy: 22, sell: 58, hold: 20 },
  ];
  const roundsB = [
    { r: 'R1', buy: 38, sell: 29, hold: 33 },
    { r: 'R2', buy: 45, sell: 28, hold: 27 },
    { r: 'R3', buy: 71, sell: 14, hold: 15 },
  ];

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal ch-compare" onClick={e => e.stopPropagation()}>
        <div className="rv2-head">
          <div className="rv2-head-left">
            <Icon name="graph" size={14} />
            <span className="label">CYCLE COMPARISON</span>
          </div>
          <div className="rv2-head-right">
            <button className="btn ghost" onClick={onClose}><Icon name="close" /></button>
          </div>
        </div>
        <div className="ch-compare-body">
          <div className="ch-compare-col">
            <div className="label">CYCLE A</div>
            <div className="ch-compare-id mono">{cA.id}</div>
            <div className="ch-compare-seed">"{cA.seed}"</div>
            <div className="ch-compare-consensus">
              <span className="ch-pill" data-tone={cA.consensus.toLowerCase()}>{cA.consensus} {cA.pct}%</span>
            </div>
            <MiniFlow rounds={roundsA} />
            <div className="ch-compare-meta">
              <div><span className="label">FLIPS</span> <span className="mono">{cA.flips}</span></div>
              <div><span className="label">DURATION</span> <span className="mono">{cA.dur}</span></div>
              <div><span className="label">SHOCKS</span> <span className="mono">{cA.shocks}</span></div>
            </div>
          </div>

          <div className="ch-compare-divider">
            <span className="ch-compare-vs">vs</span>
          </div>

          <div className="ch-compare-col">
            <div className="label">CYCLE B</div>
            <div className="ch-compare-id mono">{cB.id}</div>
            <div className="ch-compare-seed">"{cB.seed}"</div>
            <div className="ch-compare-consensus">
              <span className="ch-pill" data-tone={cB.consensus.toLowerCase()}>{cB.consensus} {cB.pct}%</span>
            </div>
            <MiniFlow rounds={roundsB} />
            <div className="ch-compare-meta">
              <div><span className="label">FLIPS</span> <span className="mono">{cB.flips}</span></div>
              <div><span className="label">DURATION</span> <span className="mono">{cB.dur}</span></div>
              <div><span className="label">SHOCKS</span> <span className="mono">{cB.shocks}</span></div>
            </div>
          </div>
        </div>

        <div className="ch-compare-notes">
          <div className="label" style={{marginBottom: 8, color:'var(--accent)'}}>DIVERGENCE</div>
          <p>
            Cycle A converged <b style={{color: 'var(--sell)'}}>SELL 58%</b> from a fragmented R1, driven by compute-scarcity rationale in Quants bracket.
            Cycle B converged <b style={{color: 'var(--buy)'}}>BUY 71%</b> instead — the Anthropic denial removed the uncertainty premium.
            Both cycles saw high Round 1→2 churn, but the signal <em>direction</em> inverted.
          </p>
        </div>
      </div>
    </div>
  );
}

function MiniFlow({ rounds }) {
  return (
    <div className="ch-miniflow">
      {rounds.map(r => (
        <div key={r.r} className="ch-miniflow-col">
          <div className="ch-miniflow-bar">
            <div className="cv-seg buy"  style={{height: `${r.buy}%`}}><span className="cv-n">{r.buy}</span></div>
            <div className="cv-seg hold" style={{height: `${r.hold}%`}}><span className="cv-n">{r.hold}</span></div>
            <div className="cv-seg sell" style={{height: `${r.sell}%`}}><span className="cv-n">{r.sell}</span></div>
          </div>
          <div className="ch-miniflow-r label">{r.r}</div>
        </div>
      ))}
    </div>
  );
}
