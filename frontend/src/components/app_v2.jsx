// Main app — committed to Quant Terminal direction (v2 shell).
// WAVE-2-NOTE (Plan 41.1-03): rewired to Plan 02 split contexts + REST clients.
//   • No more local setInterval() for fake metrics — useTelemetry drives KPIs.
//   • No more window.AS_DATA / buildAgents / BRACKETS — useAgents feeds top
//     influencers & tooltips; useBrackets backs the bracket panel; useEdgesCtx
//     owns active-edges count (single source of truth, reviewer item 9).
//   • Start / Stop POSTs route through simStart/simStop (api/simulation.ts)
//     with ApiError-aware UI error banner (reviewer items 2, 4, 24).
//   • ShockDrawer remains state-toggled only — Plan 04 owns the shock POST
//     (reviewer item 17).
//   • Claude-Artifacts postMessage bridge stays removed.
import { useState } from 'react';
import { Icon } from './icons';
import { Viz } from './viz';
import { BracketList, RationaleFeed, KpiStrip, ConsensusRing } from './panels';
import {
  InterviewModal,
  ShockDrawer,
  AdvisoryModal,
  ReplayBar,
  CyclePickerModal,
} from './modals';
import { TweaksPanel } from './tweaks';
import { SignalWire, DataSourcesModal, ReportModalV2 } from './v2';
import { IdleState, SeedingState, MemoryPausedState, ErrorState } from './states';
import { CycleHistory } from './history';
import { Settings } from './settings';
import { useTelemetry } from '../context/TelemetryContext';
import { useAgents } from '../context/AgentsContext';
import { useBrackets } from '../context/BracketContext';
import { useEdgesCtx } from '../context/EdgesContext';
import { useConnection } from '../context/ConnectionContext';
import { simStart, simStop } from '../api/simulation';
import { ApiError } from '../api/client';

function BrandMark() {
  const nodes = [[8,2],[4,8],[12,8],[2,14],[8,14],[14,14],[6,11],[10,11]];
  return (
    <svg width="22" height="22" viewBox="0 0 16 16">
      {nodes.map((n, i) => (
        <circle key={i} cx={n[0]} cy={n[1]} r={i === 0 ? 2 : 1.3}
          fill={i === 0 ? 'var(--accent)' : 'var(--text)'} opacity={i === 0 ? 1 : 0.65} />
      ))}
      <path d="M8 2 L4 14 M8 2 L12 14 M6 11 L10 11" stroke="var(--text-3)" strokeWidth="0.4" fill="none" opacity="0.6" />
    </svg>
  );
}

function Tooltip({ info }) {
  if (!info) return null;
  const { agent, x, y } = info;
  return (
    <div className="tooltip" style={{ left: x + 14, top: y + 14 }}>
      <div className="t-head">{agent.id} <span style={{color:'var(--text-3)', fontSize:10}}>· {agent.bracketDisplay || agent.bracket}</span></div>
      <div className="t-row"><span>Signal</span><strong className={`sig-${agent.signal}`} style={{padding:'1px 5px'}}>{(agent.signal || 'hold').toUpperCase()}</strong></div>
      <div className="t-row"><span>Confidence</span><strong>{Math.round((agent.confidence ?? 0) * 100)}%</strong></div>
      <div className="t-row"><span>Flipped R1→R3</span><strong>{agent.flipped ? 'Yes' : 'No'}</strong></div>
      <div style={{marginTop:6, fontSize:10, color:'var(--text-3)'}}>Click to interview →</div>
    </div>
  );
}

function Legend() {
  return (
    <div className="legend">
      <div className="legend-row"><span className="chip" style={{background:'var(--buy)'}} /> BUY</div>
      <div className="legend-row"><span className="chip" style={{background:'var(--sell)'}} /> SELL</div>
      <div className="legend-row"><span className="chip" style={{background:'var(--hold)'}} /> HOLD</div>
      <div className="legend-divider" />
      <div className="legend-row"><span className="chip-ring" /> Flipped since R1</div>
      <div className="legend-row"><span className="chip-line" /> Influence edge</div>
    </div>
  );
}

function phaseStateFrom(phase, replayCycle) {
  if (replayCycle) return 'complete';
  if (phase === 'complete' || phase === 'done') return 'complete';
  return 'live';
}

function phaseLabelFrom(phase, replayCycle, roundNum) {
  if (replayCycle) return `REPLAY · R${roundNum ?? 1}/3`;
  if (phase === 'complete' || phase === 'done') return 'COMPLETE';
  if (phase === 'round_1') return 'ROUND 1/3';
  if (phase === 'round_2') return 'ROUND 2/3';
  if (phase === 'round_3') return 'ROUND 3/3';
  if (phase === 'seeding') return 'SEEDING…';
  if (phase === 'idle') return 'IDLE';
  return String(phase || '—').toUpperCase();
}

function roundChipFrom(phase) {
  if (phase === 'round_1' || phase === 1) return 'R1';
  if (phase === 'round_2' || phase === 2) return 'R2';
  if (phase === 'round_3' || phase === 3) return 'R3';
  if (phase === 'complete' || phase === 'done') return 'FINAL';
  return null;
}

function apiErrorMessage(e, verb) {
  if (e instanceof ApiError) {
    const body = e.body;
    let detail = 'backend rejected the request';
    if (body && typeof body === 'object') {
      const b = body;
      if (typeof b.detail === 'string') detail = b.detail;
      else if (b.detail && typeof b.detail === 'object' && typeof b.detail.message === 'string') {
        detail = b.detail.message;
      }
    }
    return `${verb} failed (${e.status}): ${detail}`;
  }
  return `${verb} failed: network or unknown error`;
}

export function App() {
  // Live contexts (Plan 02)
  const { phase, running } = useTelemetry();
  const { agents } = useAgents();
  const { brackets } = useBrackets();
  const { edges } = useEdgesCtx();
  const { reconnectFailed } = useConnection();

  // Local UI state only — no duplicate simulation state
  const [layout, setLayout] = useState('force');
  const [density] = useState('comfortable');
  const [seed, setSeed] = useState('Apple acquiring Anthropic for $500B — compute commitments unclear');
  const [replayCycle, setReplayCycle] = useState(null);
  const [tweaksOpen, setTweaksOpen] = useState(false);
  const [hintsDismissed, setHintsDismissed] = useState(false);
  const [demoState] = useState('live');

  const [ui, setUi] = useState({
    shockOpen: false,
    cyclePickerOpen: false,
    interviewAgent: null,
    reportOpen: false,
    advisoryOpen: false,
    tooltip: null,
    dataSourcesOpen: false,
    historyOpen: false,
    settingsOpen: false,
  });

  // REST state
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function onStart() {
    if (busy || running || !seed.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await simStart(seed.trim());
    } catch (e) {
      setError(apiErrorMessage(e, 'Start'));
    } finally {
      setBusy(false);
    }
  }

  async function onStop() {
    if (busy || !running) return;
    setBusy(true);
    setError(null);
    try {
      await simStop();
    } catch (e) {
      setError(apiErrorMessage(e, 'Stop'));
    } finally {
      setBusy(false);
    }
  }

  // Derived labels from live phase/round
  const roundNum =
    phase === 'round_1' ? 1 :
    phase === 'round_2' ? 2 :
    phase === 'round_3' ? 3 :
    (phase === 'complete' || phase === 'done') ? 3 : 1;

  const phaseLabel = phaseLabelFrom(phase, replayCycle, roundNum);
  const phaseState = phaseStateFrom(phase, replayCycle);
  const roundChip = roundChipFrom(phase);

  // Active-edges count reads from EdgesContext — NOT snapshot.edges
  // (Plan 02 adapter keeps StateFrame.edges empty in live mode — reviewer item 9).
  const edgeCount = edges.length;

  // KR-41.1-09 (tracked in Plan 05 UAT Row 16): live-view sort by confidence desc.
  // CONTRACT Report.influence.outDegree is report-only and unavailable during
  // live rounds, so top influencers here approximate by confidence.
  const topInfluencers = agents
    .slice()
    .sort((a, b) => (b.confidence ?? 0) - (a.confidence ?? 0))
    .slice(0, 5);
  const maxConfidence = topInfluencers.length > 0
    ? Math.max(0.0001, topInfluencers[0].confidence ?? 0.0001)
    : 1;

  const onAgentHover = (agent, e) => {
    if (!agent) { setUi(u => ({...u, tooltip: null})); return; }
    const rect = e.currentTarget.closest('.canvas-wrap')?.getBoundingClientRect();
    if (!rect) return;
    setUi(u => ({ ...u, tooltip: { agent, x: e.clientX - rect.left, y: e.clientY - rect.top } }));
  };
  const onAgentClick = (agent) => setUi(u => ({...u, interviewAgent: agent}));
  const onCiteClick = (agentId) => {
    const a = agents.find(x => x.id === agentId);
    if (a) setUi(u => ({...u, interviewAgent: a}));
  };

  return (
    <div className="app" data-dir="a" data-density={density} data-screen-label="01 Dashboard">
      {/* Top bar */}
      <div className="topbar">
        <div className="brand">
          <BrandMark />
          <div style={{display:'flex', flexDirection:'column'}}>
            <span className="brand-name">AlphaSwarm</span>
            <span className="brand-sub">Mission Control</span>
          </div>
        </div>

        <div className="phase-pill" data-state={phaseState}>
          <span className="dot" />
          {phaseLabel}
        </div>

        {roundChip && (
          <div className="round-chip" title="Current round">
            {roundChip}
          </div>
        )}

        <div className="seed-input">
          <span className="prefix">SEED ⟶</span>
          <input
            value={seed}
            onChange={(e) => setSeed(e.target.value)}
            placeholder="Seed rumor…"
            disabled={running}
          />
          <span className="seed-entities">{seed.trim() ? `${seed.trim().length} chars` : 'empty'}</span>
        </div>

        {running ? (
          <button
            className="btn danger"
            onClick={onStop}
            disabled={busy}
            title="Stop simulation"
          >
            <Icon name="stop" /> {busy ? 'Stopping…' : 'Stop'}
          </button>
        ) : (
          <button
            className="btn primary"
            onClick={onStart}
            disabled={busy || !seed.trim()}
            title="Start simulation"
          >
            <Icon name="play" /> {busy ? 'Starting…' : 'Run'}
          </button>
        )}

        <div className="topbar-divider" />

        <button className="btn ghost-btn" onClick={() => setUi(u => ({...u, shockOpen: !u.shockOpen}))} title="Inject disruptive event">
          <Icon name="bolt" />
        </button>
        <button className="btn ghost-btn" onClick={() => setUi(u => ({...u, historyOpen: true}))} title="Cycle history">
          <Icon name="replay" />
        </button>
        <button className="btn ghost-btn" onClick={() => setUi(u => ({...u, dataSourcesOpen: true}))} title="Data sources inspector">
          <Icon name="search" />
        </button>
        <button className="btn ghost-btn" onClick={() => setUi(u => ({...u, reportOpen: true}))} title="Simulation report">
          <Icon name="doc" />
        </button>
        <button className="btn ghost-btn" onClick={() => setUi(u => ({...u, advisoryOpen: true}))} title="Personalized advisory (v6.0)">
          <Icon name="brief" />
        </button>
        <button className="btn ghost-btn" onClick={() => setUi(u => ({...u, settingsOpen: true}))} title="Settings">
          <Icon name="settings" />
        </button>
        <button className="btn ghost-btn" onClick={() => setTweaksOpen(v => !v)} title="Tweaks">
          <Icon name="bolt" />
        </button>
      </div>

      {error && (
        <div className="topbar-error" role="alert" style={{
          padding: '6px 12px',
          background: 'var(--sell)',
          color: 'var(--text)',
          fontSize: 12,
          fontFamily: 'JetBrains Mono, monospace',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
        }}>
          <span>{error}</span>
          <button
            className="btn ghost"
            style={{ marginLeft: 'auto', height: 22, padding: '0 8px' }}
            onClick={() => setError(null)}
          >
            Dismiss
          </button>
        </div>
      )}

      {reconnectFailed && (
        <div className="connection-banner" role="alert" style={{
          padding: '6px 12px',
          background: 'var(--sell)',
          color: 'var(--text)',
          fontSize: 12,
          fontFamily: 'JetBrains Mono, monospace',
        }}>
          Connection lost — reconnect retries exhausted. Refresh to retry.
        </div>
      )}

      {/* Signal Wire — live API activity ticker (KR-41.1-02 mocks) */}
      <SignalWire running={running} onInspect={() => setUi(u => ({...u, dataSourcesOpen: true}))} />

      {/* Main */}
      <div className="main">
        {/* Left */}
        <div className="col col-left">
          <div className="panel" style={{flex: '0 0 auto'}}>
            <div className="panel-head">
              <span className="panel-title">Brackets</span>
              <span className="label">{agents.length} AGENTS · {roundChip ?? '—'}</span>
            </div>
            <div className="panel-body">
              <BracketList onClick={() => {}} />
            </div>
          </div>

          <div className="panel">
            <div className="panel-head">
              <span className="panel-title">Top Influencers</span>
              {/* KR-41.1-09: live-view uses confidence desc as a proxy;
                  CONTRACT Report.influence.outDegree remains report-only. */}
              <span className="label">CONFIDENCE</span>
            </div>
            <div className="panel-body" style={{fontFamily:'JetBrains Mono', fontSize:11}}>
              {topInfluencers.map(a => (
                <div key={a.id} className="influencer-row">
                  <span className="infl-id" onClick={() => onCiteClick(a.id)}>{a.id}</span>
                  <span className="infl-bracket">{a.bracketDisplay || a.bracket}</span>
                  <div className="infl-bar">
                    <span style={{width: `${((a.confidence ?? 0) / maxConfidence) * 100}%`}} />
                  </div>
                  <span className="infl-num">{Math.round((a.confidence ?? 0) * 100)}%</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Center */}
        <div className="col col-center">
          <div className="canvas-topstrip">
            <div className="round-tabs">
              {[1,2,3].map(r => (
                <button key={r} className="round-tab" data-active={roundChip === `R${r}`}
                  disabled>R{r}</button>
              ))}
              <button className="round-tab" data-active={roundChip === 'FINAL'} disabled>FINAL</button>
            </div>
            <span className="topstrip-meta">
              {agents.filter(a => a.flipped).length} flips since R1 · {edgeCount} active edges
            </span>
            <div className="layout-tabs">
              <span className="label" style={{marginRight:6}}>LAYOUT</span>
              {[
                { k: 'force', icon: 'graph', label: 'Force' },
                { k: 'radial', icon: 'radial', label: 'Radial' },
                { k: 'grid', icon: 'grid', label: 'Grid' },
              ].map(l => (
                <button key={l.k} className="layout-btn" data-active={layout === l.k}
                  onClick={() => setLayout(l.k)} title={l.label}><Icon name={l.icon} /></button>
              ))}
            </div>
          </div>

          <div className="canvas-wrap">
            {(() => {
              const ds = demoState;
              if (ds === 'idle')     return <IdleState seed={seed} />;
              if (ds === 'seeding')  return <SeedingState />;
              if (ds === 'mempause') return <MemoryPausedState />;
              if (ds === 'error')    return <ErrorState />;
              return <>
                <Viz
                  layout={layout}
                  direction="a"
                  highlightId={ui.tooltip?.agent?.id}
                  onAgentHover={onAgentHover}
                  onAgentClick={onAgentClick}
                />
                <ConsensusRing />
                <Legend />
                <Tooltip info={ui.tooltip} />
              </>;
            })()}

            {!hintsDismissed && (
              <div className="first-hint">
                <span className="label" style={{color:'var(--accent)'}}>TIP</span>
                <span>Each node is one of 100 agents · color = signal · hover for detail · click to interview</span>
                <button className="btn ghost" style={{height:22, padding:'0 8px'}} onClick={() => setHintsDismissed(true)}>Got it</button>
              </div>
            )}

            {ui.shockOpen && (
              <ShockDrawer
                onClose={() => setUi(u => ({...u, shockOpen: false}))}
                onInject={() => {}}
              />
            )}

            {replayCycle && (
              <ReplayBar
                cycle={replayCycle}
                round={roundNum}
                onRound={() => {}}
                onExit={() => setReplayCycle(null)}
              />
            )}
          </div>

          <KpiStrip />
        </div>

        {/* Right */}
        <div className="col col-right">
          <div className="panel">
            <div className="panel-head">
              <span className="panel-title">Rationale Feed</span>
              <span className="label live-indicator"><span className="live-dot" /> LIVE · {roundChip ?? '—'}</span>
            </div>
            <div className="panel-body">
              <RationaleFeed
                onAgentClick={onCiteClick}
                onCiteClick={onCiteClick}
              />
            </div>
          </div>
        </div>
      </div>

      {/* Modals */}
      {ui.interviewAgent && (
        <InterviewModal agent={ui.interviewAgent} onClose={() => setUi(u => ({...u, interviewAgent: null}))} />
      )}
      {ui.reportOpen && <ReportModalV2 onClose={() => setUi(u => ({...u, reportOpen: false}))} />}
      {ui.advisoryOpen && <AdvisoryModal onClose={() => setUi(u => ({...u, advisoryOpen: false}))} />}
      {ui.dataSourcesOpen && <DataSourcesModal onClose={() => setUi(u => ({...u, dataSourcesOpen: false}))} />}
      {ui.historyOpen && (
        <CycleHistory
          onClose={() => setUi(u => ({...u, historyOpen: false}))}
          onOpenReport={() => setUi(u => ({...u, historyOpen: false, reportOpen: true}))}
        />
      )}
      {ui.settingsOpen && <Settings onClose={() => setUi(u => ({...u, settingsOpen: false}))} />}
      {ui.cyclePickerOpen && (
        <CyclePickerModal
          onPick={(c) => { setReplayCycle(c); setUi(u => ({...u, cyclePickerOpen: false})); }}
          onClose={() => setUi(u => ({...u, cyclePickerOpen: false}))}
        />
      )}

      {tweaksOpen && (
        <TweaksPanel
          state={{ layout, density, seed, replayCycle, tweaksOpen, brackets }}
          setState={() => {}}
          onClose={() => setTweaksOpen(false)}
        />
      )}
    </div>
  );
}
