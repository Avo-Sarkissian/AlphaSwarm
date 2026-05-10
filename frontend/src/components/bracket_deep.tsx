// Bracket Deep-Dive — full-screen takeover showing bracket internals.
// Real-wired per D-13 / KR-41.6-13.
//
// Source: AlphaSwarm-2/src/bracket_deep.jsx (159 LOC, CDN-globals format).
// Conversion notes:
//   - influences mock dict (line 38) REPLACED with /api/edges aggregation.
//     Direction semantics per codex MEDIUM-7: source_id = citing, target_id = cited.
//   - Live view (no edges yet) renders '—' for both out + in counts (KR-41.6-13).
//   - Source's CDN-globals export DELETED — module export only (no global pollution).
//   - agents prop is pre-filtered by caller (app_v2.tsx) per D-13:
//       useAgents().agents.filter(a => a.bracket === bracket.bracket)
//     So the inner `members` filter is now a no-op — kept defensive in case caller
//     forgets to filter.

import { useState, useEffect, useMemo } from 'react';
import { Icon } from './icons';
import { fetchEdges, type Edge } from '../api/edges';
import { useCurrentCycle } from '../hooks/useCurrentCycle';
import type { AgentView } from '../types';

const BRACKET_COLORS: Record<string, string> = {
  quants: '#6aa9ff',
  degens: '#ff5b6b',
  sovereigns: '#b080ff',
  macro: '#5be7b8',
  suits: '#ffb84d',
  insiders: '#ff9d5c',
  agents: '#8a93a0',
  doom_posters: '#ff4d7a',
  policy_wonks: '#42d690',
  whales: '#d4a843',
};

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
  // Defensive filter — caller is expected to have filtered already (D-13).
  const members = useMemo(
    () => agents.filter((a) => a.bracket.toLowerCase() === bracket.bracket.toLowerCase()),
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

  const buy = members.filter((a) => a.signal === 'buy').length;
  const sell = members.filter((a) => a.signal === 'sell').length;
  const hold = members.filter((a) => a.signal === 'hold').length;
  const total = members.length || 1;
  const flipped = members.filter((a) => a.flipped).length;
  const avgConf = members.reduce((s, a) => s + a.confidence, 0) / total;

  // Confidence histogram buckets: 0–25, 25–50, 50–75, 75–100.
  const buckets = [0, 25, 50, 75].map((lo) => ({
    lo,
    hi: lo + 25,
    count: members.filter((a) => a.confidence * 100 >= lo && a.confidence * 100 < lo + 25).length,
  }));
  const maxBucket = Math.max(...buckets.map((b) => b.count), 1);

  const color = BRACKET_COLORS[bracket.bracket] ?? 'var(--accent)';
  const sigColor = (s: string) =>
    s === 'buy' ? 'var(--buy)' : s === 'sell' ? 'var(--sell)' : 'var(--hold)';

  // Edges — aggregate per agent (codex MEDIUM-7 verified semantics):
  //   source_id = citing agent; target_id = cited agent.
  //   "out" (this agent cited N others)        → count edges where source_id === agent.id
  //   "in"  (this agent was cited by N others) → count edges where target_id === agent.id
  // Per KR-41.6-13 these counts are only meaningful post-cycle; live view shows '—'.
  const { cycleId } = useCurrentCycle();
  const [edges, setEdges] = useState<Edge[]>([]);
  useEffect(() => {
    if (!cycleId) return;
    let cancelled = false;
    fetchEdges(cycleId, 3)
      .then((e) => {
        if (!cancelled) setEdges(e);
      })
      .catch(() => {
        if (!cancelled) setEdges([]);
      });
    return () => {
      cancelled = true;
    };
  }, [cycleId]);

  const influences = useMemo(() => {
    const m: Record<string, { out: number; in: number }> = {};
    members.forEach((a) => {
      m[a.id] = { out: 0, in: 0 };
    });
    edges.forEach((e) => {
      if (m[e.source_id]) m[e.source_id].out += 1; // this agent cited someone
      if (m[e.target_id]) m[e.target_id].in += 1; // this agent was cited
    });
    return m;
  }, [edges, members]);

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
          <span className="label" style={{ color: 'var(--buy)' }}>{buy} BUY</span>
          <span className="label" style={{ color: 'var(--sell)' }}>{sell} SELL</span>
          <span className="label" style={{ color: 'var(--hold)' }}>{hold} HOLD</span>
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
              {[
                { sig: 'buy', n: buy },
                { sig: 'sell', n: sell },
                { sig: 'hold', n: hold },
              ].map(({ sig, n }) => (
                <div key={sig} className="bd-sig-row">
                  <span className={`rationale-signal sig-${sig}`}>{sig.toUpperCase()}</span>
                  <div className="bd-sig-bar">
                    <div
                      className="bd-sig-fill"
                      style={{ width: `${(n / total) * 100}%`, background: sigColor(sig) }}
                    />
                  </div>
                  <span className="mono" style={{ fontSize: 13, color: sigColor(sig) }}>{n}</span>
                  <span className="label">{((n / total) * 100).toFixed(0)}%</span>
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
                value={buy >= sell && buy >= hold ? 'BUY' : sell >= hold ? 'SELL' : 'HOLD'}
                tone={buy >= sell && buy >= hold ? 'buy' : sell >= hold ? 'sell' : 'hold'}
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
              const inf = influences[a.id];
              return (
                <div
                  key={a.id}
                  className="bd-agent-row"
                  onClick={() => onAgentInterview?.(a)}
                >
                  <div className="bd-agent-id mono" style={{ color }}>{a.id}</div>
                  <div className={`bd-agent-sig rationale-signal sig-${a.signal}`}>
                    {(a.signal ?? 'hold').toUpperCase()}
                  </div>
                  <div className="bd-agent-conf">
                    <div className="bd-conf-bar">
                      <div
                        className="bd-conf-fill"
                        style={{ width: `${a.confidence * 100}%`, background: sigColor(a.signal) }}
                      />
                    </div>
                    <span className="mono" style={{ fontSize: 10 }}>
                      {(a.confidence * 100).toFixed(0)}%
                    </span>
                  </div>
                  <div className="bd-agent-inf label">
                    {/* KR-41.6-13: influences only meaningful post-cycle; live = '—' */}
                    <span style={{ color: 'var(--accent)' }}>
                      ↗{hasEdges ? inf?.out ?? 0 : '—'}
                    </span>
                    <span style={{ color: 'var(--text-3)' }}>
                      ↙{hasEdges ? inf?.in ?? 0 : '—'}
                    </span>
                  </div>
                  {a.flipped ? <div className="bd-flip-tag label">FLIP</div> : null}
                  <div className="bd-agent-chat-icon">
                    <Icon name="chat" size={12} />
                  </div>
                </div>
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
