// Honest encodings: size = peers citing the agent, uniform while nobody is
// cited; widths follow citation counts and weights.
import { describe, expect, it } from 'vitest';
import type { Edge } from '../../api/edges';
import {
  citerColor,
  DIM_OPACITY,
  EDGE_IN,
  EDGE_NEUTRAL,
  EDGE_OPACITY,
  EDGE_OUT,
  edgeWidthScale,
  MIN_FRACTION,
  nodeRadiusScale,
  ribbonWidthScale,
  UNIFORM_FRACTION,
} from '../../viz/encodings';

const e = (weight: number): Edge => ({ source_id: 'quants_01', target_id: 'macro_01', weight });

describe('nodeRadiusScale', () => {
  it('draws every node the same size while nobody is cited (live R1)', () => {
    const radius = nodeRadiusScale(new Map(), 10);
    expect(radius('quants_01')).toBe(10 * UNIFORM_FRACTION);
    expect(radius('sell_side_03')).toBe(10 * UNIFORM_FRACTION);
  });

  it('grows with the square root of citations and fills the slot at the maximum', () => {
    const radius = nodeRadiusScale(new Map([['sell_side_03', 16], ['quants_01', 4]]), 10);
    expect(radius('sell_side_03')).toBe(10);
    expect(radius('nobody_01')).toBe(10 * MIN_FRACTION);
    const quarter = radius('quants_01');
    expect(quarter).toBeCloseTo(10 * MIN_FRACTION + (10 - 10 * MIN_FRACTION) * 0.5, 6);
  });

  it('never returns NaN for a zero or invalid slot', () => {
    expect(nodeRadiusScale(new Map([['a', 1]]), 0)('a')).toBe(0);
    expect(nodeRadiusScale(new Map([['a', 1]]), Number.NaN)('a')).toBe(0);
  });
});

describe('ribbonWidthScale', () => {
  it('keeps single citations visible and caps the widest ribbon', () => {
    const width = ribbonWidthScale(25);
    expect(width(1)).toBe(1.8);
    expect(width(25)).toBe(9);
    expect(width(100)).toBe(9);
  });
});

describe('edgeWidthScale', () => {
  it('is constant when every weight is equal', () => {
    const { width, varies } = edgeWidthScale([e(0.01), e(0.01)]);
    expect(varies).toBe(false);
    expect(width(0.01)).toBe(1.4);
  });

  it('maps the weight range onto 1..2.6 px', () => {
    const { width, varies } = edgeWidthScale([e(0.01), e(0.04)]);
    expect(varies).toBe(true);
    expect(width(0.01)).toBe(1);
    expect(width(0.04)).toBe(2.6);
  });

  it('handles no edges', () => {
    expect(edgeWidthScale([]).varies).toBe(false);
  });
});

describe('citerColor', () => {
  it('uses the citing agent signal, neutral while it is deciding', () => {
    expect(citerColor('buy')).toBe('var(--buy)');
    expect(citerColor(null)).toBe(EDGE_NEUTRAL);
  });
});

describe('graph colour tokens', () => {
  it('draws ego edges in two distinct CSS tokens and dims far below the edge opacity', () => {
    expect([EDGE_IN, EDGE_OUT, EDGE_NEUTRAL]).toEqual(['var(--edge-in)', 'var(--edge-out)', 'var(--edge)']);
    expect(DIM_OPACITY).toBeLessThan(EDGE_OPACITY / 10);
  });
});
