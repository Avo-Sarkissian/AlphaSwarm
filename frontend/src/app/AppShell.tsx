// Dashboard shell: topbar, banners, the dashboard grid, the replay bar and the
// single overlay slot (docs/DECISIONS.md#adr-frontend-quant-terminal).
import { useCallback, useEffect, useMemo, useState } from 'react';
import type { MouseEvent } from 'react';
import { Icon } from '../components/Icon';
import { Viz } from '../features/dashboard/Viz';
import type { VizLayout } from '../features/dashboard/vizLayout';
import type { AgentView } from '../types';
import { BracketList, RationaleFeed, KpiStrip, ConsensusRing } from '../features/dashboard/panels';
import { IdleState, SeedingState } from '../features/dashboard/StateOverlays';
import { useAgents } from '../context/AgentsContext';
import { useTelemetry } from '../context/TelemetryContext';
import { useRationales } from '../context/RationalesContext';
import { useConnection } from '../context/ConnectionContext';
import { useEdgesCtx } from '../context/EdgesContext';
import { simStop } from '../api/simulation';
import { useAwaitRunFrame } from '../hooks/useAwaitRunFrame';
import { useRunGate } from '../hooks/useRunGate';
import { useSampleHistory } from '../hooks/useSampleHistory';
import { bracketSpec } from '../data';
import { rankInfluencers } from '../lib/influence';
import { buildFeed, indexAgents } from '../lib/rationaleFeed';
import { signalClass, signalLabel } from '../lib/signals';
import { bracketTallies } from '../lib/tally';
import { phaseLabelFor } from '../lib/phase';
import { useRound, useRounds } from '../hooks/useRounds';
import { ModelStatus } from '../features/dashboard/ModelStatus';
import { SignalWire } from '../features/wire/SignalWire';
import { ReplayBar } from '../features/dashboard/ReplayBar';
import { InlineError } from '../components/InlineError';
import { RunErrorBanner } from '../features/dashboard/RunErrorBanner';
import { RunControls } from './RunControls';
import { ModalHost, type ActiveModal } from './ModalHost';
import { useFrameMeta } from '../context/FrameMetaContext';
import { formatApiError } from '../lib/apiError';
import { lifecycleOf } from '../lib/lifecycle';
import { SEED_MAX_LENGTH } from '../lib/seed';

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
  agent: AgentView;
  x: number;
  y: number;
}

function Tooltip({ info }: { info: TooltipInfo | null }) {
  const { finalRound } = useRounds();
  if (!info) return null;
  const { agent, x, y } = info;
  return (
    <div className="tooltip" style={{ left: x + 14, top: y + 14 }}>
      <div className="t-head">{agent.id} <span style={{color:'var(--text-3)', fontSize:10}}>· {agent.bracketDisplay}</span></div>
      <div className="t-row"><span>Signal</span><strong className={signalClass(agent.signal)} style={{padding:'1px 5px'}}>{signalLabel(agent.signal)}</strong></div>
      <div className="t-row"><span>Confidence</span><strong>{(agent.confidence*100).toFixed(0)}%</strong></div>
      <div className="t-row"><span>Flipped R1→R{finalRound}</span><strong>{agent.flipped ? 'Yes' : 'No'}</strong></div>
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

export function AppShell({ initialSeed = '' }: { initialSeed?: string }) {
  // Live data via 6-context tree (W1 Plan 01 wiring).
  const { agents } = useAgents();
  const { rationales } = useRationales();
  const { connected, lastFrame } = useConnection();
  const tel = useTelemetry();
  const meta = useFrameMeta();
  const lifecycle = lifecycleOf(meta);
  const { edges } = useEdgesCtx();
  // Viz still takes [citing, cited] tuples; every other panel reads `edges`.
  const edgePairs = useMemo<Array<[string, string]>>(
    () => edges.map((e) => [e.source_id, e.target_id]),
    [edges],
  );
  const phase = tel.phase;
  const shockWindowOpen = lastFrame?.shockWindowOpen ?? false;
  const tps = tel.telemetry.tps;
  const tpsHistory = useSampleHistory(tps, tel.ts);
  const memMb = tel.telemetry.memMb;
  const slotsUsed = tel.telemetry.slotsUsed;
  const slotsMax = tel.telemetry.slotsMax;
  const elapsedSeconds = tel.telemetry.elapsedSeconds;
  // Governor-driven paused/crisis warning (replaces the old memMb>=90 full
  // takeover): the backend governor pauses + resumes on its own, so the UI
  // only warns — it never restarts the simulation.
  const governorState = tel.telemetry.governorState;
  const governorPaused = governorState === 'paused' || governorState === 'crisis';
  const [govBannerDismissed, setGovBannerDismissed] = useState(false);
  useEffect(() => {
    if (!governorPaused) setGovBannerDismissed(false); // re-arm after recovery
  }, [governorPaused]);

  // Local UI state — chrome only (no live data here).
  const [seed, setSeed] = useState<string>(initialSeed);
  const [actionError, setActionError] = useState<string | null>(null);
  const [layout, setLayout] = useState<VizLayout>('force');
  const [hintsDismissed, setHintsDismissed] = useState(false);
  const [modal, setModal] = useState<ActiveModal>({ kind: 'none' });
  const closeModal = useCallback(() => setModal({ kind: 'none' }), []);
  const [overflowOpen, setOverflowOpen] = useState(false);
  const [tooltip, setTooltip] = useState<TooltipInfo | null>(null);

  // Bracket bars come from the agents on screen, so they always describe the
  // current round (wire bracket_summaries only arrive after a round ends);
  // pending agents leave the rest of the bar blank.
  const summaries = useMemo(
    () =>
      bracketTallies(agents).map((b) => ({
        bracket: b.bracket,
        color: bracketSpec(b.bracket)?.color ?? 'var(--accent)',
        display_name: b.display,
        total: b.total,
        buy_count: b.tally.buy,
        sell_count: b.tally.sell,
        hold_count: b.tally.hold,
      })),
    [agents],
  );
  // Feed rows carry the per-entry wire signal, not the agent's current one, so
  // a flip never retags old entries. Citations are stubbed [] in the adapter
  // (docs/DECISIONS.md#kr-41-1-10).
  const agentsById = useMemo(() => indexAgents(agents), [agents]);
  const feedRows = useMemo(() => buildFeed(rationales, agentsById), [rationales, agentsById]);

  // Top Influencers: agents cited by the most distinct peers in the round on
  // screen (in-degree). Nothing to rank until round 2's edges exist.
  const hasEdges = edges.length > 0;
  const topInfluencers = useMemo(() => {
    const byId = new Map(agents.map((a) => [a.id, a]));
    const ranked = rankInfluencers(agents, edges).slice(0, 5);
    const max = Math.max(1, ...ranked.map((r) => r.citedBy));
    return ranked.map((r) => ({
      id: r.agentId,
      bracket: byId.get(r.agentId)?.bracketDisplay ?? '',
      citedBy: r.citedBy,
      barPct: Math.round((r.citedBy / max) * 100),
    }));
  }, [agents, edges]);

  // Round on screen from the frame (useRound), never parsed from the phase
  // string, so replay and 2-round runs label correctly (lib/phase.ts).
  const { numRounds } = useRounds();
  const currentRound = useRound();
  const round = currentRound ?? 1;
  const phaseLabel = phaseLabelFor(phase, currentRound, numRounds);
  const phaseState: 'live' | 'complete' = phase === 'complete' ? 'complete' : 'live';

  const onAgentHover = (agent: AgentView | null, e?: MouseEvent<SVGElement>) => {
    if (!agent || !e) { setTooltip(null); return; }
    const wrap = e.currentTarget.closest('.canvas-wrap');
    if (!wrap) return;
    const rect = wrap.getBoundingClientRect();
    setTooltip({ agent, x: e.clientX - rect.left, y: e.clientY - rect.top });
  };
  const openInterview = (agentId: string) => setModal({ kind: 'interview', agentId });
  const onAgentClick = (agent: { id: string }) => openInterview(agent.id);

  // Run gate: cost confirmation for cloud/mixed runs, then simStart. It keeps
  // the failure message and a pending flag for the Run control. After an
  // accepted start, Run stays on "Starting…" until the run reaches the frame.
  const runStart = useAwaitRunFrame(lifecycle);
  const runGate = useRunGate({
    onSettled: (ok) => {
      if (ok) runStart.arm();
    },
  });
  const runConfirmModal = runGate.modal;
  // A run that reached SEEDING supersedes an earlier Run error, such as the
  // 409 a second tab got.
  const { clearError: clearRunError } = runGate;
  useEffect(() => {
    if (lifecycle === 'seeding') clearRunError();
  }, [lifecycle, clearRunError]);
  const onRun = () => runGate.requestRun(seed.trim());
  const onStop = async () => {
    setActionError(null);
    try {
      await simStop();
    } catch (err) {
      setActionError(formatApiError(err));
    }
  };

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
            <input
              value={seed}
              onChange={e => setSeed(e.target.value)}
              maxLength={SEED_MAX_LENGTH}
              placeholder="Seed rumor…"
              aria-label="Seed rumor"
            />
          </div>
        </div>

        <RunControls
          seed={seed}
          pending={runGate.pending || runStart.awaiting}
          onRun={onRun}
          onStop={() => void onStop()}
        />

        <ModelStatus />

        <div className="topbar-divider" />

        <button
          className="btn ghost-btn"
          onClick={() => setModal((m) => (m.kind === 'shock' ? { kind: 'none' } : { kind: 'shock' }))}
          disabled={!shockWindowOpen}
          title={shockWindowOpen ? 'Inject shock event' : 'Shock window closed: a shock can only reach a later round'}
        >
          <Icon name="bolt" />
        </button>
        <button className="btn ghost-btn" onClick={() => setModal({ kind: 'cycles' })} title="Watch / replay">
          <Icon name="replay" />
        </button>
        <button className="btn ghost-btn" onClick={() => setModal({ kind: 'report', cycleId: null })} title="Simulation report">
          <Icon name="doc" />
        </button>
        <button className="btn ghost-btn" onClick={() => setModal({ kind: 'settings' })} title="Settings">
          <Icon name="settings" />
        </button>

        <div style={{position:'relative'}}>
          <button className="btn ghost-btn" title="More tools"
            style={{color: overflowOpen ? 'var(--accent)' : undefined}}
            onClick={() => setOverflowOpen((o) => !o)}>
            <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
              <circle cx="3" cy="7.5" r="1.3" fill="currentColor"/>
              <circle cx="7.5" cy="7.5" r="1.3" fill="currentColor"/>
              <circle cx="12" cy="7.5" r="1.3" fill="currentColor"/>
            </svg>
          </button>
          {overflowOpen && (
            <div style={{
              position:'absolute', right:0, top:'calc(100% + 6px)',
              background:'var(--bg-2)', border:'1px solid var(--border-2)',
              borderRadius:5, minWidth:210, zIndex:200,
              boxShadow:'0 12px 32px rgba(0,0,0,0.5)',
              overflow:'hidden',
            }}
              onMouseLeave={() => setOverflowOpen(false)}>
              {([
                { label:'What-if Compare',       icon:'graph',    open: { kind: 'comingSoon', feature: 'whatif' } },
                { label:'Multi-seed Synthesis',  icon:'bolt',     open: { kind: 'comingSoon', feature: 'multiseed' } },
                { label:'Data Sources',          icon:'search',   open: { kind: 'dataSources' } },
                { label:'Portfolio Stress Test', icon:'doc',      open: { kind: 'comingSoon', feature: 'stress' } },
                { label:'Advisory (v6.0)',       icon:'brief',    open: { kind: 'advisory' } },
                { label:'Customize Brackets',    icon:'settings', open: { kind: 'comingSoon', feature: 'brackets' } },
                { label:'Cycle History',         icon:'replay',   open: { kind: 'cycles' } },
              ] as const).map(item => (
                <button key={item.label} onClick={() => { setModal(item.open); setOverflowOpen(false); }}
                  style={{
                    display:'flex', alignItems:'center', gap:10,
                    width:'100%', padding:'9px 14px',
                    background:'transparent', border:'none', borderBottom:'1px solid var(--border)',
                    color:'var(--text-2)', cursor:'pointer',
                    fontFamily: 'var(--font-mono)', fontSize:11, letterSpacing:'0.04em',
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

      <InlineError error={runGate.error} onDismiss={runGate.clearError} />
      <InlineError error={actionError} onDismiss={() => setActionError(null)} />
      <RunErrorBanner />

      {/* Signal Wire ticker — live data_source_audit slice (docs/DECISIONS.md#kr-41-1-02) */}
      <SignalWire onInspect={() => setModal({ kind: 'dataSources' })} />

      {/* Governor paused/crisis warning — dismissible banner, NOT a takeover.
          The backend governor throttles + resumes on its own; no resume button. */}
      {governorPaused && !govBannerDismissed && (
        <div
          style={{
            display: 'flex', alignItems: 'center', gap: 12, padding: '7px 14px',
            background: 'color-mix(in srgb, var(--sell) 10%, var(--bg-2))',
            borderBottom: '1px solid color-mix(in srgb, var(--sell) 35%, transparent)',
          }}
        >
          <span className="label" style={{ color: 'var(--sell)' }}>
            GOVERNOR {governorState?.toUpperCase()} · MEMORY {Math.round(memMb)}%
          </span>
          <span style={{ color: 'var(--text-2)', fontSize: 11 }}>
            Inference throttled under memory pressure — the governor resumes
            automatically once pressure clears. No action needed.
          </span>
          <div style={{ flex: 1 }} />
          <button
            className="btn ghost"
            style={{ height: 22, padding: '0 8px' }}
            onClick={() => setGovBannerDismissed(true)}
          >
            Dismiss
          </button>
        </div>
      )}

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
              <BracketList summaries={summaries} onClick={(s) => setModal({ kind: 'bracket', bracket: s })} />
            </div>
          </div>

          <div className="panel">
            <div className="panel-head">
              <span className="panel-title">Top Influencers</span>
              <span className="label">CITED BY</span>
            </div>
            <div className="panel-body" style={{fontFamily: 'var(--font-mono)', fontSize:11}}>
              {topInfluencers.length === 0 ? (
                <div style={{ padding: 12, color: 'var(--text-3)', fontSize: 10 }}>
                  {hasEdges
                    ? 'no citations in this round'
                    : "influence appears once round 2's citations are written"}
                </div>
              ) : topInfluencers.map(r => (
                <div key={r.id} className="influencer-row">
                  <span className="infl-id" onClick={() => openInterview(r.id)}>{r.id}</span>
                  <span className="infl-bracket">{r.bracket}</span>
                  <div className="infl-bar"><span style={{width: `${r.barPct}%`}} /></div>
                  <span className="infl-num">{r.citedBy}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Center */}
        <div className="col col-center">
          <div className="canvas-topstrip">
            <span className="topstrip-meta">{agents.filter(a => a.flipped).length} flips since R1 · {hasEdges ? `${edges.length} active edges` : `${agents.length} agents`}</span>
            <div className="layout-tabs">
              <span className="label" style={{marginRight:6}}>LAYOUT</span>
              {([
                { k: 'force', icon: 'graph', label: 'Force' },
                { k: 'radial', icon: 'radial', label: 'Radial' },
                { k: 'grid', icon: 'grid', label: 'Grid' },
              ] as const).map(l => (
                <button key={l.k} className="layout-btn" data-active={layout === l.k}
                  onClick={() => setLayout(l.k)} title={l.label}><Icon name={l.icon} /></button>
              ))}
            </div>
          </div>

          <div className="canvas-wrap">
            <Viz
              agents={agents}
              edges={edgePairs}
              layout={layout}
              direction="a"
              highlightId={tooltip?.agent.id}
              onAgentHover={onAgentHover}
              onAgentClick={onAgentClick}
            />
            <ConsensusRing agents={agents} />
            <Legend />
            <Tooltip info={tooltip} />

            {!hintsDismissed && (
              <div className="first-hint">
                <span className="label" style={{color:'var(--accent)'}}>TIP</span>
                <span>Each node is one of 100 agents · color = signal · hover for detail · click to interview</span>
                <button className="btn ghost" style={{height:22, padding:'0 8px'}} onClick={() => setHintsDismissed(true)}>Got it</button>
              </div>
            )}
            {lifecycle === 'idle' && (
              <IdleState
                seed={seed}
                numRounds={numRounds}
                onShowHistory={() => setModal({ kind: 'cycles' })}
              />
            )}
            {lifecycle === 'seeding' && <SeedingState seed={seed} elapsedSeconds={elapsedSeconds} />}
          </div>

          <KpiStrip
            agents={agents}
            tps={tps}
            tpsHistory={tpsHistory}
            mem={Math.round(memMb)}
            slots={slotsUsed}
            slotsMax={slotsMax}
            elapsed={Math.round(elapsedSeconds)}
            round={round}
            numRounds={numRounds}
          />
        </div>

        {/* Right */}
        <div className="col col-right">
          <div className="panel">
            <div className="panel-head">
              <span className="panel-title">Rationale Feed</span>
              {connected ? (
                <span className="label live-indicator"><span className="live-dot" /> LIVE · R{round}</span>
              ) : (
                <span className="label" style={{ color: 'var(--sell)' }}>RECONNECTING…</span>
              )}
            </div>
            <div className="panel-body">
              <RationaleFeed
                rows={feedRows}
                onAgentClick={openInterview}
                onCiteClick={openInterview}
              />
            </div>
          </div>
        </div>
      </div>

      <ModalHost modal={modal} onOpen={setModal} onClose={closeModal} />
      {/* Replay is driven by the frame (mode), so the bar survives a reload. */}
      {lifecycle === 'replay' && <ReplayBar />}

      {/* Pre-run cost confirmation modal (cloud/mixed mode only). */}
      {runConfirmModal}
    </div>
  );
}
