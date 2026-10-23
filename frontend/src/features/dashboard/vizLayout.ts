// Deterministic agent-graph layouts: brackets as clusters, rings or grid rows.
// No physics (docs/DECISIONS.md#kr-41-1-01). Same input -> same coordinates.

export type VizLayout = 'force' | 'radial' | 'grid';

export interface LayoutAgent {
  id: string;
  bracket: string;
  index: number;
}

export interface NodePosition {
  x: number;
  y: number;
  bracket: string;
}

export interface GridLayout {
  positions: Map<string, NodePosition>;
  bracketOrder: string[];
  cellW: number;
  cellH: number;
  pad: number;
}

/** Group agents by bracket, keeping first-seen bracket order. */
function groupByBracket<T extends { bracket: string }>(agents: readonly T[]): Map<string, T[]> {
  const groups = new Map<string, T[]>();
  for (const agent of agents) {
    const group = groups.get(agent.bracket);
    if (group) group.push(agent);
    else groups.set(agent.bracket, [agent]);
  }
  return groups;
}

/** Radius of one bracket's cluster in the force layout. */
export function clusterRadius(groupSize: number): number {
  return Math.max(28, Math.sqrt(groupSize) * 15);
}

/** Radius of ring `i` of `count` in the radial layout (one ring per bracket). */
export function ringRadius(i: number, count: number, w: number, h: number): number {
  const rMin = 70;
  const rMax = Math.min(w, h) * 0.42;
  return rMin + (count > 1 ? i / (count - 1) : 0) * (rMax - rMin);
}

/** Brackets as clusters on a large ring; members jittered by their index. */
export function layoutForce(agents: readonly LayoutAgent[], w: number, h: number): Map<string, NodePosition> {
  const groups = [...groupByBracket(agents)];
  const R = Math.min(w, h) * 0.36;
  const cx = w / 2;
  const cy = h / 2;
  const positions = new Map<string, NodePosition>();
  groups.forEach(([bracket, group], i) => {
    const angle = (i / groups.length) * Math.PI * 2 - Math.PI / 2;
    const bx = cx + Math.cos(angle) * R;
    const by = cy + Math.sin(angle) * R;
    const r = clusterRadius(group.length);
    group.forEach((agent, j) => {
      const t = (j / group.length) * Math.PI * 2;
      const jitter = ((agent.index * 137) % 100) / 100;
      const rr = r * (0.35 + jitter * 0.6);
      positions.set(agent.id, {
        x: bx + Math.cos(t + jitter * 2) * rr,
        y: by + Math.sin(t + jitter * 2) * rr,
        bracket,
      });
    });
  });
  return positions;
}

/** Brackets as concentric rings, odd rings rotated by half a slot. */
export function layoutRadial(agents: readonly LayoutAgent[], w: number, h: number): Map<string, NodePosition> {
  const groups = [...groupByBracket(agents)];
  const cx = w / 2;
  const cy = h / 2;
  const positions = new Map<string, NodePosition>();
  groups.forEach(([bracket, group], i) => {
    const ring = ringRadius(i, groups.length, w, h);
    const offset = i % 2 === 0 ? 0 : Math.PI / group.length;
    group.forEach((agent, j) => {
      const t = (j / group.length) * Math.PI * 2 + offset;
      positions.set(agent.id, { x: cx + Math.cos(t) * ring, y: cy + Math.sin(t) * ring, bracket });
    });
  });
  return positions;
}

/** One grid row per bracket (first-seen order), members packed left to right. */
export function layoutGrid(agents: readonly LayoutAgent[], w: number, h: number): GridLayout {
  const groups = [...groupByBracket(agents)];
  const pad = 64;
  // max(1, …) keeps the cells finite for an empty frame; non-empty input is unchanged.
  const rows = Math.max(1, groups.length);
  const maxCols = Math.max(1, ...groups.map(([, group]) => group.length));
  const cellW = (w - pad * 2) / maxCols;
  const cellH = (h - pad * 2) / rows;
  const positions = new Map<string, NodePosition>();
  groups.forEach(([bracket, group], r) => {
    group.forEach((agent, c) => {
      positions.set(agent.id, { x: pad + cellW * (c + 0.5), y: pad + cellH * (r + 0.5), bracket });
    });
  });
  return { positions, bracketOrder: groups.map(([bracket]) => bracket), cellW, cellH, pad };
}
