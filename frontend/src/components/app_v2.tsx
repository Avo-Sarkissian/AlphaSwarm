// Main dashboard shell — Quant Terminal direction.
//
// Lifted from AlphaSwarm-2/src/app_v2.jsx (W2 Plan 41.6-02 task 3) and
// rewired to live data per D-03 / D-07 / D-14 / KR-41.6-08.
//
// Wiring map (RESEARCH.md rows 1-14):
//   • useTelemetry() → tps / memMb / slotsUsed / slotsMax / elapsedSeconds /
//     phase / running (replaces source's setInterval mock telemetry clock)
//   • useAgents() → agents (replaces source's design-mock agent builder)
//   • useBrackets() → bracket summaries (replaces source's mock summariser)
//   • useRationales() → rationale feed (replaces source's static fixture)
//   • useConnection() → reconnectFailed gate for ErrorState
//   • simStart(seed) / simStop() from api/simulation → Topbar Run/Stop
//   • Lifecycle dispatch: ErrorState > MemoryPausedState (memMb>=90) >
//     SeedingState (phase=='initializing') > IdleState (phase=='idle' && !running)
//     > running dashboard (Viz + KpiStrip + ConsensusRing + BracketList + RationaleFeed)
//
// Modal mounts (Interview, Report, Shock, Replay, CyclePicker, AdvisoryV2,
// SignalWire ticker, DataSources takeover, BracketDeepDive) are stubbed for
// W2; W3 Plan 03 + W4 Plan 04 wire them.
//
// ModelStatus chip: hardcoded 'qwen3:8b' (KR-41.6-08, matches
// src/alphaswarm/config.py:32 OllamaSettings.worker_model default — Phase
// 41.4 locked qwen3:8b worker + qwen3.6:27b orchestrator with think=OFF).
import { useMemo, useState } from 'react';
import { Icon } from './icons';
import { Viz } from './viz';
import { BracketList, RationaleFeed, KpiStrip, ConsensusRing } from './panels';
import { IdleState, SeedingState, MemoryPausedState, ErrorState } from './states';
import { TweaksPanelLoader } from './TweaksPanelLoader';
import { useAgents } from '../context/AgentsContext';
import { useBrackets } from '../context/BracketContext';
import { useTelemetry } from '../context/TelemetryContext';
import { useRationales } from '../context/RationalesContext';
import { useConnection } from '../context/ConnectionContext';
import { useEdgesCtx } from '../context/EdgesContext';
import { simStart, simStop } from '../api/simulation';
// Plan 41.6-03 task 3 (W3): real ported components replace W2 stub overlays.
// modals.jsx, history.tsx, settings.tsx, v2.tsx, ReportModal.tsx live alongside.
import { SignalWire, ModelStatus, DataSourcesTakeover, AdvisoryV2 } from './v2';
import { ShockDrawer, ReplayBar, CyclePickerModal } from './modals';
import { ReportModal } from './ReportModal';
import { CycleHistory } from './history';
import { Settings } from './settings';
// Plan 41.6-04 task 2 (W4): real ported components replace W2/W3 stub overlays.
import { InterviewV2 } from './interview_v2';
import { BracketDeepDive } from './bracket_deep';

function BrandMark() {
  const nodes: [number, number][] = [[8,2],[4,8],[12,8],[2,14],[8,14],[14,14],[6,11],[10,11]];
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

interface TooltipInfo {
  agent: any;
  x: number;
  y: number;
}

function Tooltip({ info }: { info: TooltipInfo | null }) {
  if (!info) return null;
  const { agent, x, y } = info;
  return (
    <div className="tooltip" style={{ left: x + 14, top: y + 14 }}>
      <div className="t-head">{agent.id} <span style={{color:'var(--text-3)', fontSize:10}}>· {agent.bracketDisplay}</span></div>
      <div className="t-row"><span>Signal</span><strong className={`sig-${agent.signal}`} style={{padding:'1px 5px'}}>{(agent.signal || 'hold').toUpperCase()}</strong></div>
      <div className="t-row"><span>Confidence</span><strong>{(agent.confidence*100).toFixed(0)}%</strong></div>
      <div className="t-row"><span>Flipped R1→R3</span><strong>{agent.flipped ? 'Yes' : 'No'}</strong></div>
      <div style={{marginTop:6, fontSize:10, color:'var(--text-3)'}}>Click to interview →</div>
    </div>
  );
}

type ComingSoonKey = 'whatif' | 'multiseed' | 'stress' | 'brackets';

const COMING_SOON_COPY: Record<ComingSoonKey, { title: string; subtitle: string; body: string }> = {
  whatif: {
    title: 'What-if Compare',
    subtitle: 'COMPARE TWO SIMULATION SEEDS SIDE-BY-SIDE',
    body:
      'Run two seed rumors through the swarm in parallel and diff the resulting consensus, ' +
      'bracket distributions, and influence topology. Useful for testing how the same agents ' +
      'react to different framings of the same underlying event.\n\n' +
      'Requires backend support for paired-cycle dispatch and a dual-snapshot WS contract.',
  },
  multiseed: {
    title: 'Multi-seed Synthesis',
    subtitle: 'AGGREGATE SIGNAL ACROSS MULTIPLE SEEDS',
    body:
      'Submit a batch of related rumors (e.g. 10 paraphrasings of one event) and have the ' +
      'orchestrator synthesize a meta-advisory across all resulting cycles. Surfaces consensus ' +
      'that is stable across framings vs. seed-dependent artifacts.\n\n' +
      'Requires backend batch-orchestration and a synthesizer pass over N completed cycles.',
  },
  stress: {
    title: 'Portfolio Stress Test',
    subtitle: 'SHOCK YOUR PORTFOLIO THROUGH THE SWARM',
    body:
      'Inject a hypothetical macro/idiosyncratic shock mid-cycle and watch how each bracket ' +
      'updates. Returns a per-holding sensitivity map and worst-case drawdown estimates ' +
      'derived from the post-shock consensus distribution.\n\n' +
      'Requires the existing shock-injection wiring (Phase 35.1) plus a portfolio-aware ' +
      'risk aggregator on the orchestrator side.',
  },
  brackets: {
    title: 'Customize Brackets',
    subtitle: 'ADJUST BRACKET COMPOSITION + PERSONAS',
    body:
      'Edit the 10 bracket archetypes (counts, risk profiles, persona prompts) before a run. ' +
      'Save and reload bracket presets to test how the swarm behaves with different ' +
      'compositions (e.g. all degens, no whales).\n\n' +
      'Requires a persona-edit UI and a per-cycle bracket-override channel through the ' +
      'config layer.',
  },
};

function ComingSoonModal({
  feature,
  onClose,
}: {
  feature: ComingSoonKey;
  onClose: () => void;
}) {
  const copy = COMING_SOON_COPY[feature];
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <button className="btn ghost-btn" onClick={onClose} aria-label="Close">
            <Icon name="close" />
          </button>
          <div style={{ flex: 1 }}>
            <div style={{ color: 'var(--text)', fontSize: 15, fontWeight: 600 }}>
              {copy.title}
            </div>
            <div
              className="label"
              style={{ marginTop: 2, color: 'var(--text-3)', letterSpacing: '0.12em' }}
            >
              {copy.subtitle}
            </div>
          </div>
          <span
            style={{
              padding: '3px 8px',
              border: '1px solid color-mix(in srgb, var(--accent) 35%, transparent)',
              borderRadius: 10,
              color: 'var(--accent)',
              fontSize: 10,
              letterSpacing: '0.12em',
            }}
          >
            COMING IN v6.x
          </span>
        </div>
        <div className="modal-body">
          {copy.body.split('\n\n').map((p, i) => (
            <p
              key={i}
              style={{
                color: 'var(--text-2)',
                fontSize: 13,
                lineHeight: 1.65,
                margin: i === 0 ? '0 0 12px' : '0',
              }}
            >
              {p}
            </p>
          ))}
        </div>
      </div>
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

interface UiState {
  shockOpen: boolean;
  cyclePickerOpen: boolean;
  interviewAgent: any | null;
  interviewV2Agent: any | null;
  reportOpen: boolean;
  advisoryOpen: boolean;
  dataSourcesOpen: boolean;
  watchOpen: boolean;
  settingsOpen: boolean;
  historyOpen: boolean;
  bracketDeepDive: any | null;
  overflowOpen: boolean;
  seedSuggestOpen: boolean;
  tooltip: TooltipInfo | null;
  // Coming-in-v6.x placeholders surfaced from the overflow menu.
  comingSoon: 'whatif' | 'multiseed' | 'stress' | 'brackets' | null;
}

export function App() {
  // Live data via 6-context tree (W1 Plan 01 wiring).
  const { agents } = useAgents();
  const { brackets } = useBrackets();
  const { rationales } = useRationales();
  const { reconnectFailed } = useConnection();
  const tel = useTelemetry();
  const { edges } = useEdgesCtx();
  const phase = tel.phase;
  const running = tel.running;
  const tps = tel.telemetry.tps;
  const memMb = tel.telemetry.memMb;
  const slotsUsed = tel.telemetry.slotsUsed;
  // slotsMax read inside <ModelStatus /> (W2 stub used it directly here)
  const elapsedSeconds = tel.telemetry.elapsedSeconds;

  // Local UI state — chrome only (no live data here).
  const [seed, setSeed] = useState<string>('');
  const [layout, setLayout] = useState<'force' | 'radial' | 'grid'>('force');
  const [hintsDismissed, setHintsDismissed] = useState(false);
  const [tweaksOpen, setTweaksOpen] = useState(false);
  const [tweakState, setTweakState] = useState<{
    layout: string; density: string; phase: any; sigMix: { buy: number; sell: number; hold: number };
    demoState: string;
  }>({
    layout: 'force', density: 'comfortable', phase: 2,
    sigMix: { buy: 0.30, sell: 0.45, hold: 0.25 }, demoState: 'live',
  });
  const [ui, setUi] = useState<UiState>({
    shockOpen: false,
    cyclePickerOpen: false,
    interviewAgent: null,
    interviewV2Agent: null,
    reportOpen: false,
    advisoryOpen: false,
    dataSourcesOpen: false,
    watchOpen: false,
    settingsOpen: false,
    historyOpen: false,
    bracketDeepDive: null,
    overflowOpen: false,
    seedSuggestOpen: false,
    tooltip: null,
    comingSoon: null,
  });

  // Context-shape → panel-shape adapters.
  // BracketList expects {bracket, display_name, total, buy_count, sell_count, hold_count}.
  // BracketSummaryView ships {bracket, display, total, buy, sell, hold}.
  const summaries = useMemo(
    () => brackets.map(b => ({
      bracket: b.bracket,
      display_name: b.display,
      total: b.total,
      buy_count: b.buy,
      sell_count: b.sell,
      hold_count: b.hold,
    })),
    [brackets],
  );
  // RationaleFeed expects {agent, bracket, signal, round, text, cites}.
  // RationaleView ships {agentId, round, text, citations, sources, ts}.
  // KR-41.1-10: citations are stubbed [] in the adapter; render shows no cites
  // until backend RationaleEntry carries cited_agents.
  const feedRationales = useMemo(
    () => rationales.map(r => {
      const a = agents.find(ag => ag.id === r.agentId);
      return {
        agent: r.agentId,
        bracket: a?.bracketDisplay ?? '',
        signal: a?.signal ?? 'hold',
        round: r.round,
        text: r.text,
        cites: r.citations ?? [],
      };
    }),
    [rationales, agents],
  );

  // Top Influencers: rank by OUT-DEGREE when edges are available (post-cycle),
  // fall back to confidence rank for live/early frames (KR-41.1-09).
  const outDegree = useMemo(() => {
    const out: Record<string, number> = {};
    for (const [source] of edges) out[source] = (out[source] ?? 0) + 1;
    return out;
  }, [edges]);
  const hasEdges = edges.length > 0;
  const topInfluencers = useMemo(() => {
    if (hasEdges) {
      const maxOut = Math.max(1, ...Object.values(outDegree));
      return [...agents]
        .map(a => ({ a, deg: outDegree[a.id] ?? 0 }))
        .sort((x, y) => y.deg - x.deg)
        .slice(0, 5)
        .map(({ a, deg }) => ({
          id: a.id,
          bracket: a.bracketDisplay,
          out: deg,
          barPct: Math.round((deg / maxOut) * 100),
        }));
    }
    return [...agents]
      .sort((a, b) => b.confidence - a.confidence)
      .slice(0, 5)
      .map(a => ({
        id: a.id,
        bracket: a.bracketDisplay,
        out: Math.round(a.confidence * 100),
        barPct: Math.round(a.confidence * 100),
      }));
  }, [agents, outDegree, hasEdges]);

  // Parse round from backend phase string. Backend emits phase as 'round_1' /
  // 'round_2' / 'round_3' / 'complete' / 'idle' / 'initializing'. The original
  // Number(phase) parse returned NaN for 'round_N' strings, falling back to 2
  // even during round_1, causing the bracket panel header to show R2 while the
  // topbar showed ROUND_1.
  const round = (() => {
    if (phase === 'done' || phase === 'complete') return 3;
    if (typeof phase === 'string') {
      const m = phase.match(/^round[_-]?(\d+)$/i);
      if (m) return Number(m[1]);
      const n = Number(phase);
      if (Number.isFinite(n)) return n;
    }
    return 1;
  })();
  const phaseLabel =
    phase === 'done' ? 'COMPLETE' :
    phase === 'idle' ? 'IDLE' :
    phase === 'initializing' ? 'SEEDING' :
    typeof phase === 'string' && phase.startsWith('round') ? phase.toUpperCase() :
    `ROUND ${round}/3`;
  const phaseState: 'live' | 'complete' = phase === 'done' ? 'complete' : 'live';

  const onAgentHover = (agent: any, e: any) => {
    if (!agent) { setUi(u => ({ ...u, tooltip: null })); return; }
    const rect = e.currentTarget.closest('.canvas-wrap').getBoundingClientRect();
    setUi(u => ({ ...u, tooltip: { agent, x: e.clientX - rect.left, y: e.clientY - rect.top } }));
  };
  const onAgentClick = (agent: any) => setUi(u => ({ ...u, interviewV2Agent: agent }));
  const onCiteClick = (agentId: string) => {
    const a = agents.find(x => x.id === agentId);
    if (a) setUi(u => ({ ...u, interviewAgent: a }));
  };

  // Topbar Run/Stop handlers wire to api/simulation.
  const onRun = async () => {
    try {
      await simStart(seed);
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error('simStart failed', err);
    }
  };
  const onStop = async () => {
    try {
      await simStop();
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error('simStop failed', err);
    }
  };

  // Lifecycle dispatch — gate the dashboard render based on phase + telemetry.
  // Priority: error > paused > seeding > idle > running.
  if (reconnectFailed) {
    return <ErrorState onRetry={() => window.location.reload()} />;
  }
  if (memMb >= 90) {
    return <MemoryPausedState pct={Math.round(memMb)} onResume={onRun} />;
  }
  if (phase === 'initializing' || phase === 'seeding') {
    return <SeedingState seed={seed} />;
  }
  if (phase === 'idle' && !running) {
    return <IdleState seed={seed} setSeed={setSeed} onStart={onRun} ollamaOk />;
  }

  return (
    <div className="app" data-dir="a" data-density="comfortable" data-screen-label="01 Dashboard">
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

        <div style={{flex:1, minWidth:200, position:'relative', display:'flex', alignItems:'center', gap:6}}>
          <div className="seed-input" style={{flex:1}}>
            <span className="prefix">SEED ⟶</span>
            <input value={seed} onChange={e => setSeed(e.target.value)} />
            <span className="seed-entities">3 entities</span>
          </div>
          <button className="btn ghost-btn" title="Inspire — suggest a seed scenario"
            style={{color: ui.seedSuggestOpen ? 'var(--accent)' : undefined}}
            onClick={() => setUi(u => ({...u, seedSuggestOpen: !u.seedSuggestOpen}))}>✦</button>
        </div>

        {running ? (
          <button className="btn danger" onClick={onStop}><Icon name="stop" /> Stop</button>
        ) : (
          <button className="btn primary" onClick={onRun}><Icon name="play" /> Run</button>
        )}

        <ModelStatus />

        <div className="topbar-divider" />

        <button className="btn ghost-btn" onClick={() => setUi(u => ({...u, shockOpen: !u.shockOpen}))} title="Inject shock event">
          <Icon name="bolt" />
        </button>
        <button className="btn ghost-btn" onClick={() => setUi(u => ({...u, watchOpen: true}))} title="Watch / replay">
          <Icon name="replay" />
        </button>
        <button className="btn ghost-btn" onClick={() => setUi(u => ({...u, reportOpen: true}))} title="Simulation report">
          <Icon name="doc" />
        </button>
        <button className="btn ghost-btn" onClick={() => setUi(u => ({...u, settingsOpen: true}))} title="Settings">
          <Icon name="settings" />
        </button>

        <div style={{position:'relative'}}>
          <button className="btn ghost-btn" title="More tools"
            style={{color: ui.overflowOpen ? 'var(--accent)' : undefined}}
            onClick={() => setUi(u => ({...u, overflowOpen: !u.overflowOpen}))}>
            <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
              <circle cx="3" cy="7.5" r="1.3" fill="currentColor"/>
              <circle cx="7.5" cy="7.5" r="1.3" fill="currentColor"/>
              <circle cx="12" cy="7.5" r="1.3" fill="currentColor"/>
            </svg>
          </button>
          {ui.overflowOpen && (
            <div style={{
              position:'absolute', right:0, top:'calc(100% + 6px)',
              background:'var(--bg-2)', border:'1px solid var(--border-2)',
              borderRadius:5, minWidth:210, zIndex:200,
              boxShadow:'0 12px 32px rgba(0,0,0,0.5)',
              overflow:'hidden',
            }}
              onMouseLeave={() => setUi(u => ({...u, overflowOpen: false}))}>
              {[
                { label:'What-if Compare',       icon:'graph',    action: (u: UiState) => ({...u, comingSoon: 'whatif' as const,    overflowOpen: false}) },
                { label:'Multi-seed Synthesis',  icon:'bolt',     action: (u: UiState) => ({...u, comingSoon: 'multiseed' as const, overflowOpen: false}) },
                { label:'Data Sources',          icon:'search',   action: (u: UiState) => ({...u, dataSourcesOpen: true,            overflowOpen: false}) },
                { label:'Portfolio Stress Test', icon:'doc',      action: (u: UiState) => ({...u, comingSoon: 'stress' as const,    overflowOpen: false}) },
                { label:'Advisory (v6.0)',       icon:'brief',    action: (u: UiState) => ({...u, advisoryOpen: true,               overflowOpen: false}) },
                { label:'Customize Brackets',    icon:'settings', action: (u: UiState) => ({...u, comingSoon: 'brackets' as const,  overflowOpen: false}) },
                { label:'Cycle History',         icon:'replay',   action: (u: UiState) => ({...u, historyOpen: true,                overflowOpen: false}) },
              ].map(item => (
                <button key={item.label} onClick={() => setUi(item.action)}
                  style={{
                    display:'flex', alignItems:'center', gap:10,
                    width:'100%', padding:'9px 14px',
                    background:'transparent', border:'none', borderBottom:'1px solid var(--border)',
                    color:'var(--text-2)', cursor:'pointer',
                    fontFamily:"'JetBrains Mono', monospace", fontSize:11, letterSpacing:'0.04em',
                    textAlign:'left', transition:'all .1s',
                  }}>
                  <span style={{color:'var(--text-3)', flexShrink:0}}><Icon name={item.icon} /></span>
                  {item.label}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Signal Wire ticker — real ported component (DEV-only mock per KR-41.6-14) */}
      <SignalWire onInspect={() => setUi((u) => ({ ...u, dataSourcesOpen: true }))} />

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
              <BracketList summaries={summaries} onClick={(s: any) => {
                setUi(u => ({...u, bracketDeepDive: s}));
              }} />
            </div>
          </div>

          <div className="panel">
            <div className="panel-head">
              <span className="panel-title">Top Influencers</span>
              <span className="label">{hasEdges ? 'OUT-DEGREE' : 'CONFIDENCE'}</span>
            </div>
            <div className="panel-body" style={{fontFamily:'JetBrains Mono', fontSize:11}}>
              {topInfluencers.length === 0 ? (
                <div style={{ padding: 12, color: 'var(--text-3)', fontSize: 10 }}>
                  no agents yet — waiting for first frame
                </div>
              ) : topInfluencers.map(r => (
                <div key={r.id} className="influencer-row">
                  <span className="infl-id" onClick={() => onCiteClick(r.id)}>{r.id}</span>
                  <span className="infl-bracket">{r.bracket}</span>
                  <div className="infl-bar"><span style={{width: `${r.barPct}%`}} /></div>
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
                <button key={r} className="round-tab" data-active={round === r && phase !== 'done'}>R{r}</button>
              ))}
              <button className="round-tab" data-active={phase === 'done'}>FINAL</button>
            </div>
            <span className="topstrip-meta">{agents.filter(a => a.flipped).length} flips since R1 · {hasEdges ? `${edges.length} active edges` : `${agents.length} agents`}</span>
            <div className="layout-tabs">
              <span className="label" style={{marginRight:6}}>LAYOUT</span>
              {[
                { k: 'force', icon: 'graph', label: 'Force' },
                { k: 'radial', icon: 'radial', label: 'Radial' },
                { k: 'grid', icon: 'grid', label: 'Grid' },
              ].map(l => (
                <button key={l.k} className="layout-btn" data-active={layout === l.k}
                  onClick={() => setLayout(l.k as any)} title={l.label}><Icon name={l.icon} /></button>
              ))}
            </div>
          </div>

          <div className="canvas-wrap">
            <Viz
              agents={agents}
              layout={layout}
              direction="a"
              highlightId={ui.tooltip?.agent?.id}
              onAgentHover={onAgentHover}
              onAgentClick={onAgentClick}
              round={round}
            />
            <ConsensusRing agents={agents} />
            <Legend />
            <Tooltip info={ui.tooltip} />

            {!hintsDismissed && (
              <div className="first-hint">
                <span className="label" style={{color:'var(--accent)'}}>TIP</span>
                <span>Each node is one of 100 agents · color = signal · hover for detail · click to interview</span>
                <button className="btn ghost" style={{height:22, padding:'0 8px'}} onClick={() => setHintsDismissed(true)}>Got it</button>
              </div>
            )}
          </div>

          <KpiStrip
            agents={agents}
            tps={tps}
            mem={Math.round(memMb)}
            slots={slotsUsed}
            elapsed={Math.round(elapsedSeconds)}
            round={round}
          />
        </div>

        {/* Right */}
        <div className="col col-right">
          <div className="panel">
            <div className="panel-head">
              <span className="panel-title">Rationale Feed</span>
              <span className="label live-indicator"><span className="live-dot" /> LIVE · R{round}</span>
            </div>
            <div className="panel-body">
              <RationaleFeed
                rationales={feedRationales}
                onAgentClick={onCiteClick}
                onCiteClick={onCiteClick}
              />
            </div>
          </div>
        </div>
      </div>

      {/* W4 real-wired modal mounts (Plan 41.6-04 task 2). All stub overlays
          replaced — InterviewV2 and BracketDeepDive now mount real components. */}
      {ui.interviewV2Agent && (
        <InterviewV2
          agent={ui.interviewV2Agent}
          onClose={() => setUi((u) => ({ ...u, interviewV2Agent: null }))}
        />
      )}
      {ui.interviewAgent && (
        <InterviewV2
          agent={ui.interviewAgent}
          onClose={() => setUi((u) => ({ ...u, interviewAgent: null }))}
        />
      )}
      {ui.bracketDeepDive && (
        <BracketDeepDive
          bracket={ui.bracketDeepDive}
          agents={agents.filter((a) => a.bracket.toLowerCase() === ui.bracketDeepDive.bracket.toLowerCase())}
          onAgentInterview={(a) => setUi((u) => ({ ...u, bracketDeepDive: null, interviewV2Agent: a }))}
          onClose={() => setUi((u) => ({ ...u, bracketDeepDive: null }))}
        />
      )}
      {ui.shockOpen && (
        <ShockDrawer onClose={() => setUi((u) => ({ ...u, shockOpen: false }))} />
      )}
      {ui.watchOpen && (
        <ReplayBar
          cycle={null}
          onExit={() => setUi((u) => ({ ...u, watchOpen: false }))}
        />
      )}
      {ui.reportOpen && (
        <ReportModal onClose={() => setUi((u) => ({ ...u, reportOpen: false }))} />
      )}
      {ui.advisoryOpen && (
        <AdvisoryV2 onClose={() => setUi((u) => ({ ...u, advisoryOpen: false }))} />
      )}
      {ui.dataSourcesOpen && (
        <DataSourcesTakeover
          onClose={() => setUi((u) => ({ ...u, dataSourcesOpen: false }))}
        />
      )}
      {ui.historyOpen && (
        <CycleHistory
          onClose={() => setUi((u) => ({ ...u, historyOpen: false }))}
          onOpenReport={() =>
            setUi((u) => ({ ...u, historyOpen: false, reportOpen: true }))
          }
        />
      )}
      {ui.settingsOpen && (
        <Settings onClose={() => setUi((u) => ({ ...u, settingsOpen: false }))} />
      )}
      {ui.comingSoon && (
        <ComingSoonModal
          feature={ui.comingSoon}
          onClose={() => setUi((u) => ({ ...u, comingSoon: null }))}
        />
      )}
      {ui.cyclePickerOpen && (
        <CyclePickerModal
          onClose={() => setUi((u) => ({ ...u, cyclePickerOpen: false }))}
          onPick={() =>
            setUi((u) => ({ ...u, cyclePickerOpen: false, watchOpen: true }))
          }
        />
      )}

      {/* Dev-only TweaksPanel mount — gated to import.meta.env.DEV inside loader */}
      {tweaksOpen && (
        <TweaksPanelLoader
          state={tweakState}
          setState={setTweakState as any}
          onClose={() => setTweaksOpen(false)}
        />
      )}
    </div>
  );
}
