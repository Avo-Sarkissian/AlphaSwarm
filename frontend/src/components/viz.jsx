// Visualization module — force / grid / radial layouts, all SVG-based.
// Lifted from AlphaSwarm-2/src/viz.jsx (W2 Plan 41.6-02 task 1) and converted
// to native ES modules per D-03 (was attached as a global before the conversion).
// Deterministic SVG layout preserved per KR-41.1-01 (no d3-force).
//
// Live-data note (W2 hotfix): the AlphaSwarm-2 design's mock buildAgents()
// attached `index` (array position) and `radius` (per-bracket size) to each
// agent. Live agents from useAgents() (CONTRACT.md §2.1 shape) DON'T carry
// those — they're presentation-derived. Without them, layoutForce's jitter
// math becomes NaN ("M NaN NaN" path errors) and the per-circle r= becomes
// NaN. The Viz component now enriches agents with both fields before passing
// them downstream, restoring the deterministic layout.
import { useEffect, useMemo, useRef, useState } from 'react';
import { BRACKETS, normalizeBracketKey } from '../data';

// Backend BracketKey is PascalCase ('Quants', 'SellSide', 'EventDriven')
// while BRACKETS const values are snake_case ('quants', 'sell_side', 'event_driven').
// Normalize on lookup (shared helper in ../data) so all agents get their proper
// per-bracket radius instead of falling through to the default and rendering
// uniform tiny dots.
const _BRACKET_RADIUS_BY_VALUE = Object.fromEntries(BRACKETS.map((b) => [b.value, b.radius]));
const BRACKET_RADIUS = new Proxy(_BRACKET_RADIUS_BY_VALUE, {
  get(target, prop) {
    if (typeof prop !== 'string') return undefined;
    return target[prop] ?? target[normalizeBracketKey(prop)];
  },
});

function layoutForce(agents, w, h) {
  // Cheap circle-packed clustering — group agents by bracket, place clusters on a large ring.
  const bracketGroups = {};
  agents.forEach(a => {
    if (!bracketGroups[a.bracket]) bracketGroups[a.bracket] = [];
    bracketGroups[a.bracket].push(a);
  });
  const keys = Object.keys(bracketGroups);
  const R = Math.min(w, h) * 0.36;
  const cx = w / 2, cy = h / 2;
  const positions = {};
  keys.forEach((k, i) => {
    const angle = (i / keys.length) * Math.PI * 2 - Math.PI / 2;
    const bx = cx + Math.cos(angle) * R;
    const by = cy + Math.sin(angle) * R;
    const group = bracketGroups[k];
    const r = Math.max(28, Math.sqrt(group.length) * 15);
    group.forEach((a, j) => {
      const t = (j / group.length) * Math.PI * 2;
      const jitter = ((a.index * 137) % 100) / 100;
      const rr = r * (0.35 + jitter * 0.6);
      positions[a.id] = {
        x: bx + Math.cos(t + jitter * 2) * rr,
        y: by + Math.sin(t + jitter * 2) * rr,
        cx: bx, cy: by, bracket: k
      };
    });
  });
  return positions;
}

function layoutRadial(agents, w, h) {
  // Brackets as concentric rings, radial sort.
  const bracketGroups = {};
  agents.forEach(a => {
    if (!bracketGroups[a.bracket]) bracketGroups[a.bracket] = [];
    bracketGroups[a.bracket].push(a);
  });
  const keys = Object.keys(bracketGroups);
  const cx = w / 2, cy = h / 2;
  const rMin = 70;
  const rMax = Math.min(w, h) * 0.42;
  const positions = {};
  keys.forEach((k, i) => {
    // Guard: single bracket group (early frames) → 0/0=NaN without the ternary.
    const ring = rMin + (keys.length > 1 ? i / (keys.length - 1) : 0) * (rMax - rMin);
    const group = bracketGroups[k];
    const offset = (i % 2 === 0 ? 0 : Math.PI / group.length);
    group.forEach((a, j) => {
      const t = (j / group.length) * Math.PI * 2 + offset;
      positions[a.id] = { x: cx + Math.cos(t) * ring, y: cy + Math.sin(t) * ring, cx, cy, bracket: k, ring };
    });
  });
  return positions;
}

function layoutGrid(agents, w, h) {
  // 10×10 grid, row = bracket (in order), column packs within bracket.
  const bracketGroups = {};
  const bracketOrder = [];
  agents.forEach(a => {
    if (!bracketGroups[a.bracket]) { bracketGroups[a.bracket] = []; bracketOrder.push(a.bracket); }
    bracketGroups[a.bracket].push(a);
  });
  const rows = bracketOrder.length;
  const maxCols = Math.max(...bracketOrder.map(b => bracketGroups[b].length));
  const pad = 64;
  const innerW = w - pad * 2, innerH = h - pad * 2;
  const cellW = innerW / maxCols;
  const cellH = innerH / rows;
  const positions = {};
  bracketOrder.forEach((b, r) => {
    bracketGroups[b].forEach((a, c) => {
      positions[a.id] = {
        x: pad + cellW * (c + 0.5),
        y: pad + cellH * (r + 0.5),
        cellW, cellH, bracket: b, ring: r
      };
    });
  });
  return { positions, bracketOrder, cellW, cellH, pad, rows, maxCols };
}

export function Viz({ agents: rawAgents, edges: rawEdges = /** @type {Array<[string, string]>} */ ([]), layout, direction, onAgentHover, onAgentClick, highlightId, showEdges = true, round = 2 }) {
  // Enrich live agents with derived `index` (stable per-frame position) and
  // `radius` (BRACKETS lookup, default 5). Mock buildAgents() set these in the
  // AlphaSwarm-2 design; live useAgents() doesn't. Memoize so reference is
  // stable across renders unless rawAgents changes.
  const agents = useMemo(
    () => rawAgents.map((a, i) => ({
      ...a,
      index: i,
      radius: BRACKET_RADIUS[a.bracket] ?? 5,
    })),
    [rawAgents],
  );

  const wrapRef = useRef(null);
  const [size, setSize] = useState({ w: 800, h: 600 });

  useEffect(() => {
    if (!wrapRef.current) return;
    const ro = new ResizeObserver(entries => {
      for (const e of entries) {
        const { width, height } = e.contentRect;
        setSize({ w: width, h: height });
      }
    });
    ro.observe(wrapRef.current);
    return () => ro.disconnect();
  }, []);

  // parse_error gets a distinct muted treatment (not coerced to hold color).
  const sigColor = (s) => s === 'buy' ? 'var(--buy)' : s === 'sell' ? 'var(--sell)' : s === 'parse_error' ? 'var(--text-3)' : 'var(--hold)';

  const gridData = layout === 'grid' ? layoutGrid(agents, size.w, size.h) : null;
  const positions = useMemo(() => {
    if (layout === 'force')  return layoutForce(agents, size.w, size.h);
    if (layout === 'radial') return layoutRadial(agents, size.w, size.h);
    if (layout === 'grid')   return gridData.positions;
    return {};
  }, [agents, layout, size.w, size.h]);

  // Real INFLUENCED_BY edges from EdgesContext — [source, target] tuples.
  // Empty until the backend persists edges for the round (no fabricated edges).
  const edges = useMemo(
    () =>
      layout === 'grid'
        ? []
        : rawEdges.map(([source, target]) => ({ source, target })),
    [rawEdges, layout],
  );

  const bracketGroups = useMemo(() => {
    const g = {};
    agents.forEach(a => { if (!g[a.bracket]) g[a.bracket] = { display: a.bracketDisplay, items: [] }; g[a.bracket].items.push(a); });
    return g;
  }, [agents]);

  return (
    <div ref={wrapRef} style={{ width:'100%', height:'100%', position:'relative' }}>
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
            {Object.values(bracketGroups).map((_, i, arr) => {
              const rMin = 70;
              const rMax = Math.min(size.w, size.h) * 0.42;
              // Guard: single bracket group (early frames) → 0/0=NaN without the ternary.
              const ring = rMin + (arr.length > 1 ? i / (arr.length - 1) : 0) * (rMax - rMin);
              return <circle key={i} cx={size.w/2} cy={size.h/2} r={ring} fill="none" stroke="var(--border)" strokeDasharray="2 4" />;
            })}
          </g>
        )}

        {layout === 'grid' && gridData && (
          <g>
            {gridData.bracketOrder.map((b, r) => (
              <text
                key={b}
                x={gridData.pad - 12}
                y={gridData.pad + gridData.cellH * (r + 0.5)}
                className="bracket-label"
                textAnchor="end"
                dominantBaseline="central"
              >
                {bracketGroups[b].display}
              </text>
            ))}
          </g>
        )}

        {/* Edges */}
        {showEdges && layout !== 'grid' && (
          <g>
            {edges.map((e, i) => {
              const s = positions[e.source]; const t = positions[e.target];
              if (!s || !t) return null;
              return (
                <path
                  key={i}
                  className={`edge ${e.active ? 'active' : ''}`}
                  d={`M ${s.x} ${s.y} Q ${(s.x+t.x)/2} ${(s.y+t.y)/2 - 20} ${t.x} ${t.y}`}
                  style={{ color: e.active ? 'var(--accent)' : undefined }}
                />
              );
            })}
          </g>
        )}

        {/* Bracket labels on force layout */}
        {layout === 'force' && (
          <g>
            {Object.entries(bracketGroups).map(([k, g], i, arr) => {
              const angle = (i / arr.length) * Math.PI * 2 - Math.PI / 2;
              const R = Math.min(size.w, size.h) * 0.36 + Math.max(28, Math.sqrt(g.items.length) * 15) + 14;
              const x = size.w/2 + Math.cos(angle) * R;
              const y = size.h/2 + Math.sin(angle) * R;
              return <text key={k} x={x} y={y} textAnchor="middle" dominantBaseline="central" className="bracket-label">{g.display.toUpperCase()} · {g.items.length}</text>;
            })}
          </g>
        )}

        {/* Nodes */}
        <g>
          {agents.map(a => {
            const p = positions[a.id]; if (!p) return null;
            const color = sigColor(a.signal);
            const r = a.radius * 0.7 + (layout === 'grid' ? 6 : 0);
            const isHL = highlightId === a.id;
            if (layout === 'grid') {
              const size = Math.min(gridData.cellW, gridData.cellH) * 0.72;
              return (
                <g key={a.id} transform={`translate(${p.x - size/2}, ${p.y - size/2})`}>
                  <rect
                    width={size} height={size} rx={2}
                    className={`grid-cell${a.thinking ? ' thinking' : ''}`}
                    fill={color}
                    opacity={0.88}
                    onMouseEnter={(e) => onAgentHover && onAgentHover(a, e)}
                    onMouseLeave={() => onAgentHover && onAgentHover(null)}
                    onClick={() => onAgentClick && onAgentClick(a)}
                  />
                  {a.flipped && <circle cx={size - 4} cy={4} r={2.5} fill="var(--accent)" />}
                </g>
              );
            }
            return (
              <g key={a.id} transform={`translate(${p.x}, ${p.y})`}>
                {direction === 'c' && <circle r={r*2.2} fill="url(#nodeGlow)" style={{ color }} />}
                <circle
                  className={`node${a.thinking ? ' thinking' : ''}`}
                  r={r}
                  fill={color}
                  stroke={isHL ? 'var(--accent)' : 'rgba(255,255,255,0.15)'}
                  strokeWidth={isHL ? 2 : 1}
                  filter={direction === 'c' ? 'url(#glow)' : undefined}
                  onMouseEnter={(e) => onAgentHover && onAgentHover(a, e)}
                  onMouseLeave={() => onAgentHover && onAgentHover(null)}
                  onClick={() => onAgentClick && onAgentClick(a)}
                />
                {a.flipped && <circle r={r+3} fill="none" stroke="var(--accent)" strokeDasharray="2 2" />}
              </g>
            );
          })}
        </g>
      </svg>
    </div>
  );
}
