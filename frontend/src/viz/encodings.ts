// Visual encodings of the influence graph: every channel maps a real quantity,
// and the Legend lists only the channels on screen
// (docs/DECISIONS.md#adr-hero-graph).
import { scaleSqrt } from 'd3-scale';
import type { Edge } from '../api/edges';
import { signalColor } from '../lib/signals';
import type { AgentSignal } from '../types';

/** Edge and ribbon opacity; contrast.test.ts keeps every edge colour >= 3:1 at this opacity. */
export const EDGE_OPACITY = 0.9;
/** Opacity of nodes outside a focused agent's neighbourhood (close to invisible, but still there). */
export const DIM_OPACITY = 0.06;
/** Node radius as a fraction of its slot while no citation edges exist (uniform in R1). */
export const UNIFORM_FRACTION = 0.6;
/** Smallest node once sizes encode citations, as a fraction of the slot. */
export const MIN_FRACTION = 0.35;

export const EDGE_IN = 'var(--edge-in)';
export const EDGE_OUT = 'var(--edge-out)';
export const EDGE_NEUTRAL = 'var(--edge)';

/**
 * Node radius from the number of distinct peers citing the agent in the round
 * on screen (scaleSqrt keeps area proportional). Uniform while nobody is cited.
 */
export function nodeRadiusScale(citedBy: ReadonlyMap<string, number>, slot: number): (id: string) => number {
  const size = slot > 0 ? slot : 0;
  const max = Math.max(0, ...citedBy.values());
  if (max === 0 || size === 0) return () => size * UNIFORM_FRACTION;
  const scale = scaleSqrt().domain([0, max]).range([size * MIN_FRACTION, size]).clamp(true);
  return (id) => scale(citedBy.get(id) ?? 0);
}

/** Ribbon stroke width from its citation count. */
export function ribbonWidthScale(maxCount: number): (count: number) => number {
  const scale = scaleSqrt().domain([0, Math.max(1, maxCount)]).range([0, 9]).clamp(true);
  return (count) => Math.max(1.5, scale(count));
}

/** Agent-edge width from Edge.weight; constant when every weight is the same. */
export function edgeWidthScale(edges: readonly Edge[]): { width: (weight: number) => number; varies: boolean } {
  const weights = edges.map((e) => e.weight).filter(Number.isFinite);
  const lo = Math.min(...weights);
  const hi = Math.max(...weights);
  if (weights.length === 0 || hi - lo < 1e-9) return { width: () => 1.4, varies: false };
  const scale = scaleSqrt().domain([lo, hi]).range([1, 2.6]).clamp(true);
  return { width: (weight) => scale(weight), varies: true };
}

/** "All edges" colour: the citing agent's signal; neutral while it is still deciding. */
export function citerColor(signal: AgentSignal | null): string {
  return signal === null ? EDGE_NEUTRAL : signalColor(signal);
}
