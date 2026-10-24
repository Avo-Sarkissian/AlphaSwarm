// Cycle History — every complete cycle with the run metrics stored on its
// Cycle node (docs/DECISIONS.md#adr-cycle-metrics). Pages through
// GET /api/replay/cycles; cycles recorded before metrics existed show "—"
// and are left out of the averages.
import { useMemo, useState } from 'react';
import { Icon } from '../../components/Icon';
import { InlineError } from '../../components/InlineError';
import { replayStart, type CycleItem } from '../../api/replay';
import { useCyclePages } from '../../hooks/useCyclePages';
import { consensusOf, isSameLocalDay, parseIsoInstant, summarizeCycles } from '../../lib/cycles';
import { formatApiError } from '../../lib/apiError';
import { formatDuration } from '../../lib/format';

function formatCycleDate(iso: string): string {
  const d = parseIsoInstant(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { year: 'numeric', month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

export function CycleBrowser({
  onClose,
  onOpenReport,
}: {
  onClose: () => void;
  onOpenReport: (c: CycleItem) => void;
}) {
  const { cycles, error, hasMore, loadingMore, loadMore } = useCyclePages();
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState<'all' | 'today'>('all');
  // "Today" is anchored when the filter is chosen (an event, not render), so the
  // render stays pure (react-hooks/purity) and the list does not shift at midnight.
  const [todayAnchor, setTodayAnchor] = useState<Date | null>(null);
  const [replaying, setReplaying] = useState<string | null>(null);
  const [replayError, setReplayError] = useState<string | null>(null);

  async function onReplay(cycleId: string): Promise<void> {
    setReplaying(cycleId);
    setReplayError(null);
    try {
      await replayStart(cycleId);
      onClose();
    } catch (err) {
      setReplayError(formatApiError(err));
    } finally {
      setReplaying(null);
    }
  }

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (cycles ?? []).filter((c) => {
      if (filter === 'today' && todayAnchor !== null && !isSameLocalDay(c.created_at, todayAnchor)) return false;
      if (q && !c.seed_rumor.toLowerCase().includes(q) && !c.cycle_id.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [cycles, query, filter, todayAnchor]);
  const summary = useMemo(() => summarizeCycles(filtered), [filtered]);

  return (
    <div className="ch-takeover">
      <div className="ch-head">
        <div className="ch-head-left">
          <button className="btn ghost-btn" onClick={onClose} title="Back to dashboard" aria-label="Close history">
            <Icon name="close" />
          </button>
          <span className="ch-title">Cycle History</span>
          <span className="label ch-count">
            {filtered.length} OF {cycles?.length ?? 0} LOADED
          </span>
        </div>
        <div className="ch-head-right">
          <div className="ch-search">
            <Icon name="search" size={13} />
            <input placeholder="Filter by seed or cycle ID…" value={query} onChange={(e) => setQuery(e.target.value)} />
          </div>
          <div className="seg ch-filter">
            <button data-active={filter === 'all'} onClick={() => setFilter('all')}>
              All
            </button>
            <button
              data-active={filter === 'today'}
              onClick={() => {
                setTodayAnchor(new Date());
                setFilter('today');
              }}
            >
              Today
            </button>
          </div>
        </div>
      </div>

      <div className="ch-summary">
        <ChStat label="CYCLES SHOWN" value={String(summary.loaded)} />
        <ChStat label="BUY CONSENSUS" value={String(summary.buy)} />
        <ChStat label="SELL CONSENSUS" value={String(summary.sell)} />
        <ChStat label="HOLD CONSENSUS" value={String(summary.hold)} />
        <ChStat label="AVG FLIPS" value={summary.avgFlips === null ? '—' : summary.avgFlips.toFixed(1)} />
        <ChStat label="AVG DURATION" value={formatDuration(summary.avgSeconds)} />
      </div>

      <InlineError error={replayError} onDismiss={() => setReplayError(null)} />
      <div className="ch-table-wrap">
        <div className="ch-row ch-row-head">
          <div className="label">CYCLE ID</div>
          <div className="label">DATE</div>
          <div className="label">SEED</div>
          <div className="label" style={{ textAlign: 'center' }}>CONSENSUS</div>
          <div className="label" style={{ textAlign: 'right' }}>FLIPS</div>
          <div className="label" style={{ textAlign: 'right' }}>DURATION</div>
          <div />
        </div>
        {cycles === null && !error && (
          <div className="ch-row ch-row-wide">
            <div className="label">Loading cycles…</div>
          </div>
        )}
        {error && (
          <div className="ch-row ch-row-wide">
            <InlineError error={`Failed to load cycles: ${error}`} />
          </div>
        )}
        {cycles !== null && cycles.length === 0 && !error && (
          <div className="ch-row ch-row-wide">
            <div className="label">No completed cycles yet.</div>
          </div>
        )}
        {filtered.map((c) => (
          <CycleRow
            key={c.cycle_id}
            cycle={c}
            onOpenReport={onOpenReport}
            onReplay={() => void onReplay(c.cycle_id)}
            replayDisabled={replaying !== null}
          />
        ))}
        {hasMore && (
          <div className="ch-row ch-row-wide">
            <button className="btn ghost" onClick={loadMore} disabled={loadingMore}>
              {loadingMore ? 'Loading…' : 'Load older cycles'}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

function CycleRow({
  cycle: c,
  onOpenReport,
  onReplay,
  replayDisabled,
}: {
  cycle: CycleItem;
  onOpenReport: (c: CycleItem) => void;
  onReplay: () => void;
  replayDisabled: boolean;
}) {
  const consensus = consensusOf(c);
  return (
    <div className="ch-row">
      <button type="button" className="ch-id mono as-text" onClick={() => onOpenReport(c)}>
        {c.cycle_id}
      </button>
      <div className="ch-date mono" title={c.created_at}>
        {formatCycleDate(c.created_at)}
      </div>
      <button type="button" className="ch-seed as-text" onClick={() => onOpenReport(c)} title={c.seed_rumor}>
        "{c.seed_rumor}"
      </button>
      <div className="ch-consensus" data-signal={consensus?.signal ?? 'none'}>
        {consensus === null ? (
          <span className="ch-dash" title="Not recorded for this cycle">
            —
          </span>
        ) : (
          `${consensus.signal.toUpperCase()} ${consensus.pct}%`
        )}
      </div>
      <div className="ch-flips mono" title={c.total_flips === null ? 'Not recorded for this cycle' : undefined}>
        {c.total_flips ?? '—'}
      </div>
      <div className="ch-dur mono" title={c.total_seconds === null ? 'Not recorded for this cycle' : undefined}>
        {formatDuration(c.total_seconds)}
      </div>
      <div className="ch-actions">
        <button
          className="ch-open-btn"
          onClick={onReplay}
          disabled={replayDisabled}
          title="Replay this cycle"
          aria-label={`Replay ${c.cycle_id}`}
        >
          <Icon name="replay" />
        </button>
        <button className="ch-open-btn" onClick={() => onOpenReport(c)} title="Open report" aria-label={`Open report for ${c.cycle_id}`}>
          <Icon name="doc" />
        </button>
      </div>
    </div>
  );
}

function ChStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="ch-stat">
      <div className="label">{label}</div>
      <div className="ch-stat-v">{value}</div>
    </div>
  );
}
