// Interview panel — full-screen takeover with signal trajectory, citation map,
// rationale log. Real-wired per docs/DECISIONS.md#p41-6-d-11,
// docs/DECISIONS.md#kr-41-6-03 and docs/DECISIONS.md#kr-41-1-11.
//
// Notes:
//   - PERSONA dict (filler) DELETED (docs/DECISIONS.md#kr-41-6-03).
//   - Source's setTimeout + keyword-matching response picker REPLACED with
//     await askAgent() — single POST /api/interview/{agent_id} → response in one
//     block (docs/DECISIONS.md#kr-41-1-11 non-streaming), for the cycle on screen.
//   - History comes from GET /api/agents/{id}/decisions (stored rounds) plus the
//     live signal for the round in progress; the agent is looked up live by id
//     (docs/DECISIONS.md#p14-d-06).
//   - CitationGraph reads cites/citedBy for the round on screen from EdgesContext,
//     with source_id = citing, target_id = cited.
//   - Cycle-stats panel: Cites / Cited by count the edges of the round on screen
//     from EdgesContext; rows without a live source are not rendered
//     (docs/DECISIONS.md#kr-41-6-09).
//
// Note: response is rendered as plain text, NOT through markdown
// (docs/DECISIONS.md#t-41-6-13). If markdown render is added later, gate it
// behind the same DOMPurify chain as the advisory panel and ReportModal.

import { useState, useEffect, useMemo, useRef } from 'react';
import { Icon } from '../../components/Icon';
import { InlineError } from '../../components/InlineError';
import { askAgent } from '../../api/interview';
import { useAgents } from '../../context/AgentsContext';
import { useEdgesCtx } from '../../context/EdgesContext';
import { useFrameMeta } from '../../context/FrameMetaContext';
import { demoLock } from '../../data-source';
import { useAgentDecisions } from '../../hooks/useAgentDecisions';
import { useLatestCompletedCycle } from '../../hooks/useLatestCompletedCycle';
import { useRounds } from '../../hooks/useRounds';
import { didFlip, mergeTrajectory, openingLine, resolveInterviewCycle, type TrajectoryPoint } from '../../lib/interview';
import { signalClass, signalColor, signalLabel } from '../../lib/signals';
import type { AgentView } from '../../types';

function SignalTrajectory({ points }: { points: TrajectoryPoint[] }) {
  const last = points.length - 1;
  return (
    <div className="itv-trajectory">
      <div className="label u-mb-10">SIGNAL TRAJECTORY</div>
      <div className="itv-traj-track">
        {points.map((p, i) => {
          const color = p.signal ? signalColor(p.signal) : 'var(--bg-3)';
          return (
            <div key={p.round} className="itv-traj-col" data-source={p.source}>
              <div className="itv-traj-bar-wrap">
                <div
                  className="itv-traj-bar"
                  style={{
                    height: p.confidence !== null ? `${p.confidence * 100}%` : '0%',
                    background: color,
                    boxShadow: i === last && p.signal ? `0 0 8px ${color}` : 'none',
                  }}
                />
              </div>
              <div className="itv-traj-signal" style={{ color: p.signal ? color : 'var(--text-3)' }}>
                {p.signal ? signalLabel(p.signal) : '—'}
              </div>
              <div className="itv-traj-label label">R{p.round}{p.source === 'live' ? ' · live' : ''}</div>
              <div className="itv-traj-conf mono">{p.confidence !== null ? `${Math.round(p.confidence * 100)}%` : '—'}</div>
            </div>
          );
        })}
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
    <div className="itv-citations">
      <div className="label u-mb-10">CITATION NETWORK</div>
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
            <text x={p.x + 18} y={p.y + 9.5} textAnchor="middle" fill="var(--text-2)" fontSize="7.5" style={{ fontFamily: 'var(--font-mono)' }}>
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
            <text x={p.x + 18} y={p.y + 9.5} textAnchor="middle" fill="var(--text-2)" fontSize="7.5" style={{ fontFamily: 'var(--font-mono)' }}>
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
          fill={signalColor(agent.signal)}
        />
        <text x={cx} y={cy + 3.5} textAnchor="middle" fill="#000" fontSize="6.5" fontWeight="700" style={{ fontFamily: 'var(--font-mono)' }}>
          {agent.id}
        </text>
      </svg>
      <div className="itv-cite-legend">
        <div><span className="itv-cite-dot cited" /> cites {cited.length}</div>
        <div><span className="itv-cite-dot citedby" /> cited by {citedBy.length}</div>
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

interface InterviewPanelProps {
  agentId: string;
  onClose: () => void;
}

export function InterviewPanel({ agentId, onClose }: InterviewPanelProps) {
  const lock = demoLock();
  // Look the agent up live on every frame instead of freezing the clicked object.
  const { agents } = useAgents();
  const agent = useMemo(() => agents.find((a) => a.id === agentId) ?? null, [agents, agentId]);
  const meta = useFrameMeta();
  const { rounds } = useRounds();
  const { cycleId: latestCompleted } = useLatestCompletedCycle();
  const cycleId = resolveInterviewCycle(meta.cycleId, latestCompleted);
  const { decisions, error: historyError, loading: historyLoading } = useAgentDecisions(
    agentId,
    cycleId,
    `${meta.roundNum ?? 0}:${meta.phase}`,
  );
  const points = useMemo(
    () =>
      mergeTrajectory(
        rounds,
        decisions,
        agent ? { roundNum: meta.roundNum, signal: agent.signal, confidence: agent.confidence } : null,
      ),
    [rounds, decisions, agent, meta.roundNum],
  );
  const flipped = didFlip(points);
  const headSignal = agent?.signal ?? null;
  const opening: Message = {
    role: 'agent',
    ts: '',
    text: openingLine({
      display: agent?.bracketDisplay ?? agentId,
      phase: meta.phase,
      roundNum: meta.roundNum,
      numRounds: meta.numRounds,
      signal: headSignal,
      confidence: agent?.confidence ?? 0,
    }),
  };
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState<string>('');
  // The read-only demo cannot ask the models, so it opens on the stored rationales.
  const [tab, setTab] = useState<'chat' | 'rationale'>(lock.locked ? 'rationale' : 'chat');
  const [busy, setBusy] = useState<boolean>(false);
  const logRef = useRef<HTMLDivElement | null>(null);

  // Citations of the round on screen, from the shared EdgesContext
  // (source_id cites target_id; docs/DECISIONS.md#adr-neo4j-schema).
  const { cites, citedBy: citedByMap } = useEdgesCtx();
  const cited = cites.get(agentId) ?? [];
  const citedBy = citedByMap.get(agentId) ?? [];

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
      const resp = await askAgent(agentId, msg, cycleId);
      setMessages((prev) => [...prev, { role: 'agent', text: resp.response, ts: nowTs() }]);
    } catch (e) {
      const errMsg = e instanceof Error ? e.message : String(e);
      setMessages((prev) => [...prev, { role: 'error', text: `Error: ${errMsg}`, ts: nowTs() }]);
    } finally {
      setBusy(false);
    }
  };

  // Generic suggested prompts (not bracket-specific; the PERSONA dict was removed,
  // docs/DECISIONS.md#kr-41-6-03).
  const prompts = [
    'What drove your signal?',
    'Which peer influenced you most?',
    'What would change your view?',
  ];

  return (
    <div className="itv-takeover">
      {/* header */}
      <div className="itv-head">
        <div className="itv-head-left">
          <button className="btn ghost-btn" onClick={onClose} aria-label="Close">
            <Icon name="close" />
          </button>
          <div className="itv-agent-id">
            <div className="itv-id-pill" style={{ background: headSignal ? signalColor(headSignal) : 'var(--bg-3)' }}>
              {agentId}
            </div>
            <div>
              <div className="itv-bracket">{agent?.bracketDisplay ?? agentId}</div>
              <div className="label">{flipped ? 'FLIPPED' : 'HELD SIGNAL'}</div>
            </div>
          </div>
          <div
            className={`rationale-signal ${signalClass(headSignal)}`}
            style={{ marginLeft: 8, fontSize: 11 }}
          >
            {signalLabel(headSignal)} {Math.round((agent?.confidence ?? 0) * 100)}%
          </div>
        </div>
        <div className="itv-head-right">
          <span className="label" style={{ color: 'var(--accent)', fontSize: 11 }}>
            INTERVIEW · LIVE BACKEND
          </span>
        </div>
      </div>

      <div className="itv-body">
        {/* LEFT — context rail */}
        <div className="itv-left">
          <SignalTrajectory points={points} />
          <div className="itv-divider" />
          {agent !== null && (
            <>
              <CitationGraph agent={agent} cited={cited} citedBy={citedBy} />
              <div className="itv-divider" />
            </>
          )}
          <div className="itv-stats">
            <div className="label u-mb-8">CYCLE STATS</div>
            {([
              ['Cites', String(cited.length)],
              ['Cited by', String(citedBy.length)],
            ] as const).map(([k, v]) => (
              <div key={k} className="itv-stat-row">
                <span className="itv-stat-k label">{k}</span>
                <span className="itv-stat-v mono">{v}</span>
              </div>
            ))}
          </div>
        </div>

        {/* CENTER — chat */}
        <div className="itv-center">
          <div className="itv-tabs">
            <button className="itv-tab" data-active={tab === 'chat'} onClick={() => setTab('chat')}>
              Interview
            </button>
            <button
              className="itv-tab"
              data-active={tab === 'rationale'}
              onClick={() => setTab('rationale')}
            >
              Rationale log
            </button>
          </div>

          {tab === 'chat' && (
            <>
              <div className="itv-log" ref={logRef}>
                {[opening, ...messages].map((m, i) => (
                  <div key={i} className={`itv-msg itv-msg-${m.role}`}>
                    <div className="itv-msg-meta">
                      <span className="itv-msg-who">{m.role === 'user' ? 'YOU' : agentId}</span>
                      <span className="itv-msg-ts mono">{m.ts}</span>
                    </div>
                    <div className="itv-bubble" data-role={m.role}>
                      {m.text}
                    </div>
                  </div>
                ))}
                {busy && (
                  <div className="itv-msg itv-msg-agent">
                    <div className="itv-msg-meta">
                      <span className="itv-msg-who">{agentId}</span>
                    </div>
                    <div className="itv-bubble itv-typing" data-role="agent">
                      <span /><span /><span />
                    </div>
                  </div>
                )}
              </div>
              {/* generic suggested prompts (no PERSONA, docs/DECISIONS.md#kr-41-6-03) */}
              <div className="itv-prompts">
                {prompts.map((p, i) => (
                  <button
                    key={i}
                    className="itv-prompt"
                    onClick={() => void handleSend(p)}
                    disabled={lock.locked || busy}
                  >
                    {p}
                  </button>
                ))}
              </div>
              <div className="itv-input-row">
                <div className="seed-input" style={{ flex: 1, height: 38 }}>
                  <span className="prefix">›</span>
                  <input
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !e.shiftKey) void handleSend();
                    }}
                    placeholder={`Ask ${agentId} anything…`}
                    disabled={lock.locked || busy}
                    title={lock.title}
                    data-autofocus
                  />
                </div>
                <button
                  className="btn primary"
                  onClick={() => void handleSend()}
                  disabled={lock.locked || busy || !input.trim()}
                  title={lock.title}
                  data-demo-lock="interview"
                >
                  Ask
                </button>
              </div>
            </>
          )}

          {tab === 'rationale' && (
            <div className="itv-rationale-log">
              {historyError && <InlineError error={historyError} />}
              {points.map((p, i) => (
                <div key={p.round} className="itv-round-block">
                  <div className="itv-round-head">
                    <span className="itv-round-num">Round {p.round}</span>
                    <span
                      className={p.signal ? `rationale-signal ${signalClass(p.signal)}` : 'rationale-signal'}
                      style={p.signal ? undefined : { color: 'var(--text-3)' }}
                    >
                      {p.signal ? signalLabel(p.signal) : '—'}
                    </span>
                  </div>
                  <div className="itv-round-text" style={p.rationale ? undefined : { color: 'var(--text-3)' }}>
                    {p.rationale ??
                      (p.source === 'live'
                        ? 'Decided this round; the rationale is stored when the round ends.'
                        : historyLoading
                          ? 'Loading…'
                          : 'No decision recorded for this round.')}
                  </div>
                  {i < points.length - 1 && <div className="itv-round-connector" />}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
