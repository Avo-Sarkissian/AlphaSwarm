// Dashboard grid: brackets and influencers, the agent canvas with KPIs, the rationale feed.
import { useMemo, useState } from 'react';
import type { MouseEvent } from 'react';
import { Icon } from '../../components/Icon';
import { useAgents } from '../../context/AgentsContext';
import { useConnection } from '../../context/ConnectionContext';
import { useEdgesCtx } from '../../context/EdgesContext';
import { useFrameMeta } from '../../context/FrameMetaContext';
import { useTelemetry } from '../../context/TelemetryContext';
import { useRound, useRounds } from '../../hooks/useRounds';
import { useSampleHistory } from '../../hooks/useSampleHistory';
import { lifecycleOf } from '../../lib/lifecycle';
import { signalClass, signalLabel } from '../../lib/signals';
import type { AgentView } from '../../types';
import { BracketList, ConsensusRing, KpiStrip, RationaleFeed, type BracketRow } from './panels';
import { IdleState, SeedingState } from './StateOverlays';
import { useBracketRows, useFeedRows, useTopInfluencers } from './useDashboardData';
import { Viz } from './Viz';
import type { VizLayout } from './vizLayout';

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

export interface DashboardProps {
  seed: string;
  onInterview: (agentId: string) => void;
  onOpenBracket: (row: BracketRow) => void;
  onShowCycles: () => void;
}

export function Dashboard({ seed, onInterview, onOpenBracket, onShowCycles }: DashboardProps) {
  const { agents } = useAgents();
  const { connected } = useConnection();
  const tel = useTelemetry();
  const lifecycle = lifecycleOf(useFrameMeta());
  const { edges } = useEdgesCtx();
  // Viz still takes [citing, cited] tuples; every other panel reads `edges`.
  const edgePairs = useMemo<Array<[string, string]>>(
    () => edges.map((e) => [e.source_id, e.target_id]),
    [edges],
  );
  const tps = tel.telemetry.tps;
  const tpsHistory = useSampleHistory(tps, tel.ts);
  const memMb = tel.telemetry.memMb;
  const slotsUsed = tel.telemetry.slotsUsed;
  const slotsMax = tel.telemetry.slotsMax;
  const elapsedSeconds = tel.telemetry.elapsedSeconds;
  // Round on screen from the frame (useRound), never parsed from the phase string.
  const { numRounds } = useRounds();
  const round = useRound() ?? 1;

  const summaries = useBracketRows();
  const feedRows = useFeedRows();
  // Top Influencers: agents cited by the most distinct peers in the round on
  // screen (in-degree). Nothing to rank until round 2's edges exist.
  const topInfluencers = useTopInfluencers();
  const hasEdges = edges.length > 0;

  const [layout, setLayout] = useState<VizLayout>('force');
  const [hintsDismissed, setHintsDismissed] = useState(false);
  const [tooltip, setTooltip] = useState<TooltipInfo | null>(null);
  const onAgentHover = (agent: AgentView | null, e?: MouseEvent<SVGElement>) => {
    if (!agent || !e) { setTooltip(null); return; }
    const wrap = e.currentTarget.closest('.canvas-wrap');
    if (!wrap) return;
    const rect = wrap.getBoundingClientRect();
    setTooltip({ agent, x: e.clientX - rect.left, y: e.clientY - rect.top });
  };
  const onAgentClick = (agent: { id: string }) => onInterview(agent.id);

  return (
    <div className="main">
      {/* Left */}
      <div className="col col-left">
        <div className="panel" style={{flex: '0 0 auto'}}>
          <div className="panel-head">
            <span className="panel-title">Brackets</span>
            <span className="label">{agents.length} AGENTS · R{round}</span>
          </div>
          <div className="panel-body">
            <BracketList summaries={summaries} onClick={onOpenBracket} />
          </div>
        </div>

        <div className="panel">
          <div className="panel-head">
            <span className="panel-title">Top Influencers</span>
            <span className="label">CITED BY</span>
          </div>
          <div className="panel-body" style={{fontFamily: 'var(--font-mono)', fontSize:11}}>
            {topInfluencers.length === 0 ? (
              <div className="panel-hint">
                {hasEdges
                  ? 'no citations in this round'
                  : "influence appears once round 2's citations are written"}
              </div>
            ) : topInfluencers.map(r => (
              <div key={r.id} className="influencer-row">
                <span className="infl-id" onClick={() => onInterview(r.id)}>{r.id}</span>
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
              <button className="btn ghost compact" onClick={() => setHintsDismissed(true)}>Got it</button>
            </div>
          )}
          {lifecycle === 'idle' && (
            <IdleState
              seed={seed}
              numRounds={numRounds}
              onShowHistory={onShowCycles}
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
              onAgentClick={onInterview}
              onCiteClick={onInterview}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
