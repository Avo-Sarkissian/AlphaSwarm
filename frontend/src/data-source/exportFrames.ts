// One replay frame per round of a CycleExport, in the wire shape the backend
// broadcaster sends, so the static demo runs the real adapter and UI
// (docs/DECISIONS.md#adr-cycle-export).
import { toWireSignal } from '../lib/wireSignal';
import type {
  WireAgentState,
  WireBracketSummary,
  WireJobStatus,
  WireRationaleEntry,
  WireStateFrame,
} from '../types';
import type { CycleExport, ExportDecision } from './cycleExport';

export const DEMO_RATIONALES_PER_ROUND = 10;

const IDLE_JOB: WireJobStatus = { state: 'idle', cycle_id: null, error_code: null };

function isDecided(d: ExportDecision): boolean {
  return d.signal === 'buy' || d.signal === 'sell' || d.signal === 'hold';
}

function topRationales(decisions: readonly ExportDecision[], roundNum: number): WireRationaleEntry[] {
  return decisions
    .filter(isDecided)
    .sort((a, b) => b.confidence - a.confidence || a.agent_id.localeCompare(b.agent_id))
    .slice(0, DEMO_RATIONALES_PER_ROUND)
    .map((d, i) => ({
      seq: i + 1,
      ts: 0,
      agent_id: d.agent_id,
      signal: toWireSignal(d.signal) ?? 'hold',
      rationale: d.rationale,
      round_num: roundNum,
    }));
}

function bracketSummaries(
  decisions: readonly ExportDecision[],
  bracketOf: ReadonlyMap<string, string>,
  brackets: readonly string[],
  displayOf: ReadonlyMap<string, string>,
): WireBracketSummary[] {
  return brackets.flatMap((bracket) => {
    const members = decisions.filter((d) => bracketOf.get(d.agent_id) === bracket);
    if (members.length === 0) return [];
    const decided = members.filter(isDecided);
    const count = (signal: string) => decided.filter((d) => d.signal === signal).length;
    const mean = (pick: (d: ExportDecision) => number) =>
      decided.length === 0 ? 0 : decided.reduce((sum, d) => sum + pick(d), 0) / decided.length;
    return [
      {
        bracket,
        display_name: displayOf.get(bracket) ?? bracket,
        buy_count: count('buy'),
        sell_count: count('sell'),
        hold_count: count('hold'),
        total: decided.length,
        avg_confidence: mean((d) => d.confidence),
        avg_sentiment: mean((d) => d.sentiment),
      },
    ];
  });
}

export function exportToFrames(exp: CycleExport): WireStateFrame[] {
  const order = new Map(exp.roster.map((a, i) => [a.id, i] as const));
  const bracketOf = new Map(exp.roster.map((a) => [a.id, a.bracket] as const));
  const displayOf = new Map(exp.roster.map((a) => [a.bracket, a.display_name] as const));
  const brackets = [...new Set(exp.roster.map((a) => a.bracket))];
  const rank = (id: string) => order.get(id) ?? Number.MAX_SAFE_INTEGER;
  return exp.rounds.map((round): WireStateFrame => {
    const decisions = [...round.decisions].sort((a, b) => rank(a.agent_id) - rank(b.agent_id) || a.agent_id.localeCompare(b.agent_id));
    const agentStates: Record<string, WireAgentState> = {};
    for (const d of decisions) agentStates[d.agent_id] = { signal: toWireSignal(d.signal) ?? 'parse_error', confidence: d.confidence };
    return {
      schema_version: 1,
      mode: 'replay',
      phase: 'replay',
      cycle_id: exp.cycle.cycle_id,
      num_rounds: exp.rounds.length,
      round_num: round.round_num,
      agent_count: exp.roster.length,
      agent_states: agentStates,
      elapsed_seconds: 0,
      governor_metrics: {
        current_slots: 0,
        active_count: 0,
        pressure_level: 'green',
        memory_percent: 0,
        governor_state: 'idle',
        timestamp: 0,
      },
      tps: 0,
      rationale_entries: topRationales(decisions, round.round_num),
      bracket_summaries: bracketSummaries(decisions, bracketOf, brackets, displayOf),
      data_source_audit: [],
      edges_version: Math.max(0, round.round_num - 1),
      jobs: { advisory: IDLE_JOB, report: IDLE_JOB },
      last_error: null,
      pending_shock: null,
      applied_shocks: exp.shocks
        .filter((s) => s.injected_before_round <= round.round_num)
        .map((s) => ({ text: s.text, round_num: s.injected_before_round })),
      shock_window_open: false,
    };
  });
}
