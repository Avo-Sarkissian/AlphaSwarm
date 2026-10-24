// The legend lists exactly the encodings on screen, per layout.
import { describe, expect, it } from 'vitest';
import { legendItems, type LegendInput } from '../../viz/legendItems';

const ALL_SIGNALS: LegendInput['signals'] = new Set(['buy', 'sell', 'hold', 'parse_error', 'pending']);
const base: LegendInput = {
  layout: 'clusters',
  edgeMode: 'ribbons',
  signals: ALL_SIGNALS,
  sized: true,
  weighted: false,
  flips: false,
  withinCount: 0,
  hint: false,
};
const keys = (input: Partial<LegendInput>) => legendItems({ ...base, ...input }).map((i) => i.key);

describe('legendItems per layout', () => {
  it('clusters overview: signals, size, ribbons', () => {
    expect(keys({})).toEqual(['buy', 'sell', 'hold', 'failed', 'pending', 'size', 'ribbon']);
  });

  it('clusters with All edges: agent arrows and, when weights differ, widths', () => {
    expect(keys({ edgeMode: 'agents', weighted: true })).toEqual([
      'buy', 'sell', 'hold', 'failed', 'pending', 'size', 'agent-edge', 'edge-weight',
    ]);
  });

  it('radial overview: no edge rows, a hint instead', () => {
    expect(keys({ layout: 'radial', edgeMode: 'none', hint: true })).toEqual([
      'buy', 'sell', 'hold', 'failed', 'pending', 'size', 'hint',
    ]);
  });

  it('grid: never a size or edge row; focus shows the two outline colours', () => {
    expect(keys({ layout: 'grid', edgeMode: 'none' })).toEqual(['buy', 'sell', 'hold', 'failed', 'pending']);
    expect(keys({ layout: 'grid', edgeMode: 'ego' })).toEqual([
      'buy', 'sell', 'hold', 'failed', 'pending', 'ego-in', 'ego-out',
    ]);
  });

  it('round 1: no size row while nobody is cited, only the signals present', () => {
    expect(keys({ sized: false, edgeMode: 'none', signals: new Set(['pending', 'buy']) })).toEqual(['buy', 'pending']);
  });

  it('adds flips and the within-bracket count only when they exist', () => {
    const items = legendItems({ ...base, flips: true, withinCount: 14 });
    expect(items.map((i) => i.key)).toContain('flip');
    expect(items.find((i) => i.key === 'within')?.label).toBe('14 citations inside a bracket (not drawn)');
  });
});
