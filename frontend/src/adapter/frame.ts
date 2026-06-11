import type {
  AgentSignal,
  AgentView,
  BracketKey,
  BracketSummaryView,
  DataSourceAuditView,
  RationaleView,
  StateFrame,
  TelemetrySlice,
} from '../types';
import { agentIdToBracket } from './agentId';

// Backend BracketType.value → human display label (matches state.py BracketSummary.display_name).
const BRACKET_DISPLAY: Record<BracketKey, string> = {
  Institutions: 'Institutions',
  SellSide: 'Sell-Side',
  EventDriven: 'Event-Driven',
  Quants: 'Quants',
  Degens: 'Degens',
  Narrators: 'Narrators',
  Algos: 'Algos',
  Macro: 'Macro',
  Shorts: 'Shorts',
  Allocators: 'Allocators',
};

// Wire bracket value (snake_case) → frontend BracketKey (PascalCase).
const WIRE_TO_KEY: Record<string, BracketKey> = {
  institutions: 'Institutions',
  sell_side: 'SellSide',
  event_driven: 'EventDriven',
  quants: 'Quants',
  degens: 'Degens',
  narrators: 'Narrators',
  algos: 'Algos',
  macro: 'Macro',
  shorts: 'Shorts',
  allocators: 'Allocators',
};

function normaliseSignal(raw: unknown): AgentSignal {
  if (typeof raw !== 'string') return 'hold';
  const s = raw.toLowerCase();
  if (s === 'buy' || s === 'sell' || s === 'hold' || s === 'parse_error')
    return s;
  return 'hold';
}

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
  // KR-41.1-05 (CLOSED by ITEM 3 of quick task 260512-jqn):
  //   Backend GovernorMetrics already carries `active_count` (live slots in
  //   use) and `current_slots` (governor budget — adjusted on memory pressure
  //   transitions). Drop the {0, 8} stub and read both fields directly so the
  //   PARALLEL SLOTS KPI tile shows live numerator/denominator during
  //   dispatch (e.g. 12/16) instead of freezing at 0/8.
  const slotsUsed =
    typeof gov.active_count === 'number' ? gov.active_count : 0;
  const slotsMax =
    typeof gov.current_slots === 'number' ? gov.current_slots : 0;
  const governorState =
    typeof gov.governor_state === 'string' ? gov.governor_state : null;

  const telemetry: TelemetrySlice = {
    memMb: memPct, // KR-41.1-04: percent, not MB
    slotsUsed,
    slotsMax,
    governorState,
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
      const bracket = agentIdToBracket(id);
      // Backend deliberately emits signal=null during dispatch — render the
      // node as "thinking" (neutral hold visual, dimmed/pulsing in viz).
      const thinking = s.signal === null || s.signal === undefined;
      return {
        id,
        bracket,
        bracketDisplay: BRACKET_DISPLAY[bracket] ?? bracket,
        signal: normaliseSignal(s.signal),
        confidence,
        flipped: 0, // KR-41.1-03
        roundLastSpoke: null, // KR-41.1-03
        thinking,
      };
    },
  );

  const bracketRaw = Array.isArray(r.bracket_summaries)
    ? (r.bracket_summaries as unknown[])
    : [];
  const bracketSummaries: BracketSummaryView[] = bracketRaw.map((b) => {
    const bs = (b ?? {}) as Record<string, unknown>;
    const bracket =
      typeof bs.bracket === 'string'
        ? (WIRE_TO_KEY[bs.bracket] ?? (bs.bracket as BracketKey))
        : 'Quants';
    const buy = typeof bs.buy_count === 'number' ? bs.buy_count : 0;
    const sell = typeof bs.sell_count === 'number' ? bs.sell_count : 0;
    const hold = typeof bs.hold_count === 'number' ? bs.hold_count : 0;
    const total =
      typeof bs.total === 'number' ? bs.total : buy + sell + hold;
    const avgConfidence =
      typeof bs.avg_confidence === 'number' ? bs.avg_confidence : 0;
    const display =
      typeof bs.display_name === 'string'
        ? bs.display_name
        : (BRACKET_DISPLAY[bracket] ?? bracket);
    // consensusSignal kept numeric for back-compat — derive as avg_sentiment if present, else 0.
    const consensusSignal =
      typeof bs.avg_sentiment === 'number' ? bs.avg_sentiment : 0;
    return {
      bracket,
      display,
      buy,
      sell,
      hold,
      total,
      avgConfidence,
      consensusSignal,
      agentCount: total,
    };
  });

  const ratRaw = Array.isArray(r.rationale_entries)
    ? (r.rationale_entries as unknown[])
    : [];
  const rationales: RationaleView[] = ratRaw.map((e) => {
    const re = (e ?? {}) as Record<string, unknown>;
    return {
      agentId: typeof re.agent_id === 'string' ? re.agent_id : '',
      signal: normaliseSignal(re.signal), // per-entry wire signal, not current agent state
      round: typeof re.round_num === 'number' ? re.round_num : (roundNum ?? 0),
      text: typeof re.rationale === 'string' ? re.rationale : '',
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

  // ITEM 5 of quick task 260512-jqn — DataSource audit slice.
  // Backend StateSnapshot.data_source_audit (snake_case wire) → frontend
  // DataSourceAuditView (camelCase). SignalWire hook consumes this.
  const auditRaw = Array.isArray(r.data_source_audit)
    ? (r.data_source_audit as unknown[])
    : [];
  const dataSourceAudit: DataSourceAuditView[] = auditRaw
    .map((e): DataSourceAuditView | null => {
      if (!e || typeof e !== 'object') return null;
      const ae = e as Record<string, unknown>;
      return {
        ts: typeof ae.ts === 'number' ? ae.ts : 0,
        source: typeof ae.source === 'string' ? ae.source : 'unknown',
        query: typeof ae.query === 'string' ? ae.query : '',
        result: typeof ae.result === 'string' ? ae.result : '',
        used: typeof ae.used === 'boolean' ? ae.used : false,
      };
    })
    .filter((e): e is DataSourceAuditView => e !== null);

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
    dataSourceAudit,
  };
}
