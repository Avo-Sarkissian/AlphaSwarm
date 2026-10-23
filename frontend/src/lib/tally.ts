// Signal counts over the live agent list. Pending agents (signal
// null, still thinking this round) and failed agents (parse_error) are never
// counted as HOLD; percentages use decided agents (buy + sell + hold) only
// (docs/DECISIONS.md#adr-streaming-state).
import type { AgentView } from '../types';

export interface SignalTally {
  buy: number;
  sell: number;
  hold: number;
  parseError: number;
  thinking: number;
  resolved: number;
  decided: number;
}

export function tallySignals(agents: readonly AgentView[]): SignalTally {
  const t = { buy: 0, sell: 0, hold: 0, parseError: 0, thinking: 0 };
  for (const a of agents) {
    if (a.signal === null) t.thinking += 1;
    else if (a.signal === 'parse_error') t.parseError += 1;
    else t[a.signal] += 1;
  }
  const decided = t.buy + t.sell + t.hold;
  return { ...t, decided, resolved: decided + t.parseError };
}

export type DecidedSignal = 'buy' | 'sell' | 'hold';

export interface ConsensusLeader {
  signal: DecidedSignal | null;
  pct: number;
}

/** Plurality among decided agents; ties resolve buy > sell > hold (unchanged UI rule). */
export function consensusLeader(t: SignalTally): ConsensusLeader {
  if (t.decided === 0) return { signal: null, pct: 0 };
  const signal: DecidedSignal =
    t.buy >= t.sell && t.buy >= t.hold ? 'buy' : t.sell >= t.hold ? 'sell' : 'hold';
  return { signal, pct: Math.round((t[signal] / t.decided) * 100) };
}

export interface BracketTally {
  bracket: string;
  display: string;
  total: number;
  tally: SignalTally;
}

/** Live per-bracket tallies in roster order, keyed by the snake_case bracket value. */
export function bracketTallies(agents: readonly AgentView[]): BracketTally[] {
  const groups = new Map<string, { display: string; members: AgentView[] }>();
  for (const a of agents) {
    const key = a.bracket;
    const group = groups.get(key) ?? { display: a.bracketDisplay, members: [] };
    group.members.push(a);
    groups.set(key, group);
  }
  return [...groups.entries()].map(([bracket, g]) => ({
    bracket,
    display: g.display,
    total: g.members.length,
    tally: tallySignals(g.members),
  }));
}
