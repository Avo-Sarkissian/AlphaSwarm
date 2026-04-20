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

export interface AgentView {
  id: string;
  bracket: BracketKey;
  confidence: number;
  flipped: 0 | 1; // KR-41.1-03: stubbed 0 until backend emits
  roundLastSpoke: number | null; // KR-41.1-03: stubbed null
  thinking: boolean; // KR-41.1-03: stubbed false
}

export interface BracketSummaryView {
  bracket: BracketKey;
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
