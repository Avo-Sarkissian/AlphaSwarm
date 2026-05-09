// src/mocks/index.ts
// Dev-only re-export hub for SignalWire / DataSources / holdings mocks.
// Re-exports are gated behind import.meta.env.DEV so production bundles
// (npm run build) tree-shake the entire mocks/* tree out — keeps the
// production grep gate deterministic (KR-41.1-02 enforcement).
//
// Consumers (v2.jsx SignalWire, v2.jsx DataSourcesTakeover, etc.) MUST
// import directly from './wire' / './sources' / './holdings' — never from
// this barrel — so static analysis can drop the dev-only chunks.

// intentionally empty in production: import.meta.env.DEV ? <re-exports> : <empty>
// Keeping the file present (not deleted) so future dev-only barrel imports compile.
export {};
