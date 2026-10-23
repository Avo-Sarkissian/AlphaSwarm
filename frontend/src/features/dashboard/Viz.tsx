// Agent graph: one SVG node per agent on a deterministic layout
// (docs/DECISIONS.md#kr-41-1-01). Edges are [citing, cited] pairs.
import { memo, useEffect, useMemo, useRef, useState } from 'react';
import type { MouseEvent } from 'react';
import { BRACKETS } from '../../data';
import { signalColor } from '../../lib/signals';
import type { AgentView } from '../../types';
import {
  clusterRadius,
  layoutForce,
  layoutGrid,
  layoutRadial,
  ringRadius,
  type NodePosition,
  type VizLayout,
} from './vizLayout';

// Node radius by registry order, 5..14, until the graph redesign sizes nodes
// by influence (docs/DECISIONS.md#adr-frontend-quant-terminal).
const RADIUS_BY_BRACKET: ReadonlyMap<string, number> = new Map(
  BRACKETS.map((b, i) => [b.key, 5 + i] as const),
);

export interface VizProps {
  agents: readonly AgentView[];
  edges?: ReadonlyArray<readonly [string, string]>;
  layout: VizLayout;
  direction?: 'a' | 'c';
  onAgentHover?: (agent: AgentView | null, event?: MouseEvent<SVGElement>) => void;
  onAgentClick?: (agent: AgentView) => void;
  highlightId?: string;
  showEdges?: boolean;
}

interface VizAgent extends AgentView {
  index: number;
  radius: number;
}

const EMPTY_EDGES: ReadonlyArray<readonly [string, string]> = [];

export const Viz = memo(function Viz({
  agents: rawAgents,
  edges: rawEdges = EMPTY_EDGES,
  layout,
  direction = 'a',
  onAgentHover,
  onAgentClick,
  highlightId,
  showEdges = true,
}: VizProps) {
  const agents = useMemo<VizAgent[]>(
    () => rawAgents.map((a, i) => ({ ...a, index: i, radius: RADIUS_BY_BRACKET.get(a.bracket) ?? 5 })),
    [rawAgents],
  );

  const wrapRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 800, h: 600 });
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) setSize({ w: entry.contentRect.width, h: entry.contentRect.height });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const gridData = useMemo(
    () => (layout === 'grid' ? layoutGrid(agents, size.w, size.h) : null),
    [agents, layout, size.w, size.h],
  );
  const positions = useMemo<ReadonlyMap<string, NodePosition>>(() => {
    if (layout === 'force') return layoutForce(agents, size.w, size.h);
    if (layout === 'radial') return layoutRadial(agents, size.w, size.h);
    return gridData?.positions ?? new Map<string, NodePosition>();
  }, [agents, layout, size.w, size.h, gridData]);

  const edges = useMemo(
    () => (layout === 'grid' ? [] : rawEdges.map(([source, target]) => ({ source, target }))),
    [rawEdges, layout],
  );

  const bracketGroups = useMemo(() => {
    const groups = new Map<string, { display: string; items: VizAgent[] }>();
    for (const a of agents) {
      const group = groups.get(a.bracket);
      if (group) group.items.push(a);
      else groups.set(a.bracket, { display: a.bracketDisplay, items: [a] });
    }
    return [...groups];
  }, [agents]);
  const displayOf = (bracket: string) =>
    bracketGroups.find(([key]) => key === bracket)?.[1].display ?? bracket;

  return (
    <div ref={wrapRef} style={{ width: '100%', height: '100%', position: 'relative' }}>
      <svg className="viz-svg" viewBox={`0 0 ${size.w} ${size.h}`} preserveAspectRatio="none">
        <defs>
          <filter id="glow"><feGaussianBlur stdDeviation="2" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
          <radialGradient id="nodeGlow" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="currentColor" stopOpacity="0.45"/>
            <stop offset="100%" stopColor="currentColor" stopOpacity="0"/>
          </radialGradient>
        </defs>

        {layout === 'radial' && (
          <g style={{ opacity: 0.4 }}>
            {bracketGroups.map(([key], i) => (
              <circle key={key} cx={size.w / 2} cy={size.h / 2} r={ringRadius(i, bracketGroups.length, size.w, size.h)}
                fill="none" stroke="var(--border)" strokeDasharray="2 4" />
            ))}
          </g>
        )}

        {gridData && (
          <g>
            {gridData.bracketOrder.map((bracket, r) => (
              <text key={bracket} x={gridData.pad - 12} y={gridData.pad + gridData.cellH * (r + 0.5)}
                className="bracket-label" textAnchor="end" dominantBaseline="central">
                {displayOf(bracket)}
              </text>
            ))}
          </g>
        )}

        {showEdges && layout !== 'grid' && (
          <g>
            {edges.map((e, i) => {
              const s = positions.get(e.source);
              const t = positions.get(e.target);
              if (!s || !t) return null;
              return (
                <path key={i} className="edge"
                  d={`M ${s.x} ${s.y} Q ${(s.x + t.x) / 2} ${(s.y + t.y) / 2 - 20} ${t.x} ${t.y}`} />
              );
            })}
          </g>
        )}

        {layout === 'force' && (
          <g>
            {bracketGroups.map(([key, group], i) => {
              const angle = (i / bracketGroups.length) * Math.PI * 2 - Math.PI / 2;
              const R = Math.min(size.w, size.h) * 0.36 + clusterRadius(group.items.length) + 14;
              return (
                <text key={key} x={size.w / 2 + Math.cos(angle) * R} y={size.h / 2 + Math.sin(angle) * R}
                  textAnchor="middle" dominantBaseline="central" className="bracket-label">
                  {group.display.toUpperCase()} · {group.items.length}
                </text>
              );
            })}
          </g>
        )}

        <g>
          {agents.map((a) => {
            const p = positions.get(a.id);
            if (!p) return null;
            const color = signalColor(a.signal);
            const isHL = highlightId === a.id;
            if (gridData) {
              const cell = Math.min(gridData.cellW, gridData.cellH) * 0.72;
              return (
                <g key={a.id} transform={`translate(${p.x - cell / 2}, ${p.y - cell / 2})`}>
                  <rect width={cell} height={cell} rx={2}
                    className={`grid-cell${a.thinking ? ' thinking' : ''}`}
                    fill={color} opacity={0.88}
                    onMouseEnter={(e) => onAgentHover?.(a, e)}
                    onMouseLeave={() => onAgentHover?.(null)}
                    onClick={() => onAgentClick?.(a)} />
                  {a.flipped ? <circle cx={cell - 4} cy={4} r={2.5} fill="var(--accent)" /> : null}
                </g>
              );
            }
            const r = a.radius * 0.7;
            return (
              <g key={a.id} transform={`translate(${p.x}, ${p.y})`}>
                {direction === 'c' && <circle r={r * 2.2} fill="url(#nodeGlow)" style={{ color }} />}
                <circle className={`node${a.thinking ? ' thinking' : ''}`} r={r} fill={color}
                  stroke={isHL ? 'var(--accent)' : 'rgba(255,255,255,0.15)'} strokeWidth={isHL ? 2 : 1}
                  filter={direction === 'c' ? 'url(#glow)' : undefined}
                  onMouseEnter={(e) => onAgentHover?.(a, e)}
                  onMouseLeave={() => onAgentHover?.(null)}
                  onClick={() => onAgentClick?.(a)} />
                {a.flipped ? <circle r={r + 3} fill="none" stroke="var(--accent)" strokeDasharray="2 2" /> : null}
              </g>
            );
          })}
        </g>
      </svg>
    </div>
  );
});
