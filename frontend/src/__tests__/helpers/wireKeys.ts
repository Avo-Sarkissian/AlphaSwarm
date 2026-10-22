// Key lists for every wire object, checked against the TypeScript mirror in
// src/types.ts at compile time: `tsc -b` fails when a list misses a key or names
// one the type does not declare. frame.test.ts compares these lists with the keys
// in the backend-written fixtures, so drift on either side fails a gate.
import type {
  WireAgentState,
  WireAppliedShock,
  WireBracketSummary,
  WireDataSourceAuditEntry,
  WireGovernorMetrics,
  WireJobStatus,
  WireJobs,
  WireRationaleEntry,
  WireRunError,
  WireStateFrame,
} from '../../types';

type Missing<T, K extends readonly PropertyKey[]> = Exclude<keyof T, K[number]>;

function wireKeys<T>() {
  return <const K extends readonly (keyof T)[]>(
    keys: K & ([Missing<T, K>] extends [never] ? unknown : { missingKeys: Missing<T, K> }),
  ): readonly string[] => [...keys].map(String);
}

export const FRAME_KEYS = wireKeys<WireStateFrame>()([
  'schema_version',
  'mode',
  'phase',
  'cycle_id',
  'num_rounds',
  'round_num',
  'agent_count',
  'agent_states',
  'elapsed_seconds',
  'governor_metrics',
  'tps',
  'rationale_entries',
  'bracket_summaries',
  'data_source_audit',
  'edges_version',
  'jobs',
  'last_error',
  'pending_shock',
  'applied_shocks',
  'shock_window_open',
]);
export const AGENT_STATE_KEYS = wireKeys<WireAgentState>()(['signal', 'confidence']);
export const GOVERNOR_KEYS = wireKeys<WireGovernorMetrics>()([
  'current_slots',
  'active_count',
  'pressure_level',
  'memory_percent',
  'governor_state',
  'timestamp',
]);
export const RATIONALE_KEYS = wireKeys<WireRationaleEntry>()([
  'seq',
  'ts',
  'agent_id',
  'signal',
  'rationale',
  'round_num',
]);
export const BRACKET_SUMMARY_KEYS = wireKeys<WireBracketSummary>()([
  'bracket',
  'display_name',
  'buy_count',
  'sell_count',
  'hold_count',
  'total',
  'avg_confidence',
  'avg_sentiment',
]);
export const AUDIT_KEYS = wireKeys<WireDataSourceAuditEntry>()([
  'ts',
  'source',
  'query',
  'result',
  'used',
]);
export const RUN_ERROR_KEYS = wireKeys<WireRunError>()(['code', 'message', 'round_num', 'ts']);
export const JOBS_KEYS = wireKeys<WireJobs>()(['advisory', 'report']);
export const JOB_STATUS_KEYS = wireKeys<WireJobStatus>()(['state', 'cycle_id', 'error_code']);
export const APPLIED_SHOCK_KEYS = wireKeys<WireAppliedShock>()(['text', 'round_num']);
