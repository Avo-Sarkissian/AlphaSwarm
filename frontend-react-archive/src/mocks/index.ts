// Barrel: only tree-shake-friendly production mocks.
// HOLDINGS is intentionally NOT re-exported — it is DEV-only.
// Dev consumer pattern (inside a component):
//   if (import.meta.env.DEV) {
//     const { HOLDINGS } = await import('../mocks/holdings');
//     // ...
//   }

export { SIGNAL_WIRE_SEED } from './wire';
export type { SignalWireEvent } from './wire';
export { DATA_SOURCES, SOURCE_STATS, SOURCE_GROUP_COLOR } from './sources';
export type { DataSource, SourceStat } from './sources';
