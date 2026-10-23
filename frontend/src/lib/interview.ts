import type { AgentDecisionRow } from '../api/agents';
import type { AgentSignal } from '../types';

export type TrajectorySource = 'stored' | 'live' | 'missing';

export interface TrajectoryPoint {
  round: number;
  signal: AgentSignal | null;
  confidence: number | null;
  rationale: string | null;
  source: TrajectorySource;
}

export interface LiveAgentState {
  roundNum: number | null;
  signal: AgentSignal | null;
  confidence: number;
}

const SIGNALS: readonly string[] = ['buy', 'sell', 'hold', 'parse_error'];
const asSignal = (value: string): AgentSignal | null => (SIGNALS.includes(value) ? (value as AgentSignal) : null);

/** One point per round: the stored decision, else the live signal for the round in progress, else missing. */
export function mergeTrajectory(
  rounds: readonly number[],
  stored: readonly AgentDecisionRow[],
  live: LiveAgentState | null,
): TrajectoryPoint[] {
  const byRound = new Map(stored.map((d) => [d.round_num, d]));
  return rounds.map((round): TrajectoryPoint => {
    const d = byRound.get(round);
    if (d) return { round, signal: asSignal(d.signal), confidence: d.confidence, rationale: d.rationale, source: 'stored' };
    if (live && live.roundNum === round && live.signal !== null) {
      return { round, signal: live.signal, confidence: live.confidence, rationale: null, source: 'live' };
    }
    return { round, signal: null, confidence: null, rationale: null, source: 'missing' };
  });
}

/** True when the first and last decided (buy/sell/hold) points differ. */
export function didFlip(points: readonly TrajectoryPoint[]): boolean {
  const decided = points
    .map((p) => p.signal)
    .filter((s): s is 'buy' | 'sell' | 'hold' => s === 'buy' || s === 'sell' || s === 'hold');
  return decided.length >= 2 && decided[0] !== decided[decided.length - 1];
}

export interface OpeningLineInput {
  display: string;
  phase: string;
  roundNum: number | null;
  numRounds: number;
  signal: AgentSignal | null;
  confidence: number;
}

export function openingLine(i: OpeningLineInput): string {
  const tail = 'Ask me about my reasoning.';
  if (i.signal === null) return `${i.display}. Round ${i.roundNum ?? 1} is in progress and I have not decided yet. ${tail}`;
  const position = `${i.signal.toUpperCase()}, confidence ${Math.round(i.confidence * 100)}%`;
  if (i.phase === 'complete') return `${i.display}. Final round (R${i.numRounds}) close: ${position}. ${tail}`;
  if (i.phase === 'replay') return `${i.display}. Replaying round ${i.roundNum ?? 1} of ${i.numRounds}: ${position}. ${tail}`;
  if (i.roundNum !== null && i.roundNum >= 1) return `${i.display}. Round ${i.roundNum} of ${i.numRounds} so far: ${position}. ${tail}`;
  return `${i.display}. Last recorded position: ${position}. ${tail}`;
}

/** The interview targets the cycle on screen (live or replay), else the latest complete one. */
export function resolveInterviewCycle(frameCycleId: string | null, latestCompleted: string | null): string | null {
  return frameCycleId ?? latestCompleted;
}
