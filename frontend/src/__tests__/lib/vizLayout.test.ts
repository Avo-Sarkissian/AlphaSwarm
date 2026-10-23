import { describe, expect, it } from 'vitest';
import {
  clusterRadius,
  layoutForce,
  layoutGrid,
  layoutRadial,
  ringRadius,
  type LayoutAgent,
} from '../../features/dashboard/vizLayout';

const AGENTS: LayoutAgent[] = [
  { id: 'quants_01', bracket: 'quants', index: 0 },
  { id: 'quants_02', bracket: 'quants', index: 1 },
  { id: 'degens_01', bracket: 'degens', index: 2 },
];

function rounded(positions: ReadonlyMap<string, { x: number; y: number }>) {
  const r = (v: number) => Math.round(v * 1e6) / 1e6;
  return Object.fromEntries([...positions].map(([id, p]) => [id, [r(p.x), r(p.y)]]));
}

describe('vizLayout', () => {
  it('keeps the pre-conversion force positions', () => {
    expect(rounded(layoutForce(AGENTS, 800, 600))).toEqual({
      quants_01: [409.8, 84],
      quants_02: [388.172688, 73.200605],
      degens_01: [402.015812, 538.140423],
    });
  });

  it('keeps the pre-conversion radial positions', () => {
    expect(rounded(layoutRadial(AGENTS, 800, 600))).toEqual({
      quants_01: [470, 300],
      quants_02: [330, 300],
      degens_01: [148, 300],
    });
  });

  it('keeps the pre-conversion grid positions and cell sizes', () => {
    const grid = layoutGrid(AGENTS, 800, 600);
    expect(rounded(grid.positions)).toEqual({
      quants_01: [232, 182],
      quants_02: [568, 182],
      degens_01: [232, 418],
    });
    expect(grid.bracketOrder).toEqual(['quants', 'degens']);
    expect([grid.cellW, grid.cellH]).toEqual([336, 236]);
  });

  it('places a single bracket on finite coordinates (early frames)', () => {
    expect(rounded(layoutRadial(AGENTS.slice(0, 1), 800, 600))).toEqual({ quants_01: [470, 300] });
    expect(ringRadius(0, 1, 800, 600)).toBe(70);
  });

  it('returns no positions and finite cells for zero agents', () => {
    const grid = layoutGrid([], 800, 600);
    expect(grid.positions.size).toBe(0);
    expect(Number.isFinite(grid.cellW) && Number.isFinite(grid.cellH)).toBe(true);
    expect(layoutForce([], 800, 600).size).toBe(0);
    expect(layoutRadial([], 800, 600).size).toBe(0);
  });

  it('sizes clusters by group size with a 28px floor', () => {
    expect(clusterRadius(1)).toBe(28);
    expect(clusterRadius(16)).toBe(60);
  });
});
