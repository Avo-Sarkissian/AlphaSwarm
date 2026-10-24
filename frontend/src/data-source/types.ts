// Where frames and API answers come from: the backend (live) or one committed
// cycle export replayed in the browser (demo) (docs/DECISIONS.md#adr-frontend-quant-terminal).
import type { RequestOptions } from '../api/client';

/** connecting: nothing yet. open: frames arrive. stale: open but silent. closed: lost or failed. */
export type ConnectionStatus = 'connecting' | 'open' | 'stale' | 'closed';

export interface DataSource {
  readonly kind: 'live' | 'demo';
  /** True in the static demo: nothing that changes state or needs the models is offered. */
  readonly readOnly: boolean;
  subscribeFrames(onFrame: (raw: unknown) => void, onStatus: (s: ConnectionStatus) => void): () => void;
  fetchJson<T>(path: string, init?: RequestOptions): Promise<T>;
}
