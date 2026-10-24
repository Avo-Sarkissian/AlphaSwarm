// Dashboard grid: brackets and influencers, the agent canvas with KPIs, the rationale feed.
import { useCallback, useLayoutEffect, useRef, useState } from 'react';
import { Icon } from '../../components/Icon';
import { useAgents } from '../../context/AgentsContext';
import { useConnection } from '../../context/ConnectionContext';
import { useEdgesCtx } from '../../context/EdgesContext';
import { useFrameMeta } from '../../context/FrameMetaContext';
import { useTelemetry } from '../../context/TelemetryContext';
import { useRound, useRounds } from '../../hooks/useRounds';
import { useSampleHistory } from '../../hooks/useSampleHistory';
import { lifecycleOf } from '../../lib/lifecycle';
import { DEFAULT_ALL_EDGES, InfluenceGraph } from '../../viz/InfluenceGraph';
import type { GraphLayout, Reserve } from '../../viz/layout';
import { BracketList, ConsensusRing, KpiStrip, RationaleFeed, type BracketRow } from './panels';
import { IdleState, SeedingState } from './StateOverlays';
import { useBracketRows, useFeedRows, useTopInfluencers } from './useDashboardData';

/** The consensus ring covers the canvas's top-right corner (120 px at an 18 px offset). */
const GRAPH_RESERVE: readonly Reserve[] = [{ corner: 'top-right', w: 150, h: 150 }];

/**
 * A stable function that always calls the latest `fn`, so a memoized child does
 * not re-render when the parent passes a new inline callback.
 */
function useLatestCallback<A extends unknown[], R>(fn: (...args: A) => R): (...args: A) => R {
  const ref = useRef(fn);
  useLayoutEffect(() => {
    ref.current = fn;
  });
  return useCallback((...args: A) => ref.current(...args), []);
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
  const meta = useFrameMeta();
  const lifecycle = lifecycleOf(meta);
  const { roundNum } = meta;
  const { edges, target, status } = useEdgesCtx();
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

  const [layout, setLayout] = useState<GraphLayout>('clusters');
  const [allEdges, setAllEdges] = useState(DEFAULT_ALL_EDGES);
  const interviewFromGraph = useLatestCallback(onInterview);
  const [hintsDismissed, setHintsDismissed] = useState(false);
  const interview = useLatestCallback((agentId: string) => onInterview(agentId));
  const openBracket = useLatestCallback((row: BracketRow) => onOpenBracket(row));

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
            <BracketList summaries={summaries} onClick={openBracket} />
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
                <button type="button" className="infl-id as-text" onClick={() => onInterview(r.id)}>{r.id}</button>
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
              { k: 'clusters', icon: 'graph', label: 'Clusters' },
              { k: 'radial', icon: 'radial', label: 'Radial' },
              { k: 'grid', icon: 'grid', label: 'Grid' },
            ] as const).map(l => (
              <button key={l.k} type="button" className="layout-btn" data-active={layout === l.k}
                aria-pressed={layout === l.k} aria-label={l.label} title={l.label}
                onClick={() => setLayout(l.k)}><Icon name={l.icon} /></button>
            ))}
            <button type="button" className="layout-btn edges-toggle" aria-pressed={allEdges}
              disabled={layout === 'grid'} title="Show every citation instead of bracket ribbons"
              onClick={() => setAllEdges((v) => !v)}>All edges</button>
          </div>
        </div>

        <div className="canvas-wrap">
          <InfluenceGraph
            agents={agents}
            edges={edges}
            edgesRound={target?.round ?? null}
            edgesLoading={status === 'loading'}
            roundNum={roundNum}
            layout={layout}
            allEdges={allEdges}
            reserve={GRAPH_RESERVE}
            onInterview={interviewFromGraph}
          />
          <ConsensusRing agents={agents} />

          {!hintsDismissed && (
            <div className="first-hint">
              <span className="label u-accent">TIP</span>
              <span>Each node is one of 100 agents · colour = signal · size = peers citing it · hover for citations · click to pin, then interview</span>
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
              <span className="label u-sell">RECONNECTING…</span>
            )}
          </div>
          <div className="panel-body">
            <RationaleFeed
              rows={feedRows}
              onAgentClick={interview}
              onCiteClick={interview}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
