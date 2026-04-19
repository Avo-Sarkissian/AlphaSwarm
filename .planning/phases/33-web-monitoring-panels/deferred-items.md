# Deferred Items - Phase 33

## Pre-existing Build Issues (Out of Scope)

Discovered during Plan 01 execution. These errors exist on the base commit (82c5e78) before any Plan 01 changes.

1. **ForceGraph.vue unused imports** - `forceLink` (line 3) and `EdgeItem` (line 4) are imported but never used. Flagged by `noUnusedLocals` in tsconfig.app.json.

2. **useWebSocket.ts unused variable** - `reconnectTimer` (line 42) is assigned but its value is never read. The variable is used for timeout scheduling but TypeScript considers it unused since the value is never read back.

3. **useWebSocket.ts readonly type mismatch** - Vue's `readonly()` wraps refs with deep readonly types, making arrays `readonly T[]`. The `WebSocketState` interface declares `Readonly<Ref<T[]>>` which expects a mutable array inside the ref. This causes TS2322 errors for `snapshot`, `latestRationales`, and `allRationales` in `vue-tsc -b` mode. Fix requires changing interface types to use `DeepReadonly` or `ReadonlyArray`.

**Impact:** `npm run build` (`vue-tsc -b && vite build`) fails. `npx vue-tsc --noEmit` passes (different strictness mode).
