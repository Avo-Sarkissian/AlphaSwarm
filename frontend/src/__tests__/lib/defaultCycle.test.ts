import { describe, expect, it } from 'vitest';
import { defaultCycleId } from '../../lib/defaultCycle';

describe('defaultCycleId', () => {
  it('uses the replayed cycle', () => {
    expect(defaultCycleId({ mode: 'replay', phase: 'replay', cycleId: 'c-replay' }, 'c-latest')).toBe('c-replay');
  });

  it('uses the cycle on screen once it is complete', () => {
    expect(defaultCycleId({ mode: 'live', phase: 'complete', cycleId: 'c-live' }, 'c-latest')).toBe('c-live');
  });

  it('falls back to the newest completed cycle while a run is in progress', () => {
    expect(defaultCycleId({ mode: 'live', phase: 'round_2', cycleId: 'c-live' }, 'c-latest')).toBe('c-latest');
  });

  it('falls back to the newest completed cycle while idle', () => {
    expect(defaultCycleId({ mode: 'idle', phase: 'idle', cycleId: 'c-old' }, 'c-latest')).toBe('c-latest');
  });

  it('returns null when nothing is known', () => {
    expect(defaultCycleId({ mode: 'idle', phase: 'idle', cycleId: null }, null)).toBeNull();
  });
});
