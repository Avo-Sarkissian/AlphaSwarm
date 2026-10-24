// Flip detection in the browser. Frames carry one round at a time, so the
// signals of each round seen are remembered per cycle; an agent flipped in
// round r when its decided signal differs from round r-1's. A round never seen
// (a jump from R1 to R3) yields no flips rather than a wrong comparison
// (docs/DECISIONS.md#adr-replaystore-separate).
import type { AgentSignal, AgentView, DecidedSignal } from '../types';

export const ROUND_MEMORY_CYCLES = 4;

const memory = new Map<string, Map<number, ReadonlyMap<string, DecidedSignal>>>();

function isDecided(signal: AgentSignal | null | undefined): signal is DecidedSignal {
  return signal === 'buy' || signal === 'sell' || signal === 'hold';
}

function sameSignals(a: ReadonlyMap<string, DecidedSignal>, b: ReadonlyMap<string, DecidedSignal>): boolean {
  if (a.size !== b.size) return false;
  for (const [id, signal] of a) if (b.get(id) !== signal) return false;
  return true;
}

export function rememberRound(cycleId: string, round: number, agents: readonly AgentView[]): void {
  const signals = new Map<string, DecidedSignal>();
  for (const agent of agents) if (isDecided(agent.signal)) signals.set(agent.id, agent.signal);
  let rounds = memory.get(cycleId);
  if (rounds === undefined) {
    rounds = new Map();
    memory.set(cycleId, rounds);
    while (memory.size > ROUND_MEMORY_CYCLES) {
      const oldest = memory.keys().next().value;
      if (oldest === undefined) break;
      memory.delete(oldest);
    }
  }
  const before = rounds.get(round);
  if (before !== undefined && sameSignals(before, signals)) return;
  rounds.set(round, signals);
}

export function recallRound(cycleId: string, round: number): ReadonlyMap<string, DecidedSignal> | undefined {
  return memory.get(cycleId)?.get(round);
}

/** Tests only. */
export function forgetRounds(): void {
  memory.clear();
}

export function markFlips(
  agents: AgentView[],
  previous: ReadonlyMap<string, DecidedSignal> | undefined,
): AgentView[] {
  if (previous === undefined || previous.size === 0) return agents;
  let changed = false;
  const marked = agents.map((agent) => {
    const before = previous.get(agent.id);
    if (before !== undefined && isDecided(agent.signal) && agent.signal !== before) {
      changed = true;
      return { ...agent, flipped: 1 as const, flippedFrom: before };
    }
    return agent;
  });
  return changed ? marked : agents;
}
