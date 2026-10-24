// The agents of the current frame with real flip marks: compared with the
// remembered previous round of the same cycle (lib/flips.ts).
import { useEffect, useMemo } from 'react';
import { markFlips, recallRound, rememberRound } from '../lib/flips';
import type { AgentView, StateFrame } from '../types';

export function useFlipMarkedAgents(frame: Pick<StateFrame, 'agents' | 'cycleId' | 'roundNum'>): AgentView[] {
  const { agents, cycleId, roundNum } = frame;
  const previous =
    cycleId !== null && roundNum !== null && roundNum > 1 ? recallRound(cycleId, roundNum - 1) : undefined;
  const marked = useMemo(() => markFlips(agents, previous), [agents, previous]);
  useEffect(() => {
    if (cycleId !== null && roundNum !== null && roundNum >= 1) rememberRound(cycleId, roundNum, agents);
  }, [cycleId, roundNum, agents]);
  return marked;
}
