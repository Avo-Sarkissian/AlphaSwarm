import { describe, expect, it } from 'vitest';
import { adaptSnapshot } from '../../adapter/frame';
import { parseCycleExport } from '../../data-source/cycleExport';
import { DEMO_RATIONALES_PER_ROUND, exportToFrames } from '../../data-source/exportFrames';
import fixture from '../fixtures/cycle_export.json';

const exp = parseCycleExport(fixture);

describe('exportToFrames', () => {
  it('makes one replay frame per exported round', () => {
    const frames = exportToFrames(exp);
    expect(frames.map((f) => f.round_num)).toEqual([1, 2, 3]);
    expect(frames.every((f) => f.schema_version === 1 && f.mode === 'replay' && f.phase === 'replay')).toBe(true);
    expect(frames.map((f) => f.edges_version)).toEqual([0, 1, 2]);
    expect(frames.every((f) => f.num_rounds === 3 && f.agent_count === exp.roster.length)).toBe(true);
    expect(frames.every((f) => f.cycle_id === exp.cycle.cycle_id && !f.shock_window_open)).toBe(true);
  });

  it('keeps the roster order', () => {
    expect(Object.keys(exportToFrames(exp)[0]?.agent_states ?? {})).toEqual(exp.roster.map((a) => a.id));
  });

  it('lists the most confident decided rationales first, numbered', () => {
    const entries = exportToFrames(exp)[1]?.rationale_entries ?? [];
    expect(entries).toHaveLength(DEMO_RATIONALES_PER_ROUND);
    expect(entries.map((e) => e.seq)).toEqual(Array.from({ length: DEMO_RATIONALES_PER_ROUND }, (_, i) => i + 1));
    expect(entries.every((e) => e.signal !== 'parse_error' && e.round_num === 2 && e.ts === 0)).toBe(true);
    const confidence = new Map((exp.rounds[1]?.decisions ?? []).map((d) => [d.agent_id, d.confidence]));
    const ordered = entries.map((e) => confidence.get(e.agent_id) ?? 0);
    expect([...ordered].sort((a, b) => b - a)).toEqual(ordered);
  });

  it('summarises brackets in roster order over decided agents only', () => {
    const summaries = exportToFrames(exp)[2]?.bracket_summaries ?? [];
    const decisions = exp.rounds[2]?.decisions ?? [];
    const decided = decisions.filter((d) => d.signal !== 'parse_error').length;
    expect(decided).toBeLessThan(decisions.length); // the seeded cycle has failed agents every round
    expect(summaries.reduce((n, b) => n + b.total, 0)).toBe(decided);
    expect(summaries.every((b) => b.total === b.buy_count + b.sell_count + b.hold_count)).toBe(true);
    expect(summaries.map((b) => b.bracket)).toEqual([...new Set(exp.roster.map((a) => a.bracket))]);
  });

  it('applies each shock from the round it was injected before', () => {
    const frames = exportToFrames(exp);
    const shock = exp.shocks[0];
    expect(frames[0]?.applied_shocks).toEqual([]);
    expect(frames[1]?.applied_shocks).toEqual([{ text: shock?.text, round_num: shock?.injected_before_round }]);
  });

  it('is accepted by the frame adapter', () => {
    const view = adaptSnapshot(exportToFrames(exp)[1]);
    expect(view.mode).toBe('replay');
    expect(view.roundNum).toBe(2);
    expect(view.cycleId).toBe(exp.cycle.cycle_id);
    expect(view.agents).toHaveLength(exp.roster.length);
  });
});
