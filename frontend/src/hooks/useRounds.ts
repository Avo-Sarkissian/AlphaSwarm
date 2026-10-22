// Round structure of the run on screen, from the frame's num_rounds and
// round_num, so labels, tabs, progress and trajectories never
// assume three rounds (docs/DECISIONS.md#adr-num-rounds).
import { useMemo } from 'react';
import { useFrameMeta } from '../context/FrameMetaContext';

/** Configured default depth; used only while a frame carries no valid num_rounds. */
const DEFAULT_NUM_ROUNDS = 3;

export interface Rounds {
  numRounds: number;
  rounds: number[];
  finalRound: number;
  currentRound: number | null;
}

export function roundsFor(numRounds: number, roundNum: number | null): Rounds {
  const n = Number.isInteger(numRounds) && numRounds >= 1 ? numRounds : DEFAULT_NUM_ROUNDS;
  const current = typeof roundNum === 'number' && roundNum >= 1 ? Math.min(roundNum, n) : null;
  return {
    numRounds: n,
    rounds: Array.from({ length: n }, (_, i) => i + 1),
    finalRound: n,
    currentRound: current,
  };
}

export function useRounds(): Rounds {
  const { numRounds, roundNum } = useFrameMeta();
  return useMemo(() => roundsFor(numRounds, roundNum), [numRounds, roundNum]);
}

/** The round on screen (live or replayed); null before round 1. */
export function useRound(): number | null {
  return useRounds().currentRound;
}
