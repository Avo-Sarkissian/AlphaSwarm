// Bracket Deep-Dive — full-screen takeover showing bracket internals.
// Real-wired per docs/DECISIONS.md#p41-6-d-13 and docs/DECISIONS.md#kr-41-6-13.
//
// Notes:
//   - Citation counts come from the shared EdgesContext (round on screen).
//     Direction semantics: source_id = citing, target_id = cited.
//   - Before round 2's edges exist (R1, seeding, idle) both counts render '—'.
//   - agents prop is pre-filtered by the caller (ModalHost)
//     (docs/DECISIONS.md#p41-6-d-13):
//       useAgents().agents.filter(a => a.bracket === bracket.bracket)
//     So the inner `members` filter is now a no-op — kept defensive in case caller
//     forgets to filter.

import { useState, useMemo } from 'react';
import { Icon } from '../../components/Icon';
import { useEdgesCtx } from '../../context/EdgesContext';
import { bracketSpec } from '../../data';
import { signalClass, signalColor, signalLabel } from '../../lib/signals';
import { consensusLeader, tallySignals } from '../../lib/tally';
import type { AgentView } from '../../types';

interface BracketDescriptor {
  bracket: string;
  display_name: string;
  total?: number;
  buy_count?: number;
  sell_count?: number;
  hold_count?: number;
}

interface BracketDeepDiveProps {
  bracket: BracketDescriptor;
  agents: AgentView[];
  onClose: () => void;
  onAgentInterview?: (agent: AgentView) => void;
}

type SortKey = 'confidence' | 'signal' | 'id';

export function BracketDeepDive({
  bracket,
  agents,
  onClose,
  onAgentInterview,
}: BracketDeepDiveProps) {
  // Defensive filter — caller is expected to have filtered already
  // (docs/DECISIONS.md#p41-6-d-13);
  // agents arrive pre-filtered by wire key.
  const members = useMemo(
    () => agents.filter((a) => a.bracket === bracket.bracket),
    [agents, bracket.bracket],
  );
  const [sortBy, setSortBy] = useState<SortKey>('confidence');

  const sorted = useMemo(
    () =>
      [...members].sort((a, b) => {
        if (sortBy === 'confidence') return b.confidence - a.confidence;
        if (sortBy === 'signal') return (a.signal ?? '').localeCompare(b.signal ?? '');
        return a.id.localeCompare(b.id);
      }),
    [members, sortBy],
  );

  // Pending (null) and failed members are not HOLD; shares, the average and
  // the histogram are over decided members only (docs/DECISIONS.md#adr-streaming-state).
  const tally = tallySignals(members);
  const lead = consensusLeader(tally);
  const decided = members.filter(
    (a) => a.signal === 'buy' || a.signal === 'sell' || a.signal === 'hold',
  );
  const pctOfDecided = (n: number) => (tally.decided > 0 ? (n / tally.decided) * 100 : 0);
  const flipped = members.filter((a) => a.flipped).length;
  const avgConf =
    decided.length > 0 ? decided.reduce((s, a) => s + a.confidence, 0) / decided.length : 0;

  // Confidence histogram buckets: 0–25, 25–50, 50–75, 75–100.
  const buckets = [0, 25, 50, 75].map((lo) => ({
    lo,
    hi: lo + 25,
    count: decided.filter((a) => a.confidence * 100 >= lo && a.confidence * 100 < lo + 25).length,
  }));
  const maxBucket = Math.max(...buckets.map((b) => b.count), 1);

  const color = bracketSpec(bracket.bracket)?.color ?? 'var(--accent)';

  // Edges of the round on screen (EdgesContext): source_id cites target_id, so
  // outDegree = citations this agent made, inDegree = times it was cited
  // (docs/DECISIONS.md#adr-neo4j-schema). Before round 2's edges exist: '—'.
  const { edges, inDegree, outDegree } = useEdgesCtx();
  const hasEdges = edges.length > 0;

  return (
    <div className="bd-takeover">
      <div className="bd-head">
        <button className="btn ghost-btn" onClick={onClose}>
          <Icon name="close" />
        </button>
        <div className="bd-bracket-pill" style={{ background: color, color: '#000' }}>
          {bracket.display_name}
        </div>
        <div className="bd-head-meta">
          <span className="label">{members.length} AGENTS</span>
          <span className="label">·</span>
          <span className="label" style={{ color: 'var(--buy)' }}>{tally.buy} BUY</span>
          <span className="label" style={{ color: 'var(--sell)' }}>{tally.sell} SELL</span>
          <span className="label" style={{ color: 'var(--hold)' }}>{tally.hold} HOLD</span>
          {tally.thinking > 0 && <span className="label">{tally.thinking} PENDING</span>}
          {tally.parseError > 0 && <span className="label">{tally.parseError} FAILED</span>}
          <span className="label">·</span>
          <span className="label">{flipped} FLIPPED</span>
        </div>
      </div>

      <div className="bd-body">
        {/* Left: stats */}
        <div className="bd-left">
          {/* Signal distribution */}
          <div className="bd-stat-section">
            <div className="label" style={{ marginBottom: 10 }}>SIGNAL DISTRIBUTION</div>
            <div className="bd-signal-bars">
              {([
                { sig: 'buy', n: tally.buy },
                { sig: 'sell', n: tally.sell },
                { sig: 'hold', n: tally.hold },
              ] as const).map(({ sig, n }) => (
                <div key={sig} className="bd-sig-row">
                  <span className={`rationale-signal sig-${sig}`}>{sig.toUpperCase()}</span>
                  <div className="bd-sig-bar">
                    <div
                      className="bd-sig-fill"
                      style={{ width: `${pctOfDecided(n)}%`, background: signalColor(sig) }}
                    />
                  </div>
                  <span className="mono" style={{ fontSize: 13, color: signalColor(sig) }}>{n}</span>
                  <span className="label">{pctOfDecided(n).toFixed(0)}%</span>
                </div>
              ))}
            </div>
          </div>

          {/* Confidence histogram */}
          <div className="bd-stat-section">
            <div className="label" style={{ marginBottom: 10 }}>CONFIDENCE HISTOGRAM</div>
            <div className="bd-histogram">
              {buckets.map((b) => (
                <div key={b.lo} className="bd-hist-col">
                  <div className="bd-hist-bar-wrap">
                    <div
                      className="bd-hist-bar"
                      style={{
                        height: `${(b.count / maxBucket) * 100}%`,
                        background: color,
                      }}
                    />
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
              <BdStat label="AVG CONF" value={`${(avgConf * 100).toFixed(0)}%`} />
              <BdStat label="FLIPPED" value={`${flipped}/${members.length}`} />
              <BdStat
                label="CONSENSUS"
                value={lead.signal ? lead.signal.toUpperCase() : '—'}
                tone={lead.signal ?? undefined}
              />
            </div>
          </div>
        </div>

        {/* Right: agent roster */}
        <div className="bd-right">
          <div className="bd-roster-head">
            <span className="label">ROSTER · {members.length} AGENTS</span>
            <div className="bd-sort">
              <span className="label">SORT</span>
              {(['confidence', 'signal', 'id'] as const).map((s) => (
                <button
                  key={s}
                  className="bd-sort-btn"
                  data-active={sortBy === s}
                  onClick={() => setSortBy(s)}
                >
                  {s.toUpperCase()}
                </button>
              ))}
            </div>
          </div>
          <div className="bd-roster">
            {sorted.map((a) => {
              return (
                <button
                  type="button"
                  key={a.id}
                  className="bd-agent-row as-text as-row"
                  onClick={() => onAgentInterview?.(a)}
                >
                  <div className="bd-agent-id mono" style={{ color }}>{a.id}</div>
                  <div className={`bd-agent-sig rationale-signal ${signalClass(a.signal)}`}>
                    {signalLabel(a.signal)}
                  </div>
                  <div className="bd-agent-conf">
                    <div className="bd-conf-bar">
                      <div
                        className="bd-conf-fill"
                        style={{ width: `${a.confidence * 100}%`, background: signalColor(a.signal) }}
                      />
                    </div>
                    <span className="mono" style={{ fontSize: 10 }}>
                      {(a.confidence * 100).toFixed(0)}%
                    </span>
                  </div>
                  <div className="bd-agent-inf label">
                    {/* Citations of the round on screen; '—' until round 2's edges exist. */}
                    <span style={{ color: 'var(--accent)' }}>
                      ↗{hasEdges ? outDegree.get(a.id) ?? 0 : '—'}
                    </span>
                    <span style={{ color: 'var(--text-3)' }}>
                      ↙{hasEdges ? inDegree.get(a.id) ?? 0 : '—'}
                    </span>
                  </div>
                  {a.flipped ? <div className="bd-flip-tag label">FLIP</div> : null}
                  <div className="bd-agent-chat-icon">
                    <Icon name="chat" size={12} />
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

interface BdStatProps {
  label: string;
  value: string;
  tone?: string;
}

function BdStat({ label, value, tone }: BdStatProps) {
  return (
    <div className="bd-mini-stat" data-tone={tone}>
      <div className="label">{label}</div>
      <div className="bd-mini-val">{value}</div>
    </div>
  );
}
