// Header label for every backend SimulationPhase value. The round comes from
// the frame (useRound), never from parsing the phase string.
import { describe, expect, it } from 'vitest';
import { adaptSnapshot } from '../../adapter/frame';
import { phaseLabelFor } from '../../lib/phase';

describe('phaseLabelFor', () => {
  it('labels the real seeding phase as SEEDING', () => {
    expect(phaseLabelFor('seeding', null, 3)).toBe('SEEDING');
    expect(phaseLabelFor('initializing', null, 3)).toBe('SEEDING');
  });

  it('labels rounds against num_rounds', () => {
    expect(phaseLabelFor('round_2', 2, 3)).toBe('ROUND 2/3');
    expect(phaseLabelFor('round_2', 2, 2)).toBe('ROUND 2/2');
  });

  it('falls back to the round in the phase string when the frame has none', () => {
    expect(phaseLabelFor('round_1', null, 3)).toBe('ROUND 1/3');
  });

  it('labels replay with the replayed round instead of R1', () => {
    expect(phaseLabelFor('replay', 2, 3)).toBe('REPLAY · R2/3');
    expect(phaseLabelFor('replay', null, 3)).toBe('REPLAY');
  });

  it('keeps the finalizing, complete and idle labels', () => {
    expect(phaseLabelFor('finalizing', 3, 3)).toBe('FINALIZING');
    expect(phaseLabelFor('complete', 3, 3)).toBe('COMPLETE');
    expect(phaseLabelFor('idle', null, 3)).toBe('IDLE');
  });

  it('upper-cases an unknown phase instead of inventing a round', () => {
    expect(phaseLabelFor('warming_up', null, 3)).toBe('WARMING_UP');
  });
});

describe('adaptSnapshot', () => {
  it('treats finalizing as a running phase', () => {
    expect(adaptSnapshot({ phase: 'finalizing', round_num: 3 }).running).toBe(true);
  });
});
