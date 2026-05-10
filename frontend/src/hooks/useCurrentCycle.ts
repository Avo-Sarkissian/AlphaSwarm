import { useEffect, useState } from 'react';
import { apiFetch } from '../api/client';
import type { CycleMeta } from '../types';

// GET /api/simulate/status is NOT implemented. Derive cycleId from the first
// entry of /api/replay/cycles (newest first). Poll every 5s.
//
// Module-level singleton: ONE interval shared by all consumers. Replaces the
// previous per-consumer usePolling() approach (each consumer was creating its
// own interval AND firing an immediate tick on mount, producing 8x rapid
// requests with 4 consumers under React StrictMode double-mount).
//
// Public return shape preserved byte-identical for EdgesContext, ReportModal,
// AdvisoryV2 (the existing destructure consumers).

interface CycleState {
  cycleId: string | null;
  loading: boolean;
  error: Error | null;
}

const INTERVAL_MS = 5000;

let state: CycleState = { cycleId: null, loading: true, error: null };
const subscribers = new Set<(s: CycleState) => void>();
let intervalId: ReturnType<typeof setInterval> | null = null;
let inFlight: Promise<void> | null = null;

function emit() {
  for (const fn of subscribers) fn(state);
}

async function tick() {
  // Dedupe in-flight requests — guards against the immediate tick + interval
  // tick double-fire if a consumer subscribes mid-flight.
  if (inFlight) return inFlight;
  inFlight = (async () => {
    try {
      const data = await apiFetch<{ cycles: CycleMeta[] }>('/api/replay/cycles');
      state = {
        cycleId: data?.cycles?.[0]?.cycle_id ?? null,
        loading: false,
        error: null,
      };
    } catch (e: unknown) {
      state = {
        cycleId: state.cycleId,
        loading: false,
        error: e instanceof Error ? e : new Error(String(e)),
      };
    } finally {
      emit();
      inFlight = null;
    }
  })();
  return inFlight;
}

function ensureLoop() {
  if (intervalId !== null) return;
  // Immediate first fetch ONCE per interval lifecycle.
  void tick();
  intervalId = setInterval(() => void tick(), INTERVAL_MS);
}

function teardownIfIdle() {
  if (subscribers.size > 0) return;
  if (intervalId !== null) {
    clearInterval(intervalId);
    intervalId = null;
  }
}

export function useCurrentCycle() {
  const [snap, setSnap] = useState<CycleState>(state);

  useEffect(() => {
    subscribers.add(setSnap);
    ensureLoop();
    // Sync to the latest state at subscribe time so a late mount does not show
    // stale `loading: true` after the first tick already resolved.
    setSnap(state);
    return () => {
      subscribers.delete(setSnap);
      teardownIfIdle();
    };
  }, []);

  return {
    cycleId: snap.cycleId,
    loading: snap.loading,
    error: snap.error,
  };
}
