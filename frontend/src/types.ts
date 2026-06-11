// CONTRACT-shaped frontend types. Backend snapshot -> adapter -> StateFrame.

export type BracketKey =
  | 'Institutions'
  | 'SellSide'
  | 'EventDriven'
  | 'Quants'
  | 'Degens'
  | 'Narrators'
  | 'Algos'
  | 'Macro'
  | 'Shorts'
  | 'Allocators';

// Agent discrete signal — backend emits lowercase 'buy'|'sell'|'hold'|
// 'parse_error' on the wire; 'parse_error' gets a distinct muted treatment.
export type AgentSignal = 'buy' | 'sell' | 'hold' | 'parse_error';

export interface AgentView {
  id: string;
  bracket: BracketKey;
  bracketDisplay: string; // human-readable bracket label (backend BracketSummary.display_name)
  signal: AgentSignal; // derived from backend agent_states[id].signal (lowercased; default 'hold')
  confidence: number;
  flipped: 0 | 1; // KR-41.1-03: stubbed 0 until backend emits
  roundLastSpoke: number | null; // KR-41.1-03: stubbed null
  thinking: boolean; // true when wire signal=null (mid-dispatch placeholder)
}

export interface BracketSummaryView {
  bracket: BracketKey;
  display: string; // BracketSummary.display_name
  buy: number; // BracketSummary.buy_count
  sell: number; // BracketSummary.sell_count
  hold: number; // BracketSummary.hold_count
  total: number; // BracketSummary.total
  avgConfidence: number; // BracketSummary.avg_confidence (0..1)
  // consensusSignal/agentCount kept for Wave 1 compat (read by tests/tools if any).
  consensusSignal: number;
  agentCount: number;
}

export interface TelemetrySlice {
  memMb: number; // KR-41.1-04: governor_metrics.memory_percent (0-100); label reads "%"
  slotsUsed: number; // governor_metrics.active_count (KR-41.1-05 CLOSED by 260512-jqn ITEM 3)
  slotsMax: number; // governor_metrics.current_slots (KR-41.1-05 CLOSED by 260512-jqn ITEM 3)
  governorState: string | null; // governor_metrics.governor_state ('normal'|'paused'|'crisis'|…)
  tps: number;
  ts: number; // epoch ms of last frame
  elapsedSeconds: number;
}

export interface RationaleView {
  agentId: string;
  signal: AgentSignal; // per-entry wire signal (NOT the agent's current signal)
  round: number;
  text: string;
  citations: string[]; // KR-41.1-10: stubbed []
  sources: string[]; // KR-41.1-10: stubbed []
  ts: number;
}

// ITEM 5 of quick task 260512-jqn — DataSource audit view (one provider call).
export interface DataSourceAuditView {
  ts: number;
  source: string; // 'yfinance' | 'rss' | 'fred' | ...
  query: string;
  result: string; // 'ok' | 'cached' | 'error: <msg>'
  used: boolean;
}

export interface StateFrame {
  phase: string;
  running: boolean;
  roundNum: number | null;
  cycleId: string | null;
  agents: AgentView[];
  bracketSummaries: BracketSummaryView[];
  rationales: RationaleView[];
  telemetry: TelemetrySlice;
  consensus: number | null;
  // ITEM 5 of 260512-jqn — live provider-call audit log for SignalWire.
  dataSourceAudit: DataSourceAuditView[];
}

export interface EdgeView {
  source: string;
  target: string;
  weight: number;
}

export interface CycleMeta {
  cycle_id: string;
  started_at?: string;
  seed?: string;
  final_consensus?: number | null;
}
