// @vitest-environment happy-dom
import { cleanup, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { roundsFor, useRound, useRounds } from '../../hooks/useRounds';
import { makeMeta } from '../helpers/frameMeta';

const h = vi.hoisted(() => ({ meta: null as unknown }));
vi.mock('../../context/FrameMetaContext', () => ({ useFrameMeta: () => h.meta }));

afterEach(cleanup);

describe('roundsFor', () => {
  it('lists the rounds of a 2-round run', () => {
    expect(roundsFor(2, 1)).toEqual({ numRounds: 2, rounds: [1, 2], finalRound: 2, currentRound: 1 });
  });

  it('falls back to the default depth only while num_rounds is unknown', () => {
    expect(roundsFor(0, null).numRounds).toBe(3);
  });

  it('has no current round before round 1', () => {
    expect(roundsFor(3, 0).currentRound).toBeNull();
  });

  it('clamps a round past num_rounds', () => {
    expect(roundsFor(2, 3).currentRound).toBe(2);
  });
});

describe('useRounds / useRound', () => {
  it('reads the replayed round from the frame, not the phase string', () => {
    h.meta = makeMeta({ mode: 'replay', phase: 'replay', roundNum: 2, numRounds: 3 });
    expect(renderHook(() => useRound()).result.current).toBe(2);
  });

  it('drives a 2-round run', () => {
    h.meta = makeMeta({ numRounds: 2, roundNum: 2 });
    const { result } = renderHook(() => useRounds());
    expect(result.current.rounds).toEqual([1, 2]);
    expect(result.current.finalRound).toBe(2);
  });
});
