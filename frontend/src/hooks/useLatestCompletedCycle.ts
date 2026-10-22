import { useEffect, useState } from 'react';
import { apiFetch } from '../api/client';
import type { CycleMeta } from '../types';

// Newest completed cycle from GET /api/replay/cycles (newest first), polled
// every 5 s while at least one consumer is mounted. It is only the default
// for report/advisory pickers (see lib/defaultCycle.ts); the live dashboard
// keys everything on the frame's cycle_id.
//
// Module-level singleton: one interval shared by all consumers, so React
// StrictMode double-mounts do not multiply requests.

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

export function useLatestCompletedCycle() {
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
