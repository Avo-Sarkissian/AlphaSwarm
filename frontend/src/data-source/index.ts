// The one data source of this page (docs/DECISIONS.md#adr-frontend-quant-terminal):
// the backend, or, in a VITE_DEMO=1 build, one recorded cycle replayed in the
// browser. The demo also answers every API call (request override).
import { installRequestOverride } from '../api/client';
import { createDemoDataSource } from './demo';
import { createLiveDataSource } from './live';
import type { DataSource } from './types';

export type { ConnectionStatus, DataSource } from './types';

let active: DataSource | null = null;

export function getDataSource(): DataSource {
  if (active === null) {
    if (import.meta.env.VITE_DEMO === '1') {
      const demo = createDemoDataSource();
      installRequestOverride((path, init) => demo.fetchJson(path, init));
      active = demo;
    } else {
      active = createLiveDataSource();
    }
  }
  return active;
}

/** Tests only: forget the chosen source and any request override. */
export function resetDataSourceForTests(): void {
  active = null;
  installRequestOverride(null);
}

/** Tooltip on every control the read-only demo disables. */
export const DEMO_LOCK_TITLE =
  'Read-only demo: this needs the local models and Neo4j. Clone the repository to run it.';

export interface DemoLock {
  locked: boolean;
  title: string | undefined;
}

/** Disabled state and tooltip for a control the static demo cannot offer. */
export function demoLock(): DemoLock {
  const locked = getDataSource().readOnly;
  return { locked, title: locked ? DEMO_LOCK_TITLE : undefined };
}
