// Edge geometry and aggregation for the influence graph. Direction follows
// src/api/edges.ts: Edge.source_id is the citing agent, Edge.target_id the cited
// one, and arrows are drawn from the cited agent to the citing agent (influence
// flows cited -> citing). Design notes: docs/DECISIONS.md#adr-hero-graph.
import type { Edge } from '../api/edges';
import { BRACKETS } from '../data';
import type { GroupKey } from './layout';

export interface Point {
  x: number;
  y: number;
}

export interface CurveOptions {
  /** Perpendicular bow in px; default min(48, 20% of the distance). */
  offset?: number;
  /** Px trimmed from the end so an arrowhead stops at the target's rim. */
  pullback?: number;
}

const r2 = (v: number): number => Math.round(v * 100) / 100;

/**
 * Quadratic curve from s to t, bowed to the left of the direction of travel.
 * Swapping s and t bows the other way, so A->B and B->A never overlap.
 */
export function curvedPath(s: Point, t: Point, opts: CurveOptions = {}): string {
  const dx = t.x - s.x;
  const dy = t.y - s.y;
  const len = Math.hypot(dx, dy);
  if (!Number.isFinite(len) || len < 1e-6) return `M${r2(s.x)},${r2(s.y)}`;
  const nx = -dy / len;
  const ny = dx / len;
  const offset = opts.offset ?? Math.min(48, len * 0.2);
  const cx = (s.x + t.x) / 2 + nx * offset;
  const cy = (s.y + t.y) / 2 + ny * offset;
  let ex = t.x;
  let ey = t.y;
  const pull = Math.min(Math.max(0, opts.pullback ?? 0), len * 0.45);
  if (pull > 0) {
    const tx = t.x - cx;
    const ty = t.y - cy;
    const tl = Math.hypot(tx, ty) || 1;
    ex = t.x - (tx / tl) * pull;
    ey = t.y - (ty / tl) * pull;
  }
  return `M${r2(s.x)},${r2(s.y)} Q${r2(cx)},${r2(cy)} ${r2(ex)},${r2(ey)}`;
}

/** Citations between two brackets: `from` is the cited bracket, `to` the citing one. */
export interface RibbonCell {
  from: GroupKey;
  to: GroupKey;
  count: number;
}

export interface BracketMatrix {
  /** Row/column order: registry brackets, then 'unknown'. */
  keys: GroupKey[];
  /** counts[from][to], indexed like `keys`. */
  counts: number[][];
  /** Every edge counted once (equals edges.length). */
  total: number;
  /** Off-diagonal cells with count > 0, largest first, ties in key order. */
  cells: RibbonCell[];
  /** Citations inside one bracket (the diagonal), only brackets with a count. */
  within: Map<GroupKey, number>;
}

export const MATRIX_KEYS: readonly GroupKey[] = [...BRACKETS.map((b) => b.key), 'unknown'];

/** 11x11 count matrix of citations between brackets (registry order, then 'unknown'). */
export function aggregateByBracket(
  edges: readonly Edge[],
  bracketOf: (id: string) => GroupKey,
): BracketMatrix {
  const keys = [...MATRIX_KEYS];
  const index = new Map(keys.map((k, i) => [k, i]));
  const counts = keys.map(() => keys.map(() => 0));
  const unknown = keys.length - 1;
  for (const e of edges) {
    const from = index.get(bracketOf(e.target_id)) ?? unknown;
    const to = index.get(bracketOf(e.source_id)) ?? unknown;
    const row = counts[from];
    if (row) row[to] = (row[to] ?? 0) + 1;
  }
  const cells: RibbonCell[] = [];
  const within = new Map<GroupKey, number>();
  keys.forEach((from, i) => {
    keys.forEach((to, j) => {
      const count = counts[i]?.[j] ?? 0;
      if (count === 0) return;
      if (i === j) within.set(from, count);
      else cells.push({ from, to, count });
    });
  });
  cells.sort(
    (a, b) =>
      b.count - a.count ||
      (index.get(a.from) ?? 0) - (index.get(b.from) ?? 0) ||
      (index.get(a.to) ?? 0) - (index.get(b.to) ?? 0),
  );
  return { keys, counts, total: edges.length, cells, within };
}
