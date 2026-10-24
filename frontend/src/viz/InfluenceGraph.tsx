// The hero graph: 100 agents on a deterministic layout, bracket ribbons as the
// overview, the hovered or pinned agent's citations on demand, and every agent
// edge behind the "All edges" toggle (docs/DECISIONS.md#adr-hero-graph).
// Hover and pin state live here, so pointer movement never re-renders panels.
import { memo, useEffect, useId, useMemo, useRef, useState } from 'react';
import type { MouseEvent as ReactMouseEvent, ReactNode, RefObject } from 'react';
import type { Edge } from '../api/edges';
import { BRACKETS } from '../data';
import { rankInfluencers } from '../lib/influence';
import { signalColor } from '../lib/signals';
import type { AgentSignal, AgentView } from '../types';
import { AgentTooltip } from './AgentTooltip';
import { graphCaption } from './caption';
import { aggregateByBracket, curvedPath, egoNetwork, type Point } from './edges';
import {
  citerColor,
  DIM_OPACITY,
  EDGE_IN,
  EDGE_OPACITY,
  EDGE_OUT,
  edgeWidthScale,
  nodeRadiusScale,
  ribbonWidthScale,
} from './encodings';
import {
  computeScene,
  mergeRoster,
  rosterFromBrackets,
  type GraphLayout,
  type GroupKey,
  type Reserve,
} from './layout';
import { legendItems, type EdgeMode } from './legendItems';
import { Legend } from './Legend';
import { EdgePath, FlipRing, NodeGroup, edgeKey } from './story';

export interface InfluenceGraphProps {
  agents: readonly AgentView[];
  /** Citations of the round on screen; source_id cites target_id (src/api/edges.ts). */
  edges: readonly Edge[];
  /** The round `edges` belong to; null while no round has edges. */
  edgesRound: number | null;
  /** True while the edges for `edgesRound` are loading. */
  edgesLoading?: boolean;
  /** Round on screen (useFrameMeta().roundNum). */
  roundNum: number | null;
  layout: GraphLayout;
  /** "All edges": every agent edge instead of the bracket ribbons. */
  allEdges: boolean;
  /** Canvas corners covered by overlays (for example the consensus ring). */
  reserve?: readonly Reserve[];
  onInterview?: (agentId: string) => void;
}

/**
 * Initial state of the "All edges" toggle: false = bracket ribbons first (owner
 * decision recorded in docs/DECISIONS.md#adr-hero-graph).
 */
export const DEFAULT_ALL_EDGES = false;

const BASE_ROSTER = rosterFromBrackets();
const BRACKET_COLOURS: ReadonlyMap<GroupKey, string> = new Map(BRACKETS.map((b) => [b.key, b.color]));
const NO_RESERVE: readonly Reserve[] = [];
const DEFAULT_SIZE = { w: 800, h: 600 };
const TOP_LABELS = 5;
const GRID_CELL = 1.7;

function useCanvasSize(ref: RefObject<HTMLDivElement | null>) {
  const [size, setSize] = useState(DEFAULT_SIZE);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        // A collapsed or hidden canvas reports 0 x 0: keep the last real size.
        if (width >= 1 && height >= 1) setSize({ w: width, h: height });
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);
  return size;
}

function InfluenceGraphImpl({
  agents,
  edges,
  edgesRound,
  edgesLoading = false,
  roundNum,
  layout,
  allEdges,
  reserve = NO_RESERVE,
  onInterview,
}: InfluenceGraphProps) {
  // Marker ids must be valid in url(#...): keep only id-safe characters of useId().
  const uid = `ig${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`;
  const canvasRef = useRef<HTMLDivElement>(null);
  const size = useCanvasSize(canvasRef);
  const [hoverId, setHoverId] = useState<string | null>(null);
  const [pinnedId, setPinnedId] = useState<string | null>(null);

  // Positions depend on roster membership only, never on frame order.
  const idsKey = useMemo(() => agents.map((a) => a.id).sort().join('|'), [agents]);
  const roster = useMemo(() => mergeRoster(BASE_ROSTER, idsKey ? idsKey.split('|') : []), [idsKey]);
  const scene = useMemo(() => computeScene(roster, size, layout, { reserve }), [roster, size, layout, reserve]);
  const groupOf = useMemo(() => {
    const map = new Map(roster.map((e) => [e.id, e.bracket]));
    return (id: string): GroupKey => map.get(id) ?? 'unknown';
  }, [roster]);

  const byId = useMemo(() => new Map(agents.map((a) => [a.id, a])), [agents]);
  const ranked = useMemo(() => rankInfluencers(agents, edges), [agents, edges]);
  const citedBy = useMemo(() => new Map(ranked.map((r) => [r.agentId, r.citedBy])), [ranked]);
  const slot = scene.nodes.values().next().value?.r ?? 0;
  const radiusOf = useMemo(() => nodeRadiusScale(citedBy, slot), [citedBy, slot]);
  const widths = useMemo(() => edgeWidthScale(edges), [edges]);

  // A pinned agent that is no longer in the frame counts as unpinned.
  const pinned = pinnedId !== null && byId.has(pinnedId) ? pinnedId : null;
  const focusId = pinned ?? (hoverId !== null && byId.has(hoverId) ? hoverId : null);
  const focusAgent = focusId ? byId.get(focusId) : undefined;
  const ego = useMemo(() => (focusId ? egoNetwork(focusId, edges) : null), [focusId, edges]);
  // Ego mode only when the focused agent has citations to show; otherwise the overview stays.
  const edgeMode: EdgeMode =
    ego && ego.neighbors.size > 0 ? 'ego' : layout === 'grid' ? 'none' : allEdges ? 'agents' : layout === 'clusters' ? 'ribbons' : 'none';
  const matrix = useMemo(
    () => (edgeMode === 'ribbons' ? aggregateByBracket(edges, groupOf) : null),
    [edgeMode, edges, groupOf],
  );

  // Esc unpins, unless a dialog already handled the key.
  useEffect(() => {
    if (!pinned) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !e.defaultPrevented) setPinnedId(null);
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [pinned]);

  const markers = new Map<string, string>();
  const markerFor = (colour: string): string => {
    let id = markers.get(colour);
    if (!id) {
      id = `${uid}-m${markers.size}`;
      markers.set(colour, id);
    }
    return `url(#${id})`;
  };

  const pos = (id: string): Point | undefined => scene.nodes.get(id);
  const agentEdge = (e: Edge, colour: string, cls: string) => {
    const s = pos(e.target_id);
    const t = pos(e.source_id);
    const citer = byId.get(e.source_id);
    if (!s || !t || e.source_id === e.target_id || !citer) return null;
    return (
      <EdgePath
        key={edgeKey(e)}
        edge={e}
        className={cls}
        d={curvedPath(s, t, { pullback: radiusOf(e.source_id) + 1 })}
        stroke={colour}
        strokeWidth={widths.width(e.weight)}
        opacity={EDGE_OPACITY}
        markerEnd={markerFor(colour)}
      />
    );
  };

  let edgeLayer: ReactNode = null;
  if (edgeMode === 'ego' && ego && layout !== 'grid') {
    edgeLayer = [
      ...ego.incoming.map((e) => agentEdge(e, EDGE_IN, 'ig-edge ig-edge-in')),
      ...ego.outgoing.map((e) => agentEdge(e, EDGE_OUT, 'ig-edge ig-edge-out')),
    ];
  } else if (edgeMode === 'agents') {
    edgeLayer = edges.map((e) => agentEdge(e, citerColor(byId.get(e.source_id)?.signal ?? null), 'ig-edge'));
  } else if (edgeMode === 'ribbons' && matrix) {
    const guides = new Map(scene.groups.map((g) => [g.bracket, g]));
    const width = ribbonWidthScale(matrix.cells[0]?.count ?? 1);
    edgeLayer = matrix.cells.map((cell) => {
      const from = guides.get(cell.from);
      const to = guides.get(cell.to);
      if (!from || !to) return null;
      const colour = BRACKET_COLOURS.get(cell.from) ?? 'var(--edge)';
      return (
        <path
          key={`${cell.from}->${cell.to}`}
          className="ig-ribbon"
          d={curvedPath({ x: from.cx, y: from.cy }, { x: to.cx, y: to.cy }, { pullback: to.radius + 2 })}
          stroke={colour}
          strokeWidth={width(cell.count)}
          opacity={EDGE_OPACITY}
          markerEnd={markerFor(colour)}
        >
          <title>{`${cell.from} → ${cell.to}: ${cell.count} citations`}</title>
        </path>
      );
    });
  }

  const signals = new Set<AgentSignal | 'pending'>(agents.map((a) => a.signal ?? 'pending'));
  const items = legendItems({
    layout,
    edgeMode,
    signals,
    sized: edges.length > 0,
    weighted: edgeMode === 'agents' && widths.varies,
    flips: agents.some((a) => a.flipped),
    withinCount: matrix ? [...matrix.within.values()].reduce((a, b) => a + b, 0) : 0,
    hint: edges.length > 0 && edgeMode === 'none',
  });
  const caption = graphCaption({
    agentCount: agents.length,
    edgeCount: edges.length,
    edgesRound,
    roundNum,
    loading: edgesLoading,
  });
  const topIds = layout === 'grid' ? [] : ranked.slice(0, TOP_LABELS).map((r) => r.agentId);
  const focusSlot = focusId ? scene.nodes.get(focusId) : undefined;

  const onNodeClick = (id: string) => (e: ReactMouseEvent) => {
    e.stopPropagation();
    setPinnedId((current) => (current === id ? null : id));
  };

  return (
    <div className="ig">
      <div className="ig-canvas" ref={canvasRef}>
        <svg
          className="ig-svg"
          viewBox={`0 0 ${scene.size.w} ${scene.size.h}`}
          role="img"
          aria-label={`Influence graph: ${agents.length} agents, ${edges.length} citations${edgesRound ? ` in round ${edgesRound}` : ''}`}
        >
          <defs>
            {[...markers].map(([colour, id]) => (
              <marker key={id} id={id} viewBox="0 0 8 8" refX={8} refY={4} markerWidth={7} markerHeight={7} markerUnits="userSpaceOnUse" orient="auto">
                <path d="M0,0 L8,4 L0,8 Z" fill={colour} />
              </marker>
            ))}
          </defs>
          <rect className="ig-bg" width={scene.size.w} height={scene.size.h} onClick={() => setPinnedId(null)} />
          {layout === 'radial' &&
            scene.groups.map((g) => <circle key={`ring-${g.bracket}`} className="ig-ring" cx={g.cx} cy={g.cy} r={g.radius} />)}
          <g className="ig-edges">{edgeLayer}</g>
          <g className="ig-nodes">
            {agents.map((a) => {
              const p = scene.nodes.get(a.id);
              if (!p) return null;
              const neighbour = ego?.neighbors.has(a.id) ?? false;
              const dim = edgeMode === 'ego' && a.id !== focusId && !neighbour;
              const ring = ego && layout === 'grid' && neighbour
                ? (ego.incoming.some((e) => e.target_id === a.id) ? EDGE_IN : EDGE_OUT)
                : undefined;
              const r = layout === 'grid' ? p.r : radiusOf(a.id);
              return (
                <NodeGroup
                  key={a.id}
                  id={a.id}
                  x={p.x}
                  y={p.y}
                  className={a.id === focusId ? 'focused' : undefined}
                  opacity={dim ? DIM_OPACITY : 1}
                  onMouseEnter={() => setHoverId(a.id)}
                  onMouseLeave={() => setHoverId((h) => (h === a.id ? null : h))}
                  onClick={onNodeClick(a.id)}
                >
                  {layout === 'grid' ? (
                    <rect
                      className={a.thinking ? 'ig-node-fill thinking' : 'ig-node-fill'}
                      x={-(r * GRID_CELL) / 2}
                      y={-(r * GRID_CELL) / 2}
                      width={r * GRID_CELL}
                      height={r * GRID_CELL}
                      rx={2}
                      fill={signalColor(a.signal)}
                      stroke={ring}
                      strokeWidth={ring ? 2 : undefined}
                    />
                  ) : (
                    <circle className={a.thinking ? 'ig-node-fill thinking' : 'ig-node-fill'} r={r} fill={signalColor(a.signal)} />
                  )}
                  {a.signal === 'parse_error' && (
                    <path className="ig-fail-mark" d={`M${-r * 0.5},${-r * 0.5} L${r * 0.5},${r * 0.5} M${-r * 0.5},${r * 0.5} L${r * 0.5},${-r * 0.5}`} />
                  )}
                  {a.flipped && a.flippedFrom ? <FlipRing r={r} from={a.flippedFrom} /> : null}
                </NodeGroup>
              );
            })}
          </g>
          <g className="ig-labels">
            {scene.groups.map((g) => (
              <text key={`label-${g.bracket}`} className="ig-label" x={g.labelX} y={g.labelY} textAnchor={g.anchor} dominantBaseline="central">
                {g.label}
              </text>
            ))}
            {topIds.map((id) => {
              const p = scene.nodes.get(id);
              return p ? (
                <text key={`top-${id}`} className="ig-top-label" x={p.x} y={p.y - radiusOf(id) - 4} textAnchor="middle">
                  {id}
                </text>
              ) : null;
            })}
          </g>
        </svg>
        {focusAgent && focusSlot && ego && (
          <AgentTooltip
            agent={focusAgent}
            x={focusSlot.x + (layout === 'grid' ? focusSlot.r : radiusOf(focusAgent.id))}
            y={focusSlot.y}
            canvasWidth={scene.size.w}
            ego={ego}
            edgesRound={edgesRound}
            pinned={pinned === focusAgent.id}
            onInterview={onInterview}
          />
        )}
      </div>
      <div className="ig-foot">
        {caption && (
          <p className="ig-caption" role="status">
            {caption}
          </p>
        )}
        <Legend items={items} layout={layout} />
      </div>
    </div>
  );
}

export const InfluenceGraph = memo(InfluenceGraphImpl);
