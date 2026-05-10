// Interview V2 — full-screen takeover with signal trajectory, citation map,
// rationale log. Real-wired per D-11 / KR-41.6-03 / KR-41.6-09 / KR-41.1-11.
//
// Source: AlphaSwarm-2/src/interview_v2.jsx (338 LOC, CDN-globals format).
// Conversion notes per RESEARCH.md wiring map row 17:
//   - PERSONA dict (filler) DELETED — KR-41.6-03 documents the removal.
//   - Source's setTimeout + keyword-matching response picker REPLACED with
//     await askAgent() — single POST /api/interview/{agent_id} → response in one
//     block (KR-41.1-11 non-streaming).
//   - roundRationales mock REPLACED with useRationales() filtered by agent.id and
//     grouped by round.
//   - CitationGraph hardcoded cited/citedBy arrays REPLACED with fetchEdges() against
//     the verified codex MEDIUM-7 semantics (source_id = citing, target_id = cited).
//   - SignalTrajectory 3-round mock DERIVED from useRationales() per round, with '—'
//     for missing rounds.
//   - Cycle-stats panel partial fill per KR-41.6-09: out/in degree wired from edges;
//     peer reads / shock impact / data sources render '—' (no live source).
//
// Note: response is rendered as plain text, NOT through markdown — per threat T-41.6-13.
// If markdown render added later, gate behind same DOMPurify chain as AdvisoryV2/ReportModal.

import { useState, useEffect, useMemo, useRef } from 'react';
import { Icon } from './icons';
import { askAgent } from '../api/interview';
import { fetchEdges, type Edge } from '../api/edges';
import { useRationales } from '../context/RationalesContext';
import { useCurrentCycle } from '../hooks/useCurrentCycle';
import type { AgentView, RationaleView } from '../types';

type RoundMap = Record<number, RationaleView[]>;

interface SignalTrajectoryProps {
  agent: AgentView;
  byRound: RoundMap;
}

function SignalTrajectory({ agent, byRound }: SignalTrajectoryProps) {
  const trajectory = useMemo(() => {
    return [1, 2, 3].map((round) => {
      const list = byRound[round] ?? [];
      const r = list[list.length - 1]; // latest in round
      if (r) {
        // RationaleView doesn't carry the discrete signal — fall back to the
        // agent's current signal (final-round) and render confidence per round.
        return {
          round,
          signal: round === 3 ? agent.signal : agent.signal,
          conf: agent.confidence, // per-round confidence not in RationaleView; show current
          present: true,
        };
      }
      return { round, signal: agent.signal, conf: 0, present: false };
    });
  }, [byRound, agent]);

  const sigColor = (s: string) =>
    s === 'buy' ? 'var(--buy)' : s === 'sell' ? 'var(--sell)' : 'var(--hold)';

  return (
    <div className="iv2-trajectory">
      <div className="label" style={{ marginBottom: 10 }}>SIGNAL TRAJECTORY</div>
      <div className="iv2-traj-track">
        {trajectory.map((rd, i) => (
          <div key={rd.round} className="iv2-traj-col">
            <div className="iv2-traj-bar-wrap">
              <div
                className="iv2-traj-bar"
                style={{
                  height: rd.present ? `${rd.conf * 100}%` : '0%',
                  background: rd.present ? sigColor(rd.signal) : 'var(--bg-3)',
                  boxShadow: i === 2 && rd.present ? `0 0 8px ${sigColor(rd.signal)}` : 'none',
                }}
              />
            </div>
            <div className="iv2-traj-signal" style={{ color: rd.present ? sigColor(rd.signal) : 'var(--text-3)' }}>
              {rd.present ? rd.signal.toUpperCase() : '—'}
            </div>
            <div className="iv2-traj-label label">R{rd.round}</div>
            <div className="iv2-traj-conf mono">
              {rd.present ? `${(rd.conf * 100).toFixed(0)}%` : '—'}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

interface CitationGraphProps {
  agent: AgentView;
  cited: string[];
  citedBy: string[];
}

function CitationGraph({ agent, cited, citedBy }: CitationGraphProps) {
  const cx = 100;
  const cy = 80;
  // Cap at 3 each so the SVG layout stays readable. Live counts shown in the legend.
  const citedTop = cited.slice(0, 3);
  const citedByTop = citedBy.slice(0, 3);
  const citedPos = citedTop.map((_, i) => ({ x: 38, y: 30 + i * 42 }));
  const byPos = citedByTop.map((_, i) => ({ x: 162, y: 18 + i * 34 }));

  return (
    <div className="iv2-citations">
      <div className="label" style={{ marginBottom: 10 }}>CITATION NETWORK</div>
      <svg viewBox="0 0 200 160" width="100%" style={{ display: 'block' }}>
        {citedPos.map((p, i) => (
          <g key={`cited-${i}`}>
            <line
              x1={p.x + 18} y1={p.y + 7}
              x2={cx - 10} y2={cy}
              stroke="var(--text-3)" strokeWidth="0.8" strokeDasharray="3 2"
              markerEnd="url(#arrow)"
            />
            <rect x={p.x} y={p.y} width="36" height="14" rx="2" fill="var(--bg-3)" stroke="var(--border-2)" />
            <text x={p.x + 18} y={p.y + 9.5} textAnchor="middle" fill="var(--text-2)" fontSize="7.5" fontFamily="JetBrains Mono">
              {citedTop[i]}
            </text>
          </g>
        ))}
        {byPos.map((p, i) => (
          <g key={`citedby-${i}`}>
            <line
              x1={cx + 10} y1={cy}
              x2={p.x} y2={p.y + 7}
              stroke="var(--accent)" strokeWidth="0.8" opacity="0.6"
              markerEnd="url(#arrow2)"
            />
            <rect x={p.x} y={p.y} width="36" height="14" rx="2" fill="var(--bg-3)" stroke="var(--border-2)" />
            <text x={p.x + 18} y={p.y + 9.5} textAnchor="middle" fill="var(--text-2)" fontSize="7.5" fontFamily="JetBrains Mono">
              {citedByTop[i]}
            </text>
          </g>
        ))}
        <defs>
          <marker id="arrow" markerWidth="5" markerHeight="5" refX="5" refY="2.5" orient="auto">
            <path d="M0,0 L5,2.5 L0,5" fill="var(--text-3)" />
          </marker>
          <marker id="arrow2" markerWidth="5" markerHeight="5" refX="5" refY="2.5" orient="auto">
            <path d="M0,0 L5,2.5 L0,5" fill="var(--accent)" opacity="0.7" />
          </marker>
        </defs>
        <circle
          cx={cx} cy={cy} r="10"
          fill={agent.signal === 'buy' ? 'var(--buy)' : agent.signal === 'sell' ? 'var(--sell)' : 'var(--hold)'}
        />
        <text x={cx} y={cy + 3.5} textAnchor="middle" fill="#000" fontSize="6.5" fontWeight="700" fontFamily="JetBrains Mono">
          {agent.id}
        </text>
      </svg>
      <div className="iv2-cite-legend">
        <div><span className="iv2-cite-dot cited" /> read {cited.length}</div>
        <div><span className="iv2-cite-dot citedby" /> cited by {citedBy.length}</div>
      </div>
    </div>
  );
}

type Message = {
  role: 'user' | 'agent' | 'error';
  ts: string;
  text: string;
};

function nowTs(): string {
  return new Date().toISOString().slice(11, 19);
}

interface InterviewV2Props {
  agent: AgentView;
  onClose: () => void;
}

export function InterviewV2({ agent, onClose }: InterviewV2Props) {
  // Initial message — generic header, no PERSONA filler (KR-41.6-03).
  const [messages, setMessages] = useState<Message[]>([
    {
      role: 'agent',
      ts: nowTs(),
      text: `${agent.bracketDisplay}. Round 3 close: ${agent.signal.toUpperCase()}, confidence ${(agent.confidence * 100).toFixed(0)}%.${
        agent.flipped ? ' Flipped from Round 1.' : ''
      } Ask me about my reasoning.`,
    },
  ]);
  const [input, setInput] = useState<string>('');
  const [tab, setTab] = useState<'chat' | 'rationale'>('chat');
  const [busy, setBusy] = useState<boolean>(false);
  const logRef = useRef<HTMLDivElement | null>(null);

  // Live rationales filtered by agent + grouped by round.
  const { rationales } = useRationales();
  const agentRationales = useMemo(
    () => rationales.filter((r) => r.agentId === agent.id),
    [rationales, agent.id],
  );
  const byRound = useMemo<RoundMap>(() => {
    const m: RoundMap = { 1: [], 2: [], 3: [] };
    agentRationales.forEach((r) => {
      if (m[r.round]) m[r.round].push(r);
    });
    return m;
  }, [agentRationales]);

  // Edges — fetch once when cycleId resolves; final round (3).
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

  // codex MEDIUM-7 — verified semantics:
  //   source_id = citing agent; target_id = cited agent.
  //   `cited`   = list of agents THIS agent cited (out-going citations from agent.id)
  //               → edges where source_id === agent.id, take target_id
  //   `citedBy` = list of agents who cited THIS agent (in-coming citations to agent.id)
  //               → edges where target_id === agent.id, take source_id
  const cited = useMemo(
    () => edges.filter((e) => e.source_id === agent.id).map((e) => e.target_id),
    [edges, agent.id],
  );
  const citedBy = useMemo(
    () => edges.filter((e) => e.target_id === agent.id).map((e) => e.source_id),
    [edges, agent.id],
  );

  // Auto-scroll log on new messages.
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [messages, busy]);

  const handleSend = async (overrideText?: string) => {
    const msg = (overrideText ?? input).trim();
    if (!msg || busy) return;
    setInput('');
    setMessages((prev) => [...prev, { role: 'user', text: msg, ts: nowTs() }]);
    setBusy(true);
    try {
      const resp = await askAgent(agent.id, msg);
      setMessages((prev) => [...prev, { role: 'agent', text: resp.response, ts: nowTs() }]);
    } catch (e) {
      const errMsg = e instanceof Error ? e.message : String(e);
      setMessages((prev) => [...prev, { role: 'error', text: `Error: ${errMsg}`, ts: nowTs() }]);
    } finally {
      setBusy(false);
    }
  };

  const sigColor = (s: string) =>
    s === 'buy' ? 'var(--buy)' : s === 'sell' ? 'var(--sell)' : 'var(--hold)';

  // Generic suggested prompts (not bracket-specific — PERSONA dict removed per KR-41.6-03).
  const prompts = [
    'What drove your signal?',
    'Which peer influenced you most?',
    'What would change your view?',
  ];

  return (
    <div className="iv2-takeover">
      {/* header */}
      <div className="iv2-head">
        <div className="iv2-head-left">
          <button className="btn ghost-btn" onClick={onClose}>
            <Icon name="close" />
          </button>
          <div className="iv2-agent-id">
            <div className="iv2-id-pill" style={{ background: sigColor(agent.signal) }}>
              {agent.id}
            </div>
            <div>
              <div className="iv2-bracket">{agent.bracketDisplay}</div>
              <div className="label">{agent.flipped ? 'FLIPPED' : 'HELD SIGNAL'}</div>
            </div>
          </div>
          <div
            className={`rationale-signal sig-${agent.signal}`}
            style={{ marginLeft: 8, fontSize: 11 }}
          >
            {agent.signal.toUpperCase()} {(agent.confidence * 100).toFixed(0)}%
          </div>
        </div>
        <div className="iv2-head-right">
          <span className="label" style={{ color: 'var(--accent)', fontSize: 11 }}>
            INTERVIEW · LIVE BACKEND
          </span>
        </div>
      </div>

      <div className="iv2-body">
        {/* LEFT — context rail */}
        <div className="iv2-left">
          <SignalTrajectory agent={agent} byRound={byRound} />
          <div className="iv2-divider" />
          <CitationGraph agent={agent} cited={cited} citedBy={citedBy} />
          <div className="iv2-divider" />
          <div className="iv2-stats">
            <div className="label" style={{ marginBottom: 8 }}>CYCLE STATS</div>
            {([
              ['Out-degree', String(cited.length)],
              ['In-degree', String(citedBy.length)],
              // KR-41.6-09: peer reads / shock impact / data sources have no live source.
              ['Peer reads', '—'],
              ['Shock impact', '—'],
              ['Data sources', '—'],
            ] as const).map(([k, v]) => (
              <div key={k} className="iv2-stat-row">
                <span className="iv2-stat-k label">{k}</span>
                <span className="iv2-stat-v mono">{v}</span>
              </div>
            ))}
          </div>
        </div>

        {/* CENTER — chat */}
        <div className="iv2-center">
          <div className="iv2-tabs">
            <button className="iv2-tab" data-active={tab === 'chat'} onClick={() => setTab('chat')}>
              Interview
            </button>
            <button
              className="iv2-tab"
              data-active={tab === 'rationale'}
              onClick={() => setTab('rationale')}
            >
              Rationale log
            </button>
          </div>

          {tab === 'chat' && (
            <>
              <div className="iv2-log" ref={logRef}>
                {messages.map((m, i) => (
                  <div key={i} className={`iv2-msg iv2-msg-${m.role}`}>
                    <div className="iv2-msg-meta">
                      <span className="iv2-msg-who">{m.role === 'user' ? 'YOU' : agent.id}</span>
                      <span className="iv2-msg-ts mono">{m.ts}</span>
                    </div>
                    <div className="iv2-bubble" data-role={m.role}>
                      {m.text}
                    </div>
                  </div>
                ))}
                {busy && (
                  <div className="iv2-msg iv2-msg-agent">
                    <div className="iv2-msg-meta">
                      <span className="iv2-msg-who">{agent.id}</span>
                    </div>
                    <div className="iv2-bubble iv2-typing" data-role="agent">
                      <span /><span /><span />
                    </div>
                  </div>
                )}
              </div>
              {/* generic suggested prompts (no PERSONA per KR-41.6-03) */}
              <div className="iv2-prompts">
                {prompts.map((p, i) => (
                  <button
                    key={i}
                    className="iv2-prompt"
                    onClick={() => void handleSend(p)}
                    disabled={busy}
                  >
                    {p}
                  </button>
                ))}
              </div>
              <div className="iv2-input-row">
                <div className="seed-input" style={{ flex: 1, height: 38 }}>
                  <span className="prefix">›</span>
                  <input
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !e.shiftKey) void handleSend();
                    }}
                    placeholder={`Ask ${agent.id} anything…`}
                    disabled={busy}
                    autoFocus
                  />
                </div>
                <button className="btn primary" onClick={() => void handleSend()} disabled={busy || !input.trim()}>
                  Ask
                </button>
              </div>
            </>
          )}

          {tab === 'rationale' && (
            <div className="iv2-rationale-log">
              {[1, 2, 3].map((round) => {
                const list = byRound[round] ?? [];
                if (list.length === 0) {
                  return (
                    <div key={round} className="iv2-round-block">
                      <div className="iv2-round-head">
                        <span className="iv2-round-num">Round {round}</span>
                        <span className="rationale-signal" style={{ color: 'var(--text-3)' }}>—</span>
                      </div>
                      <div className="iv2-round-text" style={{ color: 'var(--text-3)' }}>
                        No rationale yet for this round.
                      </div>
                      {round < 3 && <div className="iv2-round-connector" />}
                    </div>
                  );
                }
                return list.map((r, i) => (
                  <div key={`${round}-${i}`} className="iv2-round-block">
                    <div className="iv2-round-head">
                      <span className="iv2-round-num">Round {round}</span>
                      <span className={`rationale-signal sig-${agent.signal}`}>
                        {agent.signal.toUpperCase()}
                      </span>
                    </div>
                    <div className="iv2-round-text">{r.text}</div>
                    {round < 3 && <div className="iv2-round-connector" />}
                  </div>
                ));
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
