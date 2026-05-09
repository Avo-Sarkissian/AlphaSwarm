// CONTRACT-shaped frontend types. Backend snapshot -> adapter -> StateFrame.

export type BracketKey =
  | 'Quants'
  | 'Degens'
  | 'Sovereigns'
  | 'Macro'
  | 'Suits'
  | 'Insiders'
  | 'Agents'
  | 'DoomPosters'
  | 'Whales'
  | 'PolicyWonks';

// Agent discrete signal — backend emits SignalType enum ('BUY'|'SELL'|'HOLD'),
// adapter lowercases to match viz/panel css class conventions.
export type AgentSignal = 'buy' | 'sell' | 'hold';

export interface AgentView {
  id: string;
  bracket: BracketKey;
  bracketDisplay: string; // human-readable bracket label (backend BracketSummary.display_name)
  signal: AgentSignal; // derived from backend agent_states[id].signal (lowercased; default 'hold')
  confidence: number;
  flipped: 0 | 1; // KR-41.1-03: stubbed 0 until backend emits
  roundLastSpoke: number | null; // KR-41.1-03: stubbed null
  thinking: boolean; // KR-41.1-03: stubbed false
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
  slotsUsed: number; // KR-41.1-05: governor_metrics.current_slots ?? 0
  slotsMax: number; // KR-41.1-05: stubbed 8
  tps: number;
  ts: number; // epoch ms of last frame
  elapsedSeconds: number;
}

export interface RationaleView {
  agentId: string;
  round: number;
  text: string;
  citations: string[]; // KR-41.1-10: stubbed []
  sources: string[]; // KR-41.1-10: stubbed []
  ts: number;
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
