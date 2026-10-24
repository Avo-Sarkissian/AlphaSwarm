// CONTRACT-shaped frontend types. Backend snapshot -> adapter -> StateFrame.

/** Wire bracket keys (BracketType.value), in DEFAULT_BRACKETS order. */
export type BracketKey =
  | 'institutions'
  | 'sell_side'
  | 'event_driven'
  | 'quants'
  | 'degens'
  | 'narrators'
  | 'algos'
  | 'macro'
  | 'shorts'
  | 'allocators';

// Agent discrete signal — backend emits lowercase 'buy'|'sell'|'hold'|
// 'parse_error' on the wire; 'parse_error' gets a distinct muted treatment.
export type AgentSignal = 'buy' | 'sell' | 'hold' | 'parse_error';

/** A signal an agent actually chose (not pending, not a parse failure). */
export type DecidedSignal = 'buy' | 'sell' | 'hold';

export interface AgentView {
  id: string;
  bracket: BracketKey | 'unknown';
  bracketDisplay: string; // human-readable bracket label (backend BracketSummary.display_name)
  signal: AgentSignal | null; // null = pending: no decision yet this round (never shown as HOLD)
  confidence: number;
  flipped: 0 | 1; // computed in the browser from the previous round (docs/DECISIONS.md#kr-41-1-03)
  /** Previous round's decided signal when flipped === 1 (computed in the browser). */
  flippedFrom?: DecidedSignal;
  roundLastSpoke: number | null; // KR-41.1-03: stubbed null
  thinking: boolean; // true exactly when signal === null (dim/pulsing node)
}

export interface BracketSummaryView {
  bracket: BracketKey | 'unknown';
  display: string; // BracketSummary.display_name
  buy: number; // BracketSummary.buy_count
  sell: number; // BracketSummary.sell_count
  hold: number; // BracketSummary.hold_count
  total: number; // BracketSummary.total
  avgConfidence: number; // BracketSummary.avg_confidence (0..1)
}

export interface TelemetrySlice {
  memMb: number; // KR-41.1-04: governor_metrics.memory_percent (0-100); label reads "%"
  slotsUsed: number; // governor_metrics.active_count (KR-41.1-05 CLOSED by 260512-jqn ITEM 3)
  slotsMax: number; // governor_metrics.current_slots (KR-41.1-05 CLOSED by 260512-jqn ITEM 3)
  governorState: string | null; // governor_metrics.governor_state ('running'|'throttled'|'paused'|'crisis'|'recovering'|'idle')
  tps: number;
  ts: number; // epoch ms of last frame
  elapsedSeconds: number;
}

export interface RationaleView {
  seq: number; // backend-stamped; grows for the life of the server process (replay: 1..n)
  agentId: string;
  signal: AgentSignal; // per-entry wire signal (NOT the agent's current signal)
  round: number;
  text: string;
  citations: string[]; // KR-41.1-10: stubbed []
  sources: string[]; // KR-41.1-10: stubbed []
  ts: number; // epoch ms when the backend recorded it; 0 = unknown (replay)
}

// ITEM 5 of quick task 260512-jqn — DataSource audit view (one provider call).
export interface DataSourceAuditView {
  ts: number;
  source: string; // 'yfinance' | 'rss' | 'fred' | ...
  query: string;
  result: string; // 'ok' | 'cached' | 'error: <msg>'
  used: boolean;
}

export interface JobStatusView {
  state: 'idle' | 'running' | 'failed';
  cycleId: string | null;
  errorCode: string | null;
}

export interface JobsView {
  advisory: JobStatusView;
  report: JobStatusView;
}

export interface RunErrorView {
  code: string;
  message: string;
  roundNum: number | null;
  ts: number; // epoch seconds (backend time.time())
}

export interface AppliedShockView {
  text: string;
  roundNum: number;
}

export interface StateFrame {
  schemaVersion: number; // 0 when the frame carries none
  mode: FrameMode;
  phase: string;
  running: boolean;
  roundNum: number | null;
  cycleId: string | null;
  numRounds: number;
  edgesVersion: number;
  agents: AgentView[];
  bracketSummaries: BracketSummaryView[];
  rationales: RationaleView[];
  telemetry: TelemetrySlice;
  // ITEM 5 of 260512-jqn — live provider-call audit log for SignalWire.
  dataSourceAudit: DataSourceAuditView[];
  jobs: JobsView;
  lastError: RunErrorView | null;
  pendingShock: string | null;
  appliedShocks: AppliedShockView[];
  shockWindowOpen: boolean;
}

// ── Wire types: exact mirror of alphaswarm.web.wire.StateFrame (snake_case) ──
// tests/test_wire_contract.py writes the golden frames in src/__tests__/fixtures/;
// frame.test.ts checks them against these declarations. Change both sides together.
export type WireSignal = 'buy' | 'sell' | 'hold' | 'parse_error';
export type FrameMode = 'live' | 'replay' | 'idle';
export type WirePhase =
  | 'idle'
  | 'seeding'
  | 'round_1'
  | 'round_2'
  | 'round_3'
  | 'finalizing'
  | 'complete'
  | 'replay';

export interface WireAgentState {
  signal: WireSignal | null;
  confidence: number;
}

export interface WireGovernorMetrics {
  current_slots: number;
  active_count: number;
  pressure_level: string;
  memory_percent: number;
  governor_state: string;
  timestamp: number;
}

export interface WireRationaleEntry {
  seq: number;
  ts: number;
  agent_id: string;
  signal: WireSignal;
  rationale: string;
  round_num: number;
}

export interface WireBracketSummary {
  bracket: string;
  display_name: string;
  buy_count: number;
  sell_count: number;
  hold_count: number;
  total: number;
  avg_confidence: number;
  avg_sentiment: number;
}

export interface WireDataSourceAuditEntry {
  ts: number;
  source: string;
  query: string;
  result: string;
  used: boolean;
}

export interface WireRunError {
  code: string;
  message: string;
  round_num: number | null;
  ts: number;
}

export interface WireJobStatus {
  state: 'idle' | 'running' | 'failed';
  cycle_id: string | null;
  error_code: string | null;
}

export interface WireJobs {
  advisory: WireJobStatus;
  report: WireJobStatus;
}

export interface WireAppliedShock {
  text: string;
  round_num: number;
}

export interface WireStateFrame {
  schema_version: 1;
  mode: FrameMode;
  phase: WirePhase;
  cycle_id: string | null;
  num_rounds: number;
  round_num: number;
  agent_count: number;
  agent_states: Record<string, WireAgentState>;
  elapsed_seconds: number;
  governor_metrics: WireGovernorMetrics;
  tps: number;
  rationale_entries: WireRationaleEntry[];
  bracket_summaries: WireBracketSummary[];
  data_source_audit: WireDataSourceAuditEntry[];
  edges_version: number;
  jobs: WireJobs;
  last_error: WireRunError | null;
  pending_shock: string | null;
  applied_shocks: WireAppliedShock[];
  shock_window_open: boolean;
}
