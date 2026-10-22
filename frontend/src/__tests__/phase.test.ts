// Header round and label for every backend SimulationPhase value, including
// 'finalizing', which must not fall back to round 1.
import { describe, expect, it } from 'vitest';
import { adaptSnapshot } from '../adapter/frame';
import { phaseLabelFor, roundFromPhase } from '../lib/phase';

describe('roundFromPhase', () => {
  it('reads round_N', () => {
    expect(roundFromPhase('round_1')).toBe(1);
    expect(roundFromPhase('round_2')).toBe(2);
  });
  it('keeps the last round while finalizing and when complete', () => {
    expect(roundFromPhase('finalizing')).toBe(3);
    expect(roundFromPhase('complete')).toBe(3);
  });
  it('falls back to 1 before the first round', () => {
    expect(roundFromPhase('idle')).toBe(1);
    expect(roundFromPhase('seeding')).toBe(1);
  });
});

describe('phaseLabelFor', () => {
  it('labels finalizing', () => {
    expect(phaseLabelFor('finalizing', 3)).toBe('FINALIZING');
  });
  it('keeps the existing labels', () => {
    expect(phaseLabelFor('complete', 3)).toBe('COMPLETE');
    expect(phaseLabelFor('idle', 1)).toBe('IDLE');
    expect(phaseLabelFor('initializing', 1)).toBe('SEEDING');
    expect(phaseLabelFor('round_2', 2)).toBe('ROUND_2');
    expect(phaseLabelFor('replay', 2)).toBe('ROUND 2/3');
  });
});

describe('adaptSnapshot', () => {
  it('treats finalizing as a running phase', () => {
    // The run is not over until COMPLETE.
    expect(adaptSnapshot({ phase: 'finalizing', round_num: 3 }).running).toBe(true);
  });
});
