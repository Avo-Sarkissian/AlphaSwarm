import { useEffect, useState } from 'react';
import { listCycles } from '../api/replay';

// Newest completed cycle from GET /api/replay/cycles?limit=1 (newest first),
// polled every 5 s while at least one consumer is mounted. It is only a
// fallback: report and advisory default to it (lib/defaultCycle.ts), the
// interview when no cycle is on screen (lib/interview.ts); the live dashboard
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
      const page = await listCycles({ limit: 1 });
      state = {
        cycleId: page.cycles[0]?.cycle_id ?? null,
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

// What a consumer mounting now should see. With no loop running, the mount
// starts a fresh lookup, so the cached answer may be stale until it lands.
function mountSnapshot(): CycleState {
  return intervalId === null ? { ...state, loading: true } : state;
}

function ensureLoop() {
  if (intervalId !== null) return;
  // Immediate first fetch ONCE per interval lifecycle; until it answers,
  // consumers see loading (a cycle may have completed since the last loop).
  state = { ...state, loading: true };
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
  const [snap, setSnap] = useState<CycleState>(mountSnapshot);

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
