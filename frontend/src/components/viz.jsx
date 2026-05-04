// Visualization module — force / grid / radial layouts, all SVG-based.
// WAVE-2-NOTE: wired to AgentsContext + EdgesContext (Plan 41.1-03). Do NOT
// reintroduce local useEdges or snapshot.edges reads. Reviewer item 9: viz MUST
// NOT call useEdges directly and MUST NOT own any fetch of /api/edges — the
// EdgesProvider (Plan 02) owns the single useEdges call for the whole app.
import { useMemo, useState, useEffect, useRef } from 'react';
import { useAgents } from '../context/AgentsContext';
import { useEdgesCtx } from '../context/EdgesContext';

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
      const idx = a.index ?? j;
      const jitter = ((idx * 137) % 100) / 100;
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
    const ring = rMin + (i / Math.max(1, (keys.length - 1))) * (rMax - rMin);
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
  const maxCols = Math.max(1, ...bracketOrder.map(b => bracketGroups[b].length));
  const pad = 64;
  const innerW = w - pad * 2, innerH = h - pad * 2;
  const cellW = innerW / maxCols;
  const cellH = innerH / Math.max(1, rows);
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

export function Viz({ layout, direction, onAgentHover, onAgentClick, highlightId, showEdges = true }) {
  const wrapRef = useRef(null);
  const [size, setSize] = useState({ w: 800, h: 600 });
  // Live render path: agents + edges come from split contexts built in Plan 02.
  const { agents } = useAgents();
  const { edges: ctxEdges } = useEdgesCtx();
  const liveAgents = agents;
  const liveEdges = ctxEdges;

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

  const sigColor = (s) => s === 'buy' ? 'var(--buy)' : s === 'sell' ? 'var(--sell)' : 'var(--hold)';

  // All hooks must run unconditionally (Rules of Hooks); the empty-state
  // guard below renders an empty SVG only after all useMemo calls are set up.
  const gridData = layout === 'grid' ? layoutGrid(liveAgents, size.w, size.h) : null;
  const positions = useMemo(() => {
    if (layout === 'force')  return layoutForce(liveAgents, size.w, size.h);
    if (layout === 'radial') return layoutRadial(liveAgents, size.w, size.h);
    if (layout === 'grid')   return gridData ? gridData.positions : {};
    return {};
  }, [liveAgents, layout, size.w, size.h, gridData]);

  // Normalise CONTRACT [source, target] tuples into the design's {source, target, active} shape.
  const edges = useMemo(() => {
    if (layout === 'grid') return [];
    const tuples = Array.isArray(liveEdges) ? liveEdges : [];
    return tuples.map(([source, target], i) => ({ source, target, active: i < 14 }));
  }, [liveEdges, layout]);

  const bracketGroups = useMemo(() => {
    const g = {};
    liveAgents.forEach(a => {
      if (!g[a.bracket]) g[a.bracket] = { display: a.bracketDisplay || a.bracket, items: [] };
      g[a.bracket].items.push(a);
    });
    return g;
  }, [liveAgents]);

  // Null / pre-connection guard: empty SVG placeholder while the websocket
  // has not yet delivered a frame (AgentsProvider hasn't mounted data).
  if (liveAgents.length === 0) {
    return (
      <div ref={wrapRef} style={{ width:'100%', height:'100%', position:'relative' }}>
        <svg className="viz-svg viz-empty" role="img" aria-label="force graph pending" viewBox={`0 0 ${size.w} ${size.h}`} preserveAspectRatio="none" />
      </div>
    );
  }

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
              const ring = rMin + (i / Math.max(1, (arr.length - 1))) * (rMax - rMin);
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
          {liveAgents.map(a => {
            const p = positions[a.id]; if (!p) return null;
            const color = sigColor(a.signal);
            const baseRadius = a.radius ?? 8;
            const r = baseRadius * 0.7 + (layout === 'grid' ? 6 : 0);
            const isHL = highlightId === a.id;
            if (layout === 'grid') {
              const cellSize = gridData ? Math.min(gridData.cellW, gridData.cellH) * 0.72 : 12;
              return (
                <g key={a.id} transform={`translate(${p.x - cellSize/2}, ${p.y - cellSize/2})`}>
                  <rect
                    width={cellSize} height={cellSize} rx={2}
                    className="grid-cell"
                    fill={color}
                    opacity={0.88}
                    onMouseEnter={(e) => onAgentHover && onAgentHover(a, e)}
                    onMouseLeave={() => onAgentHover && onAgentHover(null)}
                    onClick={() => onAgentClick && onAgentClick(a)}
                  />
                  {a.flipped && <circle cx={cellSize - 4} cy={4} r={2.5} fill="var(--accent)" />}
                </g>
              );
            }
            return (
              <g key={a.id} transform={`translate(${p.x}, ${p.y})`}>
                {direction === 'c' && <circle r={r*2.2} fill="url(#nodeGlow)" style={{ color }} />}
                <circle
                  className="node"
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
