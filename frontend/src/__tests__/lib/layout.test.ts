// Deterministic layout: permutation invariance, no overlap, in bounds, no NaN,
// reserved corners kept free, labels readable at small heights.
import { describe, expect, it } from 'vitest';
import {
  BASE_INSET,
  computeLayout,
  computeScene,
  labelRect,
  mergeRoster,
  reserveRect,
  rosterFromBrackets,
  type GraphLayout,
  type NodeSlot,
  type Rect,
  type RosterEntry,
  type Scene,
} from '../../viz/layout';

const ROSTER = rosterFromBrackets();
const LAYOUTS: readonly GraphLayout[] = ['clusters', 'radial', 'grid'];
const SIZES = [
  { w: 1200, h: 800 },
  { w: 800, h: 600 },
  { w: 640, h: 420 },
] as const;
const RING = [{ corner: 'top-right', w: 138, h: 138 }] as const;

/** Deterministic Fisher-Yates with a small LCG, so the test itself is reproducible. */
function shuffled<T>(items: readonly T[], seed: number): T[] {
  const out = [...items];
  let s = seed;
  for (let i = out.length - 1; i > 0; i -= 1) {
    s = (s * 1103515245 + 12345) % 2147483648;
    const j = s % (i + 1);
    const tmp = out[i] as T;
    out[i] = out[j] as T;
    out[j] = tmp;
  }
  return out;
}

const sorted = (nodes: ReadonlyMap<string, NodeSlot>) => [...nodes.entries()].sort(([a], [b]) => (a < b ? -1 : 1));
const slotRect = (n: NodeSlot): Rect => ({ x: n.x - n.r, y: n.y - n.r, w: 2 * n.r, h: 2 * n.r });
const overlaps = (a: Rect, b: Rect) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
const inside = (r: Rect, w: number, h: number) =>
  r.x >= BASE_INSET - 1e-6 && r.y >= BASE_INSET - 1e-6 && r.x + r.w <= w - BASE_INSET + 1e-6 && r.y + r.h <= h - BASE_INSET + 1e-6;

function overlappingPairs(scene: Scene): string[] {
  const list = [...scene.nodes.entries()];
  const bad: string[] = [];
  for (let i = 0; i < list.length; i += 1) {
    for (let j = i + 1; j < list.length; j += 1) {
      const [ia, a] = list[i] as [string, NodeSlot];
      const [ib, b] = list[j] as [string, NodeSlot];
      if (Math.hypot(a.x - b.x, a.y - b.y) < a.r + b.r - 1e-6) bad.push(`${ia}~${ib}`);
    }
  }
  return bad;
}

describe('rosterFromBrackets', () => {
  it('lists the 100 agents in registry order with backend-style ids', () => {
    expect(ROSTER).toHaveLength(100);
    expect(ROSTER.slice(0, 2)).toEqual([
      { id: 'institutions_01', bracket: 'institutions' },
      { id: 'institutions_02', bracket: 'institutions' },
    ]);
    expect(ROSTER.at(-1)).toEqual({ id: 'allocators_05', bracket: 'allocators' });
  });
});

describe('mergeRoster', () => {
  it('adds frame ids the registry does not know, once, and ignores input order', () => {
    const ids = ['quants_01', 'whales_01', 'quants_13', 'whales_01'];
    const merged = mergeRoster(ROSTER, ids);
    expect(merged).toHaveLength(102);
    expect(merged.slice(100)).toEqual([
      { id: 'whales_01', bracket: 'unknown' },
      { id: 'quants_13', bracket: 'quants' },
    ]);
    const a = computeLayout(mergeRoster(ROSTER, ids), { w: 800, h: 600 }, 'clusters');
    const b = computeLayout(mergeRoster(ROSTER, [...ids].reverse()), { w: 800, h: 600 }, 'clusters');
    expect(sorted(a)).toEqual(sorted(b));
  });
});

describe.each(LAYOUTS)('computeScene(%s)', (layout) => {
  it('does not depend on roster order (live vs replay frames)', () => {
    const base = computeLayout(ROSTER, { w: 800, h: 600 }, layout);
    for (const seed of [1, 7, 42]) {
      const other = computeLayout(shuffled<RosterEntry>(ROSTER, seed), { w: 800, h: 600 }, layout);
      expect(sorted(other)).toEqual(sorted(base));
    }
  });

  it.each(SIZES)('never overlaps two node slots at $w x $h', (size) => {
    const scene = computeScene(ROSTER, size, layout, { reserve: RING });
    expect(scene.nodes.size).toBe(100);
    expect(overlappingPairs(scene)).toEqual([]);
  });

  it.each(SIZES)('keeps nodes and labels inside the margin and out of the reserved corner at $w x $h', (size) => {
    const scene = computeScene(ROSTER, size, layout, { reserve: RING });
    const ring = reserveRect(RING[0], size);
    const rects = [...[...scene.nodes.values()].map(slotRect), ...scene.groups.map(labelRect)];
    expect(rects.filter((r) => !inside(r, size.w, size.h))).toEqual([]);
    expect(rects.filter((r) => overlaps(r, ring))).toEqual([]);
  });

  it.each(SIZES)('never draws a label over a node or another label at $w x $h', (size) => {
    const scene = computeScene(ROSTER, size, layout, { reserve: RING });
    const labels = scene.groups.map(labelRect);
    const nodes = [...scene.nodes.values()].map(slotRect);
    const hits = labels.flatMap((l, i) => [
      ...nodes.filter((n) => overlaps(l, n)).map(() => `label ${i} x node`),
      ...labels.slice(i + 1).filter((m) => overlaps(l, m)).map(() => `label ${i} x label`),
    ]);
    expect(hits).toEqual([]);
  });

  it.each([
    { w: 0, h: 0 },
    { w: 1, h: 1 },
    { w: Number.NaN, h: 600 },
  ])('returns finite numbers for a degenerate $w x $h canvas', (size) => {
    const scene = computeScene(ROSTER, size, layout);
    const numbers = [
      ...[...scene.nodes.values()].flatMap((n) => [n.x, n.y, n.r]),
      ...scene.groups.flatMap((g) => [g.labelX, g.labelY, g.cx, g.cy, g.radius]),
    ];
    expect(numbers.every(Number.isFinite)).toBe(true);
  });

  it('returns an empty scene for an empty roster', () => {
    const scene = computeScene([], { w: 800, h: 600 }, layout);
    expect(scene.nodes.size).toBe(0);
    expect(scene.groups).toEqual([]);
  });

  it('labels brackets in registry order, unknown last', () => {
    const scene = computeScene(mergeRoster(ROSTER, ['whales_01']), { w: 800, h: 600 }, layout);
    expect(scene.groups.map((g) => g.bracket)).toEqual([
      'institutions', 'sell_side', 'event_driven', 'quants', 'degens',
      'narrators', 'algos', 'macro', 'shorts', 'allocators', 'unknown',
    ]);
    expect(scene.groups[0]?.label).toBe('INSTITUTIONS · 18');
    expect(scene.groups.at(-1)?.label).toBe('UNKNOWN · 1');
    expect(scene.nodes.has('whales_01')).toBe(true);
  });
});

describe('layout specifics', () => {
  it('radial rings grow outward in registry order', () => {
    const radii = computeScene(ROSTER, { w: 800, h: 600 }, 'radial').groups.map((g) => g.radius);
    expect(radii).toEqual([...radii].sort((a, b) => a - b));
    expect(new Set(radii).size).toBe(radii.length);
  });

  it('grid puts one bracket per row, members left to right', () => {
    const scene = computeScene(ROSTER, { w: 800, h: 600 }, 'grid');
    const first = scene.nodes.get('institutions_01');
    const second = scene.nodes.get('institutions_02');
    const nextRow = scene.nodes.get('sell_side_01');
    expect(first && second && nextRow).toBeTruthy();
    expect(second?.y).toBe(first?.y);
    expect((second?.x ?? 0) > (first?.x ?? 0)).toBe(true);
    expect((nextRow?.y ?? 0) > (first?.y ?? 0)).toBe(true);
  });

  it('uses the canvas: clusters fill at least 60% of the shorter side', () => {
    const scene = computeScene(ROSTER, { w: 800, h: 600 }, 'clusters');
    const ys = [...scene.nodes.values()].flatMap((n) => [n.y - n.r, n.y + n.r]);
    expect(Math.max(...ys) - Math.min(...ys)).toBeGreaterThan(0.6 * (600 - 2 * BASE_INSET));
  });
});
