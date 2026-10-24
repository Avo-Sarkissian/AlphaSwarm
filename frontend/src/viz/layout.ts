// Deterministic agent-graph layouts, computed from the static roster and the
// canvas size only: frame order never moves a node, and live and replay frames
// of the same cycle draw identical positions. No physics
// (docs/DECISIONS.md#kr-41-1-01); design notes in docs/DECISIONS.md#adr-hero-graph.
import { BRACKETS, isBracketKey } from '../data';
import type { BracketKey } from '../types';

export type GraphLayout = 'clusters' | 'radial' | 'grid';
export type GroupKey = BracketKey | 'unknown';

export interface RosterEntry {
  id: string;
  bracket: GroupKey;
}

export interface Size {
  w: number;
  h: number;
}

/** One agent's slot: centre plus the largest radius that never touches a neighbour. */
export interface NodeSlot {
  x: number;
  y: number;
  r: number;
}

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** A corner of the canvas that an overlay covers; the scene keeps out of it. */
export interface Reserve {
  corner: 'top-left' | 'top-right' | 'bottom-left' | 'bottom-right';
  w: number;
  h: number;
}

/** Where a bracket sits and where its label goes. */
export interface GroupGuide {
  bracket: GroupKey;
  label: string;
  labelX: number;
  labelY: number;
  anchor: 'start' | 'middle' | 'end';
  /** Cluster centre (clusters), canvas centre (radial), first cell centre (grid). */
  cx: number;
  cy: number;
  /** Cluster radius including node slots (clusters), ring radius (radial), 0 (grid). */
  radius: number;
}

export interface Scene {
  layout: GraphLayout;
  size: Size;
  nodes: Map<string, NodeSlot>;
  groups: GroupGuide[];
}

export interface SceneOptions {
  reserve?: readonly Reserve[];
}

/** Margin kept free on every side of the canvas. */
export const BASE_INSET = 16;
/** Bracket label metrics; mirror `.ig-label` in styles.css (font-size, letter-spacing). */
export const LABEL_FONT_PX = 9.5;
export const LABEL_CHAR_PX = 6.5;
const LABEL_GAP = 8;
/** Golden angle: successive phyllotaxis points never line up. */
const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));
/** Nearest phyllotaxis neighbours sit 1.546 spacings apart, so a 0.7-spacing slot never touches. */
const SLOT_PER_SPACING = 0.7;
const UNKNOWN_DISPLAY = 'Unknown';
const ORDER: readonly GroupKey[] = [...BRACKETS.map((b) => b.key), 'unknown'];

function pad2(n: number): string {
  return String(n).padStart(2, '0');
}

/** The canonical 100-agent roster: registry order, ids `{key}_{NN}` like the backend. */
export function rosterFromBrackets(brackets = BRACKETS): RosterEntry[] {
  return brackets.flatMap((b) =>
    Array.from({ length: b.count }, (_, i) => ({ id: `${b.key}_${pad2(i + 1)}`, bracket: b.key })),
  );
}

function groupOfId(id: string): GroupKey {
  const key = id.replace(/_\d+$/, '');
  return isBracketKey(key) ? key : 'unknown';
}

const byId = (a: RosterEntry, b: RosterEntry): number =>
  a.id.localeCompare(b.id, 'en', { numeric: true });

/**
 * The canonical roster plus any frame id it does not know (registry drift or an
 * unknown bracket), so every agent on screen gets a slot. Input order is irrelevant.
 */
export function mergeRoster(base: readonly RosterEntry[], ids: Iterable<string>): RosterEntry[] {
  const known = new Set(base.map((e) => e.id));
  const extra = [...new Set(ids)]
    .filter((id) => !known.has(id))
    .map((id) => ({ id, bracket: groupOfId(id) }));
  return [...base, ...extra];
}

interface Group {
  key: GroupKey;
  entries: RosterEntry[];
  label: string;
}

function displayOf(key: GroupKey): string {
  return key === 'unknown' ? UNKNOWN_DISPLAY : (BRACKETS.find((b) => b.key === key)?.display ?? key);
}

/** Groups in registry order, members sorted by id: the only order the layout ever uses. */
function groupRoster(roster: readonly RosterEntry[]): Group[] {
  const buckets = new Map<GroupKey, RosterEntry[]>();
  for (const entry of roster) {
    const list = buckets.get(entry.bracket);
    if (list) {
      if (!list.some((e) => e.id === entry.id)) list.push(entry);
    } else {
      buckets.set(entry.bracket, [entry]);
    }
  }
  return ORDER.flatMap((key) => {
    const entries = buckets.get(key);
    if (!entries || entries.length === 0) return [];
    const sorted = [...entries].sort(byId);
    return [{ key, entries: sorted, label: `${displayOf(key).toUpperCase()} · ${sorted.length}` }];
  });
}

function labelWidth(label: string): number {
  return label.length * LABEL_CHAR_PX;
}

export function reserveRect(reserve: Reserve, size: Size): Rect {
  const x = reserve.corner.endsWith('left') ? 0 : size.w - reserve.w;
  const y = reserve.corner.startsWith('top') ? 0 : size.h - reserve.h;
  return { x, y, w: reserve.w, h: reserve.h };
}

function insideBox(rect: Rect, box: Rect): boolean {
  return (
    rect.x >= box.x - 1e-6 &&
    rect.y >= box.y - 1e-6 &&
    rect.x + rect.w <= box.x + box.w + 1e-6 &&
    rect.y + rect.h <= box.y + box.h + 1e-6
  );
}

function overlaps(a: Rect, b: Rect): boolean {
  return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
}

const slotRect = (n: NodeSlot): Rect => ({ x: n.x - n.r, y: n.y - n.r, w: 2 * n.r, h: 2 * n.r });

/** Text box of a group label, from the same metrics the CSS uses. */
export function labelRect(g: GroupGuide): Rect {
  const w = labelWidth(g.label);
  const x = g.anchor === 'start' ? g.labelX : g.anchor === 'end' ? g.labelX - w : g.labelX - w / 2;
  return { x, y: g.labelY - LABEL_FONT_PX / 2 - 1, w, h: LABEL_FONT_PX + 2 };
}

function fits(scene: Scene, box: Rect, keepOut: readonly Rect[]): boolean {
  const rects = [...[...scene.nodes.values()].map(slotRect), ...scene.groups.map(labelRect)];
  return rects.every((r) => insideBox(r, box) && keepOut.every((k) => !overlaps(r, k)));
}

/** Largest scale in [lo, hi] for which `build(scale)` fits; `lo` when nothing fits. */
function largestFitting(lo: number, hi: number, build: (scale: number) => Scene, ok: (s: Scene) => boolean): Scene {
  let best = build(lo);
  if (!ok(best)) return best;
  let a = lo;
  let b = Math.max(lo, hi);
  for (let i = 0; i < 40; i += 1) {
    const mid = (a + b) / 2;
    const scene = build(mid);
    if (ok(scene)) {
      best = scene;
      a = mid;
    } else {
      b = mid;
    }
  }
  return best;
}

function clusterScene(groups: Group[], size: Size, cx: number, cy: number, spacing: number): Scene {
  const slot = spacing * SLOT_PER_SPACING;
  const k = groups.length;
  const radii = groups.map((g) => spacing * Math.sqrt(Math.max(0, g.entries.length - 0.5)) + slot);
  // Ring radius: every pair of clusters, adjacent or not, stays one spacing apart.
  let ring = 0;
  for (let a = 0; a < k; a += 1) {
    for (let b = a + 1; b < k; b += 1) {
      const steps = Math.min(b - a, k - (b - a));
      const chord = 2 * Math.sin((Math.PI * steps) / k);
      const need = ((radii[a] ?? 0) + (radii[b] ?? 0) + spacing) / chord;
      ring = Math.max(ring, need);
    }
  }
  const nodes = new Map<string, NodeSlot>();
  const guides: GroupGuide[] = [];
  groups.forEach((g, i) => {
    const angle = -Math.PI / 2 + (2 * Math.PI * i) / k;
    const gx = cx + ring * Math.cos(angle);
    const gy = cy + ring * Math.sin(angle);
    g.entries.forEach((entry, j) => {
      const r = spacing * Math.sqrt(j + 0.5);
      const t = j * GOLDEN_ANGLE;
      nodes.set(entry.id, { x: gx + r * Math.cos(t), y: gy + r * Math.sin(t), r: slot });
    });
    // Labels point away from the ring centre, so they never cover another cluster.
    const radius = radii[i] ?? 0;
    const cos = Math.cos(angle);
    const anchor = k === 1 ? 'middle' : cos > 0.3 ? 'start' : cos < -0.3 ? 'end' : 'middle';
    const reach = radius + LABEL_GAP + (anchor === 'middle' ? LABEL_FONT_PX / 2 : 0);
    const dir = k === 1 ? -Math.PI / 2 : angle;
    guides.push({
      bracket: g.key,
      label: g.label,
      labelX: gx + reach * Math.cos(dir),
      labelY: gy + reach * Math.sin(dir),
      anchor,
      cx: gx,
      cy: gy,
      radius,
    });
  });
  return { layout: 'clusters', size, nodes, groups: guides };
}

function radialScene(groups: Group[], size: Size, cx: number, cy: number, unit: number): Scene {
  const ringGap = Math.max(2.6 * unit, LABEL_FONT_PX + 3);
  const labelSpan = groups.map((g) => labelWidth(g.label) + 8);
  // Inner radius: each ring must fit its nodes (2.2 units apart) plus a label gap at the top.
  let inner = 2.6 * unit;
  groups.forEach((g, i) => {
    const needed = (2.2 * unit * g.entries.length + (labelSpan[i] ?? 0) + 2 * unit) / (2 * Math.PI);
    inner = Math.max(inner, needed - i * ringGap);
  });
  const nodes = new Map<string, NodeSlot>();
  const guides: GroupGuide[] = [];
  groups.forEach((g, i) => {
    const ring = inner + i * ringGap;
    const gap = ((labelSpan[i] ?? 0) + 2 * unit) / ring;
    const step = (2 * Math.PI - gap) / g.entries.length;
    g.entries.forEach((entry, j) => {
      const t = -Math.PI / 2 + gap / 2 + (j + 0.5) * step;
      nodes.set(entry.id, { x: cx + ring * Math.cos(t), y: cy + ring * Math.sin(t), r: unit });
    });
    guides.push({ bracket: g.key, label: g.label, labelX: cx, labelY: cy - ring, anchor: 'middle', cx, cy, radius: ring });
  });
  return { layout: 'radial', size, nodes, groups: guides };
}

function gridScene(groups: Group[], size: Size, box: Rect): Scene {
  const labelColumn = Math.max(...groups.map((g) => labelWidth(g.label))) + 12;
  const cols = Math.max(1, ...groups.map((g) => g.entries.length));
  const rows = Math.max(1, groups.length);
  const cellW = Math.max(0, box.w - labelColumn) / cols;
  const cellH = box.h / rows;
  const slot = Math.min(cellW, cellH) * 0.42;
  const left = box.x + labelColumn;
  const nodes = new Map<string, NodeSlot>();
  const guides: GroupGuide[] = groups.map((g, row) => {
    const y = box.y + cellH * (row + 0.5);
    g.entries.forEach((entry, c) => nodes.set(entry.id, { x: left + cellW * (c + 0.5), y, r: slot }));
    return { bracket: g.key, label: g.label, labelX: left - 8, labelY: y, anchor: 'end' as const, cx: left + cellW / 2, cy: y, radius: 0 };
  });
  return { layout: 'grid', size, nodes, groups: guides };
}

/**
 * Full scene: node slots plus bracket guides. Brackets follow the registry
 * order and members their id order, so the result depends only on the roster's
 * membership, the size and the layout. Everything stays inside a BASE_INSET
 * margin and outside the reserved corners whenever the canvas is big enough.
 */
export function computeScene(
  roster: readonly RosterEntry[],
  size: Size,
  layout: GraphLayout,
  opts: SceneOptions = {},
): Scene {
  const w = Number.isFinite(size.w) ? Math.max(0, size.w) : 0;
  const h = Number.isFinite(size.h) ? Math.max(0, size.h) : 0;
  const safe: Size = { w, h };
  const groups = groupRoster(roster);
  if (groups.length === 0) return { layout, size: safe, nodes: new Map(), groups: [] };
  const keepOut = (opts.reserve ?? []).map((r) => reserveRect(r, safe));
  const box: Rect = { x: BASE_INSET, y: BASE_INSET, w: Math.max(0, w - 2 * BASE_INSET), h: Math.max(0, h - 2 * BASE_INSET) };

  if (layout === 'grid') {
    const reserved = opts.reserve ?? [];
    const topH = Math.max(0, ...reserved.filter((r) => r.corner.startsWith('top')).map((r) => r.h));
    const bottomH = Math.max(0, ...reserved.filter((r) => r.corner.startsWith('bottom')).map((r) => r.h));
    const y0 = Math.max(box.y, topH);
    const y1 = Math.min(box.y + box.h, h - bottomH);
    const gridBox: Rect = { x: box.x, y: y0, w: box.w, h: Math.max(0, y1 - y0) };
    return gridScene(groups, safe, gridBox);
  }
  const cx = box.x + box.w / 2;
  const cy = box.y + box.h / 2;
  const ok = (s: Scene) => fits(s, box, keepOut);
  const limit = Math.max(1, Math.min(box.w, box.h));
  if (layout === 'radial') return largestFitting(0.5, limit / 8, (u) => radialScene(groups, safe, cx, cy, u), ok);
  return largestFitting(0.5, limit / 4, (s) => clusterScene(groups, safe, cx, cy, s), ok);
}

/** Node slots only: the shape other callers need when they do not draw labels. */
export function computeLayout(
  roster: readonly RosterEntry[],
  size: Size,
  layout: GraphLayout,
): Map<string, NodeSlot> {
  return computeScene(roster, size, layout).nodes;
}
