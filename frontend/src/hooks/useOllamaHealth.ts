// NR-7: poll /api/health/ollama every 5 seconds while a long-running task is
// active. Idle pages do NOT poll — `active` gates the timer entirely.
//
// Returns a snapshot of the latest health response (or null when inactive)
// plus the most recent fetch error (cleared on the next successful tick).
//
// Cancellation: the cleanup callback flips a `cancelled` flag AND clears the
// interval. Pending fetches that resolve after cancellation are no-ops.
import { useEffect, useState } from 'react';
import { getOllamaHealth, type OllamaHealth } from '../api/health';

export interface UseOllamaHealthResult {
  health: OllamaHealth | null;
  error: Error | null;
}

const POLL_INTERVAL_MS = 5000;

export function useOllamaHealth(active: boolean): UseOllamaHealthResult {
  const [health, setHealth] = useState<OllamaHealth | null>(null);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    if (!active) {
      // Reset state when transitioning to inactive — UI consumers can rely
      // on `health === null` meaning "no live signal" rather than stale.
      setHealth(null);
      setError(null);
      return;
    }

    let cancelled = false;

    const tick = () => {
      getOllamaHealth()
        .then((h) => {
          if (cancelled) return;
          setHealth(h);
          setError(null);
        })
        .catch((e: unknown) => {
          if (cancelled) return;
          // Network failure / non-200: synthesize a disconnected health
          // record so the banner can show "OLLAMA DISCONNECTED" without
          // a separate error state.
          setHealth({ connected: false, models_loaded: [] });
          setError(e instanceof Error ? e : new Error(String(e)));
        });
    };

    tick(); // immediate fire so the banner does not wait 5s for first signal
    const id = window.setInterval(tick, POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [active]);

  return { health, error };
}
