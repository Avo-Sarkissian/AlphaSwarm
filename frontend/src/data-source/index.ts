// The one data source of this page (docs/DECISIONS.md#adr-frontend-quant-terminal).
import { createLiveDataSource } from './live';
import type { DataSource } from './types';

export type { ConnectionStatus, DataSource } from './types';

let active: DataSource | null = null;

export function getDataSource(): DataSource {
  active ??= createLiveDataSource();
  return active;
}
