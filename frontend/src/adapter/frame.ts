import type {
  AgentSignal,
  AgentView,
  AppliedShockView,
  BracketSummaryView,
  DataSourceAuditView,
  FrameMode,
  JobStatusView,
  RationaleView,
  RunErrorView,
  StateFrame,
  TelemetrySlice,
} from '../types';
import { bracketOf, bracketSpec, toBracketKey } from '../data';

/** The StateFrame schema this bundle was built against (alphaswarm.web.wire.SCHEMA_VERSION). */
export const SUPPORTED_SCHEMA_VERSION = 1;
let warnedSchemaVersion: number | null = null;

function normaliseSignal(raw: unknown): AgentSignal {
  if (typeof raw !== 'string') return 'hold';
  const s = raw.toLowerCase();
  if (s === 'buy' || s === 'sell' || s === 'hold' || s === 'parse_error')
    return s;
  return 'hold';
}

// Agent signal from the wire: null, missing or unrecognised means the agent has
// not decided yet this round. It is never coerced to HOLD.
function parseAgentSignal(raw: unknown): AgentSignal | null {
  if (typeof raw !== 'string') return null;
  const s = raw.toLowerCase();
  return s === 'buy' || s === 'sell' || s === 'hold' || s === 'parse_error' ? s : null;
}

const finiteOr = (v: unknown, fallback: number): number =>
  typeof v === 'number' && Number.isFinite(v) ? v : fallback;

const stringOrNull = (v: unknown): string | null => (typeof v === 'string' ? v : null);

// The backend derives mode from phase; do the same when a frame carries no mode.
function adaptMode(raw: unknown, phase: string): FrameMode {
  if (raw === 'live' || raw === 'replay' || raw === 'idle') return raw;
  if (phase === 'idle') return 'idle';
  if (phase === 'replay') return 'replay';
  return 'live';
}

function adaptJob(raw: unknown): JobStatusView {
  const j = (raw ?? {}) as Record<string, unknown>;
  const state = j.state === 'running' || j.state === 'failed' ? j.state : 'idle';
  return { state, cycleId: stringOrNull(j.cycle_id), errorCode: stringOrNull(j.error_code) };
}

function adaptLastError(raw: unknown): RunErrorView | null {
  if (typeof raw !== 'object' || raw === null) return null;
  const e = raw as Record<string, unknown>;
  if (typeof e.code !== 'string') return null;
  return {
    code: e.code,
    message: typeof e.message === 'string' ? e.message : '',
    roundNum: typeof e.round_num === 'number' ? e.round_num : null,
    ts: finiteOr(e.ts, 0),
  };
}

function adaptAppliedShocks(raw: unknown): AppliedShockView[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .map((s): AppliedShockView | null => {
      if (typeof s !== 'object' || s === null) return null;
      const shock = s as Record<string, unknown>;
      if (typeof shock.text !== 'string') return null;
      return { text: shock.text, roundNum: finiteOr(shock.round_num, 0) };
    })
    .filter((s): s is AppliedShockView => s !== null);
}

// A frontend bundle built against another schema keeps working (the adapter is
// defensive) but says so once, so a stale `frontend/dist` is easy to diagnose.
function checkSchemaVersion(version: number): void {
  if (version === SUPPORTED_SCHEMA_VERSION || version === warnedSchemaVersion) return;
  warnedSchemaVersion = version;
  // eslint-disable-next-line no-console
  console.warn(
    `[adaptSnapshot] backend sent schema_version ${version}; this UI expects ` +
      `${SUPPORTED_SCHEMA_VERSION}. Rebuild the frontend (npm run build).`,
  );
}

// Defensive: every field has a typed fallback, so a partial or malformed frame
// never throws. The wire shape is WireStateFrame (types.ts), pinned by the
// backend-written fixtures in src/__tests__/fixtures/.
export function adaptSnapshot(raw: unknown): StateFrame {
  const r = (raw ?? {}) as Record<string, unknown>;
  const schemaVersion = finiteOr(r.schema_version, 0);
  if (typeof r.schema_version === 'number') checkSchemaVersion(schemaVersion);

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
      const bracket = bracketOf(id);
      // signal=null during dispatch means "no decision yet": pending, rendered
      // as a dim pulsing node and counted nowhere (lib/tally.ts).
      const signal = parseAgentSignal(s.signal);
      return {
        id,
        bracket,
        bracketDisplay: bracketSpec(bracket)?.display ?? 'Unknown',
        signal,
        confidence,
        flipped: 0, // KR-41.1-03
        roundLastSpoke: null, // KR-41.1-03
        thinking: signal === null,
      };
    },
  );

  const bracketRaw = Array.isArray(r.bracket_summaries)
    ? (r.bracket_summaries as unknown[])
    : [];
  const bracketSummaries: BracketSummaryView[] = bracketRaw.map((b) => {
    const bs = (b ?? {}) as Record<string, unknown>;
    const bracket = toBracketKey(bs.bracket);
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
        : (bracketSpec(bracket)?.display ?? 'Unknown');
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
  const rationales: RationaleView[] = ratRaw.map((e, i) => {
    const re = (e ?? {}) as Record<string, unknown>;
    return {
      seq: finiteOr(re.seq, i + 1),
      agentId: typeof re.agent_id === 'string' ? re.agent_id : '',
      signal: normaliseSignal(re.signal), // per-entry wire signal, not current agent state
      round: typeof re.round_num === 'number' ? re.round_num : (roundNum ?? 0),
      text: typeof re.rationale === 'string' ? re.rationale : '',
      citations: [], // KR-41.1-10
      sources: [], // KR-41.1-10
      ts: finiteOr(re.ts, 0) * 1000, // wire: epoch seconds (0 in replay); view: epoch ms
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

  const jobsRaw = (r.jobs ?? {}) as Record<string, unknown>;

  return {
    schemaVersion,
    mode: adaptMode(r.mode, phase),
    phase,
    running,
    roundNum,
    cycleId: stringOrNull(r.cycle_id),
    numRounds: finiteOr(r.num_rounds, 3),
    edgesVersion: finiteOr(r.edges_version, 0),
    agents,
    bracketSummaries,
    rationales,
    telemetry,
    consensus,
    dataSourceAudit,
    jobs: { advisory: adaptJob(jobsRaw.advisory), report: adaptJob(jobsRaw.report) },
    lastError: adaptLastError(r.last_error),
    pendingShock: stringOrNull(r.pending_shock),
    appliedShocks: adaptAppliedShocks(r.applied_shocks),
    shockWindowOpen: r.shock_window_open === true,
  };
}
