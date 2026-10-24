// Data Sources takeover: the live provider-call audit per source, with recent calls.
import { useState, useMemo } from 'react';
import { Icon } from '../../components/Icon';
import { useDataSourceAudit } from '../../hooks/useDataSourceAudit';
import { usePrivacyFacts } from '../../hooks/usePrivacyFacts';
import { dataSourcesNote } from '../../lib/privacyCopy';
import { recentFor, summarizeAudit } from '../../lib/dataSources';
import { SOURCE_COLOR, SOURCE_LABEL } from './wireFormat';

// No mock fallback (docs/DECISIONS.md#kr-41-1-02).
export function DataSourcesTakeover({ onClose }: { onClose: () => void }) {
  const audit = useDataSourceAudit();
  const summaries = useMemo(() => summarizeAudit(audit), [audit]);
  const [selected, setSelected] = useState<string | null>(null);
  const active = selected ?? summaries[0]?.source ?? null;
  const recent = useMemo(() => (active ? recentFor(audit, active) : []), [audit, active]);
  const totals = useMemo(
    () =>
      summaries.reduce(
        (t, s) => ({ calls: t.calls + s.calls, errors: t.errors + s.errors, cached: t.cached + s.cached, cited: t.cited + s.cited }),
        { calls: 0, errors: 0, cached: 0, cited: 0 },
      ),
    [summaries],
  );

  return (
    <div className="ds-takeover">
      <div className="ds-head">
        <div className="ds-head-left">
          <button className="btn ghost-btn" onClick={onClose} aria-label="Close data sources">
            <Icon name="close" />
          </button>
          <div className="ds-head-title">Data Sources</div>
          <div className="label u-muted">
            LAST {audit.length} PROVIDER CALLS
          </div>
        </div>
        <div className="ds-head-stats">
          <DsStat label="CALLS" value={String(totals.calls)} />
          <DsStat label="ERRORS" value={String(totals.errors)} tone={totals.errors > 0 ? 'sell' : 'ok'} />
          <DsStat label="CACHED" value={String(totals.cached)} />
          <DsStat label="FED TO AGENTS" value={String(totals.cited)} />
        </div>
      </div>

      <div className="ds-body">
        {summaries.length === 0 ? (
          <div className="ds-empty">
            No provider calls yet. Market prices and headlines are fetched while the swarm is seeding.
          </div>
        ) : (
          <>
            <div className="ds-left">
              <div className="ds-source-list">
                {summaries.map((s) => (
                  <button
                    key={s.source}
                    className="ds-source-row"
                    data-active={active === s.source}
                    onClick={() => setSelected(s.source)}
                  >
                    <div className="ds-src-top">
                      <div className="ds-src-name">
                        <span className="ds-src-dot" style={{ background: SOURCE_COLOR[s.source] ?? 'var(--accent)' }} />
                        <span>{SOURCE_LABEL[s.source] ?? s.source}</span>
                      </div>
                      <span className={`ds-src-calls mono ${s.errors > 0 ? 'err' : ''}`}>{s.calls}</span>
                    </div>
                    <div className="ds-src-meta">
                      <span>{s.cached} cached</span>
                      {s.errors > 0 && <span className="ds-err-badge">{s.errors} err</span>}
                      <span>{s.cited} fed to agents</span>
                    </div>
                  </button>
                ))}
              </div>
            </div>

            <div className="ds-detail-pane">
              <div className="label u-mb-10">
                RECENT CALLS · {active ? (SOURCE_LABEL[active] ?? active) : ''}
              </div>
              <div className="ds-recent-table">
                <div className="ds-recent-head">
                  <span className="label">TIME</span>
                  <span className="label">QUERY</span>
                  <span className="label">RESULT</span>
                  <span className="label">FED TO AGENTS</span>
                </div>
                {recent.map((r, i) => (
                  <div key={`${r.ts}-${i}`} className="ds-recent-row-item">
                    <span className="mono">{new Date(r.ts * 1000).toLocaleTimeString()}</span>
                    <span className="mono ds-q-text">{r.query}</span>
                    <span className="mono ds-r-text">{r.result}</span>
                    <span className={`ds-cited-badge ${r.used ? 'yes' : 'no'}`}>{r.used ? 'YES' : 'NO'}</span>
                  </div>
                ))}
              </div>
            </div>
          </>
        )}
      </div>
      <DataSourcesPrivacyNote />
    </div>
  );
}

function DataSourcesPrivacyNote() {
  const [privacy] = usePrivacyFacts();
  return (
    <div className="ds-privacy-note">
      <Icon name="lock" size={12} />
      <span>{dataSourcesNote(privacy)}</span>
    </div>
  );
}

function DsStat({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: string;
}) {
  return (
    <div className="ds-head-stat" data-tone={tone}>
      <div className="label">{label}</div>
      <div className="ds-head-stat-v mono">{value}</div>
    </div>
  );
}
