// Edge geometry, bracket aggregation and the ego network.
import { describe, expect, it } from 'vitest';
import type { Edge } from '../../api/edges';
import { bracketOf } from '../../data';
import { aggregateByBracket, curvedPath, egoNetwork, MATRIX_KEYS } from '../../viz/edges';

const e = (source_id: string, target_id: string, weight = 0.01): Edge => ({ source_id, target_id, weight });
const A = { x: 100, y: 100 };
const B = { x: 300, y: 100 };

/** Parse "M sx,sy Q cx,cy ex,ey" into numbers. */
function parts(path: string) {
  const n = path.match(/-?\d+(?:\.\d+)?/g)?.map(Number) ?? [];
  return { start: [n[0], n[1]], control: [n[2], n[3]], end: [n[4], n[5]] };
}

describe('curvedPath', () => {
  it('gives A->B and B->A different curves', () => {
    expect(curvedPath(A, B)).not.toBe(curvedPath(B, A));
  });

  it('bows the two directions to opposite sides of the chord', () => {
    const ab = parts(curvedPath(A, B)).control[1] ?? 0;
    const ba = parts(curvedPath(B, A)).control[1] ?? 0;
    expect(Math.sign(ab - A.y)).toBe(-Math.sign(ba - A.y));
    expect(Math.abs(ab - A.y)).toBeCloseTo(40, 6); // min(48, 20% of 200)
  });

  it('honours an explicit offset', () => {
    expect(parts(curvedPath(A, B, { offset: 10 })).control).toEqual([200, 110]);
  });

  it('pulls the end back by the requested distance', () => {
    const { end } = parts(curvedPath(A, B, { offset: 0, pullback: 12 }));
    expect(end).toEqual([288, 100]);
  });

  it('never pulls back past the middle of a short edge', () => {
    const { end } = parts(curvedPath(A, { x: 110, y: 100 }, { offset: 0, pullback: 50 }));
    expect(end[0]).toBeGreaterThan(104);
  });

  it('degrades to a move-to for coincident or non-finite points', () => {
    expect(curvedPath(A, A)).toBe('M100,100');
    expect(curvedPath(A, { x: Number.NaN, y: 0 })).toBe('M100,100');
  });
});

describe('aggregateByBracket', () => {
  const edges = [
    e('quants_01', 'sell_side_03'), // sell_side -> quants
    e('quants_02', 'sell_side_03'), // sell_side -> quants
    e('sell_side_01', 'quants_01'), // quants -> sell_side
    e('macro_02', 'macro_01'), //      macro -> macro (within)
    e('whales_01', 'degens_04'), //    degens -> unknown
  ];
  const m = aggregateByBracket(edges, bracketOf);

  it('totals equal the edge count', () => {
    const sum = m.counts.flat().reduce((a, b) => a + b, 0);
    expect(sum).toBe(edges.length);
    expect(m.total).toBe(edges.length);
  });

  it('counts from the cited bracket to the citing bracket', () => {
    const at = (from: string, to: string) =>
      m.counts[MATRIX_KEYS.indexOf(from as never)]?.[MATRIX_KEYS.indexOf(to as never)];
    expect(at('sell_side', 'quants')).toBe(2);
    expect(at('quants', 'sell_side')).toBe(1);
    expect(at('degens', 'unknown')).toBe(1);
  });

  it('lists off-diagonal ribbons largest first and keeps the diagonal apart', () => {
    expect(m.cells).toEqual([
      { from: 'sell_side', to: 'quants', count: 2 },
      { from: 'quants', to: 'sell_side', count: 1 },
      { from: 'degens', to: 'unknown', count: 1 },
    ]);
    expect([...m.within]).toEqual([['macro', 1]]);
  });

  it('has at most 110 ribbons for any input (11 x 10 off-diagonal cells)', () => {
    expect(MATRIX_KEYS).toHaveLength(11);
    expect(aggregateByBracket([], bracketOf).cells).toEqual([]);
  });
});

describe('egoNetwork', () => {
  const edges = [
    e('quants_01', 'sell_side_03'), // quants_01 cited sell_side_03
    e('degens_02', 'quants_01'), //    degens_02 cited quants_01
    e('macro_01', 'quants_01'), //     macro_01 cited quants_01
    e('quants_01', 'quants_01'), //    self-citation: ignored
    e('algos_01', 'shorts_02'), //     unrelated
  ];

  it('splits who the agent cited (incoming arrows) from who cited it (outgoing)', () => {
    const ego = egoNetwork('quants_01', edges);
    expect(ego.incoming.map((x) => x.target_id)).toEqual(['sell_side_03']);
    expect(ego.outgoing.map((x) => x.source_id)).toEqual(['degens_02', 'macro_01']);
    expect([...ego.neighbors].sort()).toEqual(['degens_02', 'macro_01', 'sell_side_03']);
  });

  it('is empty for an agent with no citations and ignores self-citations', () => {
    const ego = egoNetwork('narrators_01', edges);
    expect(ego.incoming).toEqual([]);
    expect(ego.outgoing).toEqual([]);
    expect(ego.neighbors.size).toBe(0);
    expect(egoNetwork('quants_01', [e('quants_01', 'quants_01')]).neighbors.size).toBe(0);
  });
});
