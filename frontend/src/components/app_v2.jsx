// Main app — committed to Quant Terminal direction (v2 shell).
// WAVE-1-NOTE: This is the actually-mounted AppShell. Behavioural notes:
//   • Claude-Artifacts postMessage bridge (window.parent.postMessage) REMOVED
//     — AlphaSwarm does not run inside an iframe.
//   • window.AS_DATA.buildAgents removed; agents default to []. Wave 2 wires
//     AgentsContext.
//   • window.AS_DATA.RATIONALES removed; rationales default to []. Wave 2
//     wires RationalesContext.
//   • ReactDOM.createRoot call removed — main.tsx owns mounting.
//   • SignalWire + DataSourcesModal remain mock-backed (see mocks/wire.ts
//     and mocks/sources.ts) per plan EXCEPTION.
import { useState, useEffect, useMemo } from 'react';
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
      <div className="t-head">{agent.id} <span style={{color:'var(--text-3)', fontSize:10}}>· {agent.bracketDisplay}</span></div>
      <div className="t-row"><span>Signal</span><strong className={`sig-${agent.signal}`} style={{padding:'1px 5px'}}>{agent.signal.toUpperCase()}</strong></div>
      <div className="t-row"><span>Confidence</span><strong>{(agent.confidence*100).toFixed(0)}%</strong></div>
      <div className="t-row"><span>Flipped R1→R3</span><strong>{agent.flipped ? 'Yes' : 'No'}</strong></div>
      <div className="t-row"><span>Peer reads</span><strong>{12 + ((agent.index ?? 0) % 18)}</strong></div>
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

export function App() {
  const [state, setState] = useState({
    layout: 'force',
    density: 'comfortable',
    phase: 2,
    sigMix: { buy: 0.30, sell: 0.45, hold: 0.25 },
    seed: 'Apple acquiring Anthropic for $500B — compute commitments unclear',
    running: true,
    replayCycle: null,
    tweaksOpen: false,
    hintsDismissed: false,
    demoState: 'live',
  });

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

  const [elapsed, setElapsed] = useState(258);
  const [tps, setTps] = useState(48.3);
  const [mem, setMem] = useState(72);
  const [slots, setSlots] = useState(12);

  useEffect(() => {
    if (!state.running) return;
    const t = window.setInterval(() => {
      setElapsed(e => e + 1);
      setTps(t => Math.max(20, Math.min(80, t + (Math.random() - 0.5) * 3.8)));
      setMem(m => Math.max(55, Math.min(92, m + (Math.random() - 0.5) * 2.2)));
      setSlots(s => Math.max(4, Math.min(16, s + Math.floor((Math.random() - 0.5) * 2))));
    }, 900);
    return () => window.clearInterval(t);
  }, [state.running]);

  const round = state.replayCycle ? state.phase : (state.phase === 'done' ? 3 : state.phase);
  // WAVE-1-NOTE: `buildAgents` removed. Wave 2 wires AgentsContext into
  // AppShell.tsx which supersedes this component.
  const agents = useMemo(() => [], []);
  // WAVE-1-NOTE: bracketSummaries removed — bracket list renders empty until
  // BracketContext is wired in Wave 2.
  const summaries = useMemo(() => [], []);

  // WAVE-1-NOTE: Claude-Artifacts postMessage bridge removed. AlphaSwarm does
  // not run inside an iframe parent, so there is nothing to communicate with.

  const phaseLabel =
    state.replayCycle ? `REPLAY · R${round}/3` :
    state.phase === 'done' ? 'COMPLETE' :
    `ROUND ${state.phase}/3`;
  const phaseState = state.replayCycle ? 'complete' : state.phase === 'done' ? 'complete' : 'live';

  const onAgentHover = (agent, e) => {
    if (!agent) { setUi(u => ({...u, tooltip: null})); return; }
    const rect = e.currentTarget.closest('.canvas-wrap').getBoundingClientRect();
    setUi(u => ({ ...u, tooltip: { agent, x: e.clientX - rect.left, y: e.clientY - rect.top } }));
  };
  const onAgentClick = (agent) => setUi(u => ({...u, interviewAgent: agent}));
  const onCiteClick = (agentId) => {
    const a = agents.find(x => x.id === agentId);
    if (a) setUi(u => ({...u, interviewAgent: a}));
  };

  return (
    <div className="app" data-dir="a" data-density={state.density} data-screen-label="01 Dashboard">
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

        <div className="seed-input">
          <span className="prefix">SEED ⟶</span>
          <input value={state.seed} onChange={e => setState(s => ({...s, seed: e.target.value}))} />
          <span className="seed-entities">3 entities</span>
        </div>

        {state.running ? (
          <button className="btn danger" onClick={() => setState(s => ({...s, running: false}))}><Icon name="stop" /> Stop</button>
        ) : (
          <button className="btn primary" onClick={() => setState(s => ({...s, running: true}))}><Icon name="play" /> Run</button>
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
        <button className="btn ghost-btn" onClick={() => setState(s => ({...s, tweaksOpen: !s.tweaksOpen}))} title="Tweaks">
          <Icon name="bolt" />
        </button>
      </div>

      {/* Signal Wire — live API activity ticker */}
      <SignalWire running={state.running} onInspect={() => setUi(u => ({...u, dataSourcesOpen: true}))} />

      {/* Main */}
      <div className="main">
        {/* Left */}
        <div className="col col-left">
          <div className="panel" style={{flex: '0 0 auto'}}>
            <div className="panel-head">
              <span className="panel-title">Brackets</span>
              <span className="label">{agents.length} AGENTS · R{round}</span>
            </div>
            <div className="panel-body">
              <BracketList summaries={summaries} onClick={() => {}} />
            </div>
          </div>

          <div className="panel">
            <div className="panel-head">
              <span className="panel-title">Top Influencers</span>
              <span className="label">OUT-DEGREE</span>
            </div>
            <div className="panel-body" style={{fontFamily:'JetBrains Mono', fontSize:11}}>
              {[
                { id: 'Q-03', out: 31, bracket: 'Quants' },
                { id: 'P-02', out: 22, bracket: 'Policy Wonks' },
                { id: 'I-04', out: 18, bracket: 'Insiders' },
                { id: 'M-06', out: 14, bracket: 'Macro' },
                { id: 'X-01', out: 11, bracket: 'Doom-Posters' },
              ].map(r => (
                <div key={r.id} className="influencer-row">
                  <span className="infl-id" onClick={() => onCiteClick(r.id)}>{r.id}</span>
                  <span className="infl-bracket">{r.bracket}</span>
                  <div className="infl-bar"><span style={{width: `${(r.out/31)*100}%`}} /></div>
                  <span className="infl-num">{r.out}</span>
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
                <button key={r} className="round-tab" data-active={round === r && state.phase !== 'done'}
                  onClick={() => setState(s => ({...s, phase: r}))}>R{r}</button>
              ))}
              <button className="round-tab" data-active={state.phase === 'done'}
                onClick={() => setState(s => ({...s, phase: 'done'}))}>FINAL</button>
            </div>
            <span className="topstrip-meta">{agents.filter(a => a.flipped).length} flips since R1 · {55} active edges</span>
            <div className="layout-tabs">
              <span className="label" style={{marginRight:6}}>LAYOUT</span>
              {[
                { k: 'force', icon: 'graph', label: 'Force' },
                { k: 'radial', icon: 'radial', label: 'Radial' },
                { k: 'grid', icon: 'grid', label: 'Grid' },
              ].map(l => (
                <button key={l.k} className="layout-btn" data-active={state.layout === l.k}
                  onClick={() => setState(s => ({...s, layout: l.k}))} title={l.label}><Icon name={l.icon} /></button>
              ))}
            </div>
          </div>

          <div className="canvas-wrap">
            {(() => {
              const ds = state.demoState || 'live';
              if (ds === 'idle')     return <IdleState seed={state.seed} />;
              if (ds === 'seeding')  return <SeedingState />;
              if (ds === 'mempause') return <MemoryPausedState onResume={() => setState(s => ({...s, demoState: 'live'}))} />;
              if (ds === 'error')    return <ErrorState onRetry={() => setState(s => ({...s, demoState: 'live'}))} />;
              return <>
                <Viz
                  agents={agents}
                  layout={state.layout}
                  direction="a"
                  highlightId={ui.tooltip?.agent?.id}
                  onAgentHover={onAgentHover}
                  onAgentClick={onAgentClick}
                  round={round}
                />
                <ConsensusRing agents={agents} />
                <Legend />
                <Tooltip info={ui.tooltip} />
              </>;
            })()}

            {!state.hintsDismissed && (
              <div className="first-hint">
                <span className="label" style={{color:'var(--accent)'}}>TIP</span>
                <span>Each node is one of 100 agents · color = signal · hover for detail · click to interview</span>
                <button className="btn ghost" style={{height:22, padding:'0 8px'}} onClick={() => setState(s => ({...s, hintsDismissed: true}))}>Got it</button>
              </div>
            )}

            {ui.shockOpen && (
              <ShockDrawer
                onClose={() => setUi(u => ({...u, shockOpen: false}))}
                onInject={() => {}}
              />
            )}

            {state.replayCycle && (
              <ReplayBar
                cycle={state.replayCycle}
                round={round}
                onRound={(r) => setState(s => ({...s, phase: r === 0 ? 1 : r}))}
                onExit={() => setState(s => ({...s, replayCycle: null, phase: 2}))}
              />
            )}
          </div>

          <KpiStrip agents={agents} tps={tps} mem={Math.round(mem)} slots={slots} elapsed={elapsed} round={round === 'done' ? 3 : round} />
        </div>

        {/* Right */}
        <div className="col col-right">
          <div className="panel">
            <div className="panel-head">
              <span className="panel-title">Rationale Feed</span>
              <span className="label live-indicator"><span className="live-dot" /> LIVE · R{round}</span>
            </div>
            <div className="panel-body">
              {/* WAVE-1-NOTE: RATIONALES removed. Wave 2 wires RationalesContext. */}
              <RationaleFeed
                rationales={[]}
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
          onOpenReport={(c) => setUi(u => ({...u, historyOpen: false, reportOpen: true}))}
        />
      )}
      {ui.settingsOpen && <Settings onClose={() => setUi(u => ({...u, settingsOpen: false}))} />}
      {ui.cyclePickerOpen && (
        <CyclePickerModal
          onPick={(c) => { setState(s => ({...s, replayCycle: c, phase: 3, running: false})); setUi(u => ({...u, cyclePickerOpen: false})); }}
          onClose={() => setUi(u => ({...u, cyclePickerOpen: false}))}
        />
      )}

      {state.tweaksOpen && (
        <TweaksPanel state={state} setState={setState} onClose={() => setState(s => ({...s, tweaksOpen: false}))} />
      )}
    </div>
  );
}
