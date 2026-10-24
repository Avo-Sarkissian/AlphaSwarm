import { describe, expect, it } from 'vitest';
import { parseCycleExport } from '../../data-source/cycleExport';
import fixture from '../fixtures/cycle_export.json';

describe('parseCycleExport', () => {
  it('accepts the backend fixture', () => {
    const exp = parseCycleExport(fixture);
    expect(exp.schema).toBe('alphaswarm.cycle-export/1');
    expect(exp.rounds).toHaveLength(3);
  });

  it.each([
    ['a number', 42],
    ['another schema', { ...fixture, schema: 'alphaswarm.cycle-export/2' }],
    ['an empty roster', { ...fixture, roster: [] }],
    ['no rounds', { ...fixture, rounds: [] }],
    ['a round without decisions', { ...fixture, rounds: [{ round_num: 1, citations: [] }] }],
    ['no cycle id', { ...fixture, cycle: { ...fixture.cycle, cycle_id: 7 } }],
    ['no shocks list', { ...fixture, shocks: null }],
  ])('rejects %s', (_label, raw) => {
    expect(() => parseCycleExport(raw)).toThrow(/cycle export/);
  });
});
