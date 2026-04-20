// Cycle History — list of past cycles, compare mode.
// Full-screen takeover triggered from topbar.
//
// Plan 04 wiring: fetches /api/replay/cycles via listCycles(). The list
// endpoint returns only { cycle_id, created_at, seed_rumor, round_count }
// — consensus/flips/duration/shocks columns render em-dash placeholders
// under KR-41.1-07 (reviewer item 20 column parity deviation).
import { useEffect, useMemo, useState } from 'react';
import { Icon } from './icons';
import { listCycles } from '../api/replay';

export function CycleHistory({ onClose, onOpenReport }) {
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('all'); // all | today
  const [selected, setSelected] = useState(new Map()); // cycle_id -> CycleItem
  const [compareOpen, setCompareOpen] = useState(false);
  const [cycles, setCycles] = useState(null); // null = loading
  const [loadError, setLoadError] = useState(null);

  // Plan 04: live fetch from /api/replay/cycles. KR-41.1-08 error handling:
  // console.error for operator visibility + surfaced label.
  useEffect(() => {
    let cancelled = false;
    listCycles()
      .then((cs) => {
        if (!cancelled) setCycles(cs);
      })
      .catch((e) => {
        if (cancelled) return;
        // KR-41.1-08: structured error stream not yet exposed; log+display.
        console.error('listCycles failed', e);
        setLoadError(e);
        setCycles([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const todayIso = useMemo(() => new Date().toISOString().slice(0, 10), []);

  const filtered = useMemo(() => {
    return (cycles ?? []).filter((c) => {
      if (filter === 'today' && !c.created_at.startsWith(todayIso)) return false;
      if (
        query &&
        !c.seed_rumor.toLowerCase().includes(query.toLowerCase()) &&
        !c.cycle_id.toLowerCase().includes(query.toLowerCase())
      )
        return false;
      return true;
    });
  }, [cycles, query, filter, todayIso]);

  const toggleSelect = (c) => {
    setSelected((prev) => {
      const next = new Map(prev);
      if (next.has(c.cycle_id)) next.delete(c.cycle_id);
      else if (next.size < 2) next.set(c.cycle_id, c);
      return next;
    });
  };

  const selectedArr = [...selected.values()];
  const compareA = selectedArr[0];
  const compareB = selectedArr[1];

  // KR-41.1-07: consensus/flips/duration/shocks are NOT on the list endpoint,
  // so only total count is derivable without extra requests.
  const stats = useMemo(
    () => ({ total: (cycles ?? []).length }),
    [cycles],
  );

  return (
    <div className="ch-takeover">
      <div className="ch-head">
        <div className="ch-head-left">
          <button className="btn ghost-btn" onClick={onClose} title="Back to dashboard">
            <Icon name="close" />
          </button>
          <span className="ch-title">Cycle History</span>
          <span className="label ch-count">
            {filtered.length} OF {(cycles ?? []).length}
          </span>
        </div>
        <div className="ch-head-right">
          <div className="ch-search">
            <Icon name="search" size={13} />
            <input
              placeholder="Filter by seed or cycle ID…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          <div className="seg ch-filter">
            <button data-active={filter === 'all'} onClick={() => setFilter('all')}>
              All
            </button>
            <button data-active={filter === 'today'} onClick={() => setFilter('today')}>
              Today
            </button>
            {/* KR-41.1-07: Starred filter removed — backend has no starred field. */}
          </div>
        </div>
      </div>

      {/* Summary strip. KR-41.1-07: only TOTAL CYCLES is backend-derivable
          from /api/replay/cycles. Consensus/flips/etc. tallies are omitted. */}
      <div className="ch-summary">
        <ChStat label="TOTAL CYCLES" value={stats.total} />
        <div className="ch-compare-cta">
          {loadError && (
            <span className="label" style={{ color: 'var(--sell)' }}>
              Failed to load cycles — see console.
            </span>
          )}
          {!loadError && selected.size === 0 && (
            <span className="label" style={{ color: 'var(--text-3)' }}>
              Select two cycles to compare
            </span>
          )}
          {selected.size === 1 && (
            <span className="label" style={{ color: 'var(--accent)' }}>
              1 selected · pick one more
            </span>
          )}
          {selected.size === 2 && (
            <button className="btn primary" onClick={() => setCompareOpen(true)}>
              <Icon name="graph" /> Compare {compareA.cycle_id} vs {compareB.cycle_id}
            </button>
          )}
          {selected.size > 0 && (
            <button
              className="btn ghost"
              onClick={() => setSelected(new Map())}
              title="Clear selection"
              style={{ marginLeft: 6 }}
            >
              Clear
            </button>
          )}
        </div>
      </div>

      <div className="ch-table-wrap">
        <div className="ch-row ch-row-head">
          <div></div>
          <div className="label">CYCLE ID</div>
          <div className="label">DATE</div>
          <div className="label">SEED</div>
          {/* KR-41.1-07: backend list omits consensus/flips/duration/shocks.
              Columns kept for parity with the design; values render '—'. */}
          <div className="label" style={{ textAlign: 'center' }}>
            CONSENSUS
          </div>
          <div className="label" style={{ textAlign: 'right' }}>
            FLIPS
          </div>
          <div className="label" style={{ textAlign: 'right' }}>
            DURATION
          </div>
          <div className="label" style={{ textAlign: 'center' }}>
            SHOCKS
          </div>
          <div></div>
        </div>
        {cycles === null && (
          <div className="ch-row" style={{ padding: '30px 20px' }}>
            <div className="label">Loading cycles…</div>
          </div>
        )}
        {cycles && cycles.length === 0 && (
          <div className="ch-row" style={{ padding: '30px 20px' }}>
            <div className="label">No completed cycles yet.</div>
          </div>
        )}
        {filtered.map((c) => {
          const isSel = selected.has(c.cycle_id);
          return (
            <div key={c.cycle_id} className="ch-row" data-selected={isSel}>
              <button
                className="ch-check"
                data-checked={isSel}
                onClick={() => toggleSelect(c)}
                title="Select for compare"
              >
                {isSel && (
                  <svg
                    width="10"
                    height="10"
                    viewBox="0 0 10 10"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.8"
                  >
                    <path d="M1 5 L4 8 L9 2" />
                  </svg>
                )}
              </button>
              <div className="ch-id mono" onClick={() => onOpenReport(c)}>
                {c.cycle_id}
              </div>
              <div className="ch-date mono">{c.created_at}</div>
              <div
                className="ch-seed"
                onClick={() => onOpenReport(c)}
                title={c.seed_rumor}
              >
                "{c.seed_rumor}"
              </div>
              {/* KR-41.1-07 em-dash placeholders: backend list endpoint does
                  not expose consensus / flips / duration / shocks. */}
              <div
                className="ch-consensus label"
                style={{ color: 'var(--text-3)', textAlign: 'center' }}
              >
                —
              </div>
              <div
                className="ch-flips mono label"
                style={{ color: 'var(--text-3)', textAlign: 'right' }}
              >
                —
              </div>
              <div
                className="ch-dur mono label"
                style={{ color: 'var(--text-3)', textAlign: 'right' }}
              >
                —
              </div>
              <div
                className="ch-shocks label"
                style={{ color: 'var(--text-3)', textAlign: 'center' }}
              >
                —
              </div>
              <button
                className="ch-open-btn"
                onClick={() => onOpenReport(c)}
                title="Open report"
              >
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

// Compare two cycles side-by-side.
// KR-41.1-07: round tallies are illustrative; backend does not expose
// per-round consensus for a given cycle via the list endpoint.
export function CompareModal({ a, b, onClose }) {
  if (!a || !b) return null;

  // KR-41.1-07: illustrative bar chart — round-level consensus is not on
  // /api/replay/cycles. Cycle-ID pairing UX still works.
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
      <div className="modal ch-compare" onClick={(e) => e.stopPropagation()}>
        <div className="rv2-head">
          <div className="rv2-head-left">
            <Icon name="graph" size={14} />
            <span className="label">CYCLE COMPARISON</span>
          </div>
          <div className="rv2-head-right">
            <button className="btn ghost" onClick={onClose}>
              <Icon name="close" />
            </button>
          </div>
        </div>
        <div className="ch-compare-body">
          <div className="ch-compare-col">
            <div className="label">CYCLE A</div>
            <div className="ch-compare-id mono">{a.cycle_id}</div>
            <div className="ch-compare-seed">"{a.seed_rumor}"</div>
            {/* KR-41.1-07: consensus pill hidden (not on list endpoint). */}
            <MiniFlow rounds={roundsA} />
            <div className="ch-compare-meta">
              <div>
                <span className="label">CREATED</span>{' '}
                <span className="mono">{a.created_at}</span>
              </div>
              <div>
                <span className="label">ROUNDS</span>{' '}
                <span className="mono">{a.round_count}</span>
              </div>
            </div>
          </div>

          <div className="ch-compare-divider">
            <span className="ch-compare-vs">vs</span>
          </div>

          <div className="ch-compare-col">
            <div className="label">CYCLE B</div>
            <div className="ch-compare-id mono">{b.cycle_id}</div>
            <div className="ch-compare-seed">"{b.seed_rumor}"</div>
            <MiniFlow rounds={roundsB} />
            <div className="ch-compare-meta">
              <div>
                <span className="label">CREATED</span>{' '}
                <span className="mono">{b.created_at}</span>
              </div>
              <div>
                <span className="label">ROUNDS</span>{' '}
                <span className="mono">{b.round_count}</span>
              </div>
            </div>
          </div>
        </div>

        <div className="ch-compare-notes">
          <div className="label" style={{ marginBottom: 8, color: 'var(--accent)' }}>
            DIVERGENCE
          </div>
          <p>
            {/* KR-41.1-07: narrative text is illustrative; per-cycle structured
                summary is not yet exposed by the backend. */}
            Cycle comparison details require per-round consensus data not yet
            available from <span className="mono">/api/replay/cycles</span>.
            Open individual reports for full narratives.
          </p>
        </div>
      </div>
    </div>
  );
}

function MiniFlow({ rounds }) {
  return (
    <div className="ch-miniflow">
      {rounds.map((r) => (
        <div key={r.r} className="ch-miniflow-col">
          <div className="ch-miniflow-bar">
            <div className="cv-seg buy" style={{ height: `${r.buy}%` }}>
              <span className="cv-n">{r.buy}</span>
            </div>
            <div className="cv-seg hold" style={{ height: `${r.hold}%` }}>
              <span className="cv-n">{r.hold}</span>
            </div>
            <div className="cv-seg sell" style={{ height: `${r.sell}%` }}>
              <span className="cv-n">{r.sell}</span>
            </div>
          </div>
          <div className="ch-miniflow-r label">{r.r}</div>
        </div>
      ))}
    </div>
  );
}
