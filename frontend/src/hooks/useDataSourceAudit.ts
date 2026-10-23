// Hook that surfaces the WS frame's dataSourceAudit slice (adapter-mapped
// from snake_case data_source_audit). Returns [] when the sim has not yet
// made any provider calls (sim idle, or right after Start before R1 dispatch).
//
// The SignalWire ticker and the Data Sources takeover read only this; there
// is no mock fallback (docs/DECISIONS.md#kr-41-1-02).
import { useConnection } from '../context/ConnectionContext';
import type { DataSourceAuditView } from '../types';

export type { DataSourceAuditView };

/**
 * Read the most recent provider-call audit entries from the WS frame.
 *
 * The backend keeps a bounded deque (maxlen=100) of every yfinance/RSS
 * fetch on StateStore. The broadcaster mirrors it into every snapshot,
 * so reconnecting clients see the existing window immediately.
 */
export function useDataSourceAudit(): DataSourceAuditView[] {
  const conn = useConnection();
  return conn.lastFrame?.dataSourceAudit ?? [];
}
