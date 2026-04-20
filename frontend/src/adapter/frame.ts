import type {
  AgentView,
  BracketKey,
  BracketSummaryView,
  RationaleView,
  StateFrame,
  TelemetrySlice,
} from '../types';
import { agentIdToBracket } from './agentId';

// Defensive: every field access uses ?. + fallback. Backend shape:
//   { phase, round_num, agent_count, agent_states, elapsed_seconds,
//     governor_metrics:{memory_percent,current_slots?}, tps,
//     rationale_entries[], bracket_summaries[] }
// There is NO top-level cycle_id on the snapshot; EdgesContext fills it later.
export function adaptSnapshot(raw: unknown): StateFrame {
  const r = (raw ?? {}) as Record<string, unknown>;

  const phase = typeof r.phase === 'string' ? r.phase : 'idle';
  const running =
    phase !== 'complete' && phase !== 'initializing' && phase !== 'idle';

  const roundNumRaw = r.round_num;
  const roundNum =
    typeof roundNumRaw === 'number' && Number.isFinite(roundNumRaw)
      ? roundNumRaw
      : null;

  const gov = (r.governor_metrics ?? {}) as Record<string, unknown>;
  const memPct = typeof gov.memory_percent === 'number' ? gov.memory_percent : 0;
  const slotsUsed =
    typeof gov.current_slots === 'number' ? gov.current_slots : 0; // KR-41.1-05

  const telemetry: TelemetrySlice = {
    memMb: memPct, // KR-41.1-04: percent, not MB
    slotsUsed, // KR-41.1-05
    slotsMax: 8, // KR-41.1-05: stubbed
    tps: typeof r.tps === 'number' ? r.tps : 0,
    ts: Date.now(),
    elapsedSeconds:
      typeof r.elapsed_seconds === 'number' ? r.elapsed_seconds : 0,
  };

  const agentStates = (r.agent_states ?? {}) as Record<string, unknown>;
  const agents: AgentView[] = Object.entries(agentStates).map(
    ([id, rawState]) => {
      const s = (rawState ?? {}) as Record<string, unknown>;
      const confidence =
        typeof s.confidence === 'number' ? s.confidence : 0;
      return {
        id,
        bracket: agentIdToBracket(id),
        confidence,
        flipped: 0, // KR-41.1-03
        roundLastSpoke: null, // KR-41.1-03
        thinking: false, // KR-41.1-03
      };
    },
  );

  const bracketRaw = Array.isArray(r.bracket_summaries)
    ? (r.bracket_summaries as unknown[])
    : [];
  const bracketSummaries: BracketSummaryView[] = bracketRaw.map((b) => {
    const bs = (b ?? {}) as Record<string, unknown>;
    const bracket =
      typeof bs.bracket === 'string' ? (bs.bracket as BracketKey) : 'Quants';
    return {
      bracket,
      consensusSignal:
        typeof bs.consensus_signal === 'number' ? bs.consensus_signal : 0,
      agentCount:
        typeof bs.agent_count === 'number' ? bs.agent_count : 0,
    };
  });

  const ratRaw = Array.isArray(r.rationale_entries)
    ? (r.rationale_entries as unknown[])
    : [];
  const rationales: RationaleView[] = ratRaw.map((e) => {
    const re = (e ?? {}) as Record<string, unknown>;
    return {
      agentId: typeof re.agent_id === 'string' ? re.agent_id : '',
      round: typeof re.round === 'number' ? re.round : (roundNum ?? 0),
      text: typeof re.text === 'string' ? re.text : '',
      citations: [], // KR-41.1-10
      sources: [], // KR-41.1-10
      ts: typeof re.ts === 'number' ? re.ts : Date.now(),
    };
  });

  // Consensus: derive from bracket summaries if present (avg signal), else null.
  const consensus =
    bracketSummaries.length > 0
      ? bracketSummaries.reduce((acc, b) => acc + b.consensusSignal, 0) /
        bracketSummaries.length
      : null;

  return {
    phase,
    running,
    roundNum,
    cycleId: null, // filled by EdgesContext via useCurrentCycle
    agents,
    bracketSummaries,
    rationales,
    telemetry,
    consensus,
  };
}
