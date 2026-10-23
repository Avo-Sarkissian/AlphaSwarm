// Agent graph plus its hover tooltip. Hover state lives here, so moving the mouse
// re-renders this pane only, never the dashboard panels
// (docs/DECISIONS.md#adr-frontend-quant-terminal).
import { memo, useCallback, useState } from 'react';
import type { MouseEvent } from 'react';
import { useRounds } from '../../hooks/useRounds';
import { signalClass, signalLabel } from '../../lib/signals';
import type { AgentView } from '../../types';
import { Viz } from './Viz';
import type { VizLayout } from './vizLayout';

interface TooltipInfo {
  agent: AgentView;
  x: number;
  y: number;
}

export interface GraphPaneProps {
  agents: readonly AgentView[];
  edges?: ReadonlyArray<readonly [string, string]>;
  layout: VizLayout;
  onAgentClick: (agent: AgentView) => void;
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

export const GraphPane = memo(function GraphPane({ agents, edges, layout, onAgentClick }: GraphPaneProps) {
  const [tooltip, setTooltip] = useState<TooltipInfo | null>(null);
  const onAgentHover = useCallback((agent: AgentView | null, e?: MouseEvent<SVGElement>) => {
    if (!agent || !e) { setTooltip(null); return; }
    const wrap = e.currentTarget.closest('.canvas-wrap');
    if (!wrap) return;
    const rect = wrap.getBoundingClientRect();
    setTooltip({ agent, x: e.clientX - rect.left, y: e.clientY - rect.top });
  }, []);
  return (
    <>
      <Viz
        agents={agents}
        edges={edges}
        layout={layout}
        direction="a"
        highlightId={tooltip?.agent.id}
        onAgentHover={onAgentHover}
        onAgentClick={onAgentClick}
      />
      <Tooltip info={tooltip} />
    </>
  );
});
