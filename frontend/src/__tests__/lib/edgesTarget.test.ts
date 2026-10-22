import { describe, expect, it } from 'vitest';
import { edgesTarget } from '../../lib/edgesTarget';
import { makeMeta, TEST_CYCLE_ID } from '../helpers/frameMeta';

describe('edgesTarget', () => {
  it.each([
    ['an idle frame', makeMeta({ mode: 'idle', phase: 'idle', edgesVersion: 2 })],
    ['live seeding', makeMeta({ phase: 'seeding', roundNum: 0, edgesVersion: 0 })],
    ['live round 2 before its edges are written', makeMeta({ phase: 'round_2', roundNum: 2 })],
    ['replay round 1 (round 1 has no citations)', makeMeta({ mode: 'replay', phase: 'replay', roundNum: 1 })],
    ['a frame without a cycle id', makeMeta({ cycleId: null, edgesVersion: 1 })],
  ])('returns null for %s', (_label, meta) => {
    expect(edgesTarget(meta)).toBeNull();
  });

  it('shows round 2 edges during live round 3 (edges_version 1)', () => {
    const meta = makeMeta({ phase: 'round_3', roundNum: 3, edgesVersion: 1 });
    expect(edgesTarget(meta)).toEqual({ cycleId: TEST_CYCLE_ID, round: 2 });
  });

  it('shows the final round once its edges exist in a 3-round run', () => {
    const meta = makeMeta({ phase: 'complete', roundNum: 3, edgesVersion: 2 });
    expect(edgesTarget(meta)).toEqual({ cycleId: TEST_CYCLE_ID, round: 3 });
  });

  it('shows the final round of a 2-round run, never a literal 3', () => {
    const meta = makeMeta({ phase: 'complete', roundNum: 2, numRounds: 2, edgesVersion: 1 });
    expect(edgesTarget(meta)).toEqual({ cycleId: TEST_CYCLE_ID, round: 2 });
  });

  it('uses the replayed round in replay', () => {
    const meta = makeMeta({ mode: 'replay', phase: 'replay', roundNum: 3, edgesVersion: 2 });
    expect(edgesTarget(meta)).toEqual({ cycleId: TEST_CYCLE_ID, round: 3 });
  });

  it('never targets a round past num_rounds', () => {
    const meta = makeMeta({ phase: 'complete', numRounds: 2, edgesVersion: 4 });
    expect(edgesTarget(meta)).toEqual({ cycleId: TEST_CYCLE_ID, round: 2 });
  });
});
