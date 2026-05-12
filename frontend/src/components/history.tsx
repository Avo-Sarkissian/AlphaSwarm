// Cycle History — list of past cycles, compare mode (D-21).
// Full-screen takeover triggered from topbar.
//
// Ported from AlphaSwarm-2/src/history.jsx (262 LOC) per D-03 and renamed
// .jsx → .tsx per codex HIGH-1 (uses CycleItem[] typing + selected: Set<string>).
//
// Wiring:
//   • Local cycle-archive mock removed — wired to listCycles() from api/replay.
//   • Em-dash placeholders for consensus/flips/duration/shocks per KR-41.1-07
//     (backend /api/replay/cycles payload has only cycle_id, created_at,
//     seed_rumor, round_count).
//   • Compare button conditional render per D-21 — only shown when
//     comparableCycles.length >= 2. Currently always 0 (no backend
//     cycle-comparison endpoint), so the button is always hidden (KR-41.6-07).
import { useEffect, useMemo, useState } from 'react';
import { Icon } from './icons';
import { listCycles, type CycleItem } from '../api/replay';

// Render the backend's ISO `created_at` as a short local-time stamp so the
// table is scannable. Falls back to the raw value on parse failure.
function formatCycleDate(iso: string): string {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString(undefined, {
      year: 'numeric', month: 'short', day: '2-digit',
      hour: '2-digit', minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

export function CycleHistory({
  onClose,
  onOpenReport,
}: {
  onClose: () => void;
  onOpenReport: (c: CycleItem) => void;
}) {
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState<'all' | 'starred' | 'today'>('all');
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [compareOpen, setCompareOpen] = useState(false);
  const [cycles, setCycles] = useState<CycleItem[] | null>(null); // null = loading
  const [err, setErr] = useState<Error | null>(null);

  useEffect(() => {
    let cancelled = false;
    listCycles()
      .then((cs) => {
        if (!cancelled) setCycles(cs);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        // KR-41.1-08
        // eslint-disable-next-line no-console
        console.error('listCycles failed', e);
        setErr(e instanceof Error ? e : new Error(String(e)));
        setCycles([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const todayPrefix = useMemo(() => {
    const d = new Date();
    const yyyy = d.getUTCFullYear();
    const mm = String(d.getUTCMonth() + 1).padStart(2, '0');
    const dd = String(d.getUTCDate()).padStart(2, '0');
    return `${yyyy}-${mm}-${dd}`;
  }, []);

  const filtered = useMemo(() => {
    if (!cycles) return [];
    return cycles.filter((c) => {
      if (filter === 'today' && !c.created_at.startsWith(todayPrefix)) return false;
      // 'starred' is design-only — backend has no concept; skip when filter active
      if (filter === 'starred') return false;
      if (
        query &&
        !c.seed_rumor.toLowerCase().includes(query.toLowerCase()) &&
        !c.cycle_id.toLowerCase().includes(query.toLowerCase())
      )
        return false;
      return true;
    });
  }, [cycles, query, filter, todayPrefix]);

  const toggleSelect = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else if (next.size < 2) next.add(id);
      return next;
    });
  };

  const compareA = [...selected][0];
  const compareB = [...selected][1];

  // D-21: derive comparableCycles. No backend cycle-comparison endpoint →
  // always empty → Compare button never renders. KR-41.6-07.
  const comparableCycles: CycleItem[] = [];

  // stats — computed from live list (em-dash where the backend doesn't carry data)
  const total = cycles?.length ?? 0;

  return (
    <div className="ch-takeover">
      <div className="ch-head">
        <div className="ch-head-left">
          <button
            className="btn ghost-btn"
            onClick={onClose}
            title="Back to dashboard"
          >
            <Icon name="close" />
          </button>
          <span className="ch-title">Cycle History</span>
          <span className="label ch-count">
            {filtered.length} OF {total}
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
            <button
              data-active={filter === 'all'}
              onClick={() => setFilter('all')}
            >
              All
            </button>
            <button
              data-active={filter === 'today'}
              onClick={() => setFilter('today')}
            >
              Today
            </button>
            <button
              data-active={filter === 'starred'}
              onClick={() => setFilter('starred')}
            >
              Starred
            </button>
          </div>
        </div>
      </div>

      {/* summary strip — em-dashes for fields the backend doesn't carry (KR-41.1-07) */}
      <div className="ch-summary">
        <ChStat label="TOTAL CYCLES" value={String(total)} />
        <ChStat label="SELL CONSENSUS" value="—" />
        <ChStat label="BUY CONSENSUS" value="—" />
        <ChStat label="HOLD" value="—" />
        <ChStat label="AVG FLIPS" value="—" />
        <div className="ch-compare-cta">
          {selected.size === 0 && (
            <span className="label" style={{ color: 'var(--text-3)' }}>
              {/* D-21: comparison disabled (no backend endpoint) — KR-41.6-07 */}
              Cycle comparison ships in a future phase
            </span>
          )}
          {selected.size === 1 && (
            <span className="label" style={{ color: 'var(--accent)' }}>
              1 selected · pick one more
            </span>
          )}
          {/* D-21: only render Compare when comparable data exists. Always false in W3. */}
          {selected.size === 2 && comparableCycles.length >= 2 && (
            <button className="btn primary" onClick={() => setCompareOpen(true)}>
              <Icon name="graph" /> Compare {compareA} vs {compareB}
            </button>
          )}
          {selected.size > 0 && (
            <button
              className="btn ghost"
              onClick={() => setSelected(new Set())}
              title="Clear selection"
              style={{ marginLeft: 6 }}
            >
              Clear
            </button>
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
          <div className="ch-row" style={{ padding: '24px 16px' }}>
            <div className="label">Loading cycles…</div>
          </div>
        )}
        {err && (
          <div
            className="ch-row"
            style={{ padding: '24px 16px', color: 'var(--sell)' }}
          >
            <div className="label">Failed to load cycles: {err.message}</div>
          </div>
        )}
        {cycles && cycles.length === 0 && !err && (
          <div className="ch-row" style={{ padding: '24px 16px' }}>
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
                onClick={() => toggleSelect(c.cycle_id)}
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
              <div className="ch-date mono" title={c.created_at}>{formatCycleDate(c.created_at)}</div>
              <div
                className="ch-seed"
                onClick={() => onOpenReport(c)}
                title={c.seed_rumor}
              >
                "{c.seed_rumor}"
              </div>
              {/* KR-41.1-07: consensus/flips/duration/shocks not on the list endpoint */}
              <div className="ch-consensus">
                <span className="ch-dash">—</span>
              </div>
              <div className="ch-flips mono">—</div>
              <div className="ch-dur mono">—</div>
              <div className="ch-shocks">
                <span className="ch-dash">—</span>
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

      {/* CompareModal kept exported below; in W3 it never mounts (D-21 → button hidden) */}
      {compareOpen && compareA && compareB && (
        <CompareModal a={compareA} b={compareB} onClose={() => setCompareOpen(false)} />
      )}
    </div>
  );
}

function ChStat({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: string;
}) {
  return (
    <div className="ch-stat" data-tone={tone || 'default'}>
      <div className="label">{label}</div>
      <div className="ch-stat-v">{value}</div>
      {sub && <div className="ch-stat-sub mono">{sub}</div>}
    </div>
  );
}

// Compare two cycles side-by-side. D-21: never mounts in W3 (button hidden);
// kept exported so a future backend cycle-comparison endpoint can re-enable it.
export function CompareModal({
  a,
  b,
  onClose,
}: {
  a: string;
  b: string;
  onClose: () => void;
}) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal ch-compare" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head rv2-head">
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
        <div className="ch-compare-body" style={{ padding: 24 }}>
          <div className="label" style={{ color: 'var(--text-3)' }}>
            Cycle comparison ships in a future phase. Selected cycles: {a} vs {b}.
          </div>
        </div>
      </div>
    </div>
  );
}
