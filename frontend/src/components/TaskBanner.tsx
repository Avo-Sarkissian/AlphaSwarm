// NR-8: long-running-task visibility banner.
//
// Renders nothing when neither a simulation nor an advisory synthesis is in
// flight. While active, surfaces:
//   - task name (SIMULATION RUNNING / ADVISORY SYNTHESIZING)
//   - elapsed time (mm:ss since the active flag flipped true)
//   - Ollama health status (advisory only — sim has its own model lifecycle)
//   - Cancel button (sim) or Retry button (advisory + Ollama disconnected)
//
// Mounted in app_v2.jsx between the topbar-error block and SignalWire so it
// shares horizontal space with the rest of the chrome strip.
//
// NR-7 colour switch: when the advisory branch sees Ollama disconnected, the
// banner background flips to --sell so the user sees the regression at a
// glance rather than wondering whether the synth is "still working".
import { useEffect, useState, type JSX } from 'react';
import { useOllamaHealth } from '../hooks/useOllamaHealth';

export interface TaskBannerProps {
  running: boolean;
  advisorySynthesizing: boolean;
  onCancelSim: () => void;
  onRetryAdvisory?: () => void;
}

function fmtElapsed(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const mm = Math.floor(totalSeconds / 60).toString().padStart(2, '0');
  const ss = (totalSeconds % 60).toString().padStart(2, '0');
  return `${mm}:${ss}`;
}

export function TaskBanner({
  running,
  advisorySynthesizing,
  onCancelSim,
  onRetryAdvisory,
}: TaskBannerProps): JSX.Element | null {
  const active = running || advisorySynthesizing;
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [now, setNow] = useState<number>(Date.now());

  // Health polling is gated on advisorySynthesizing alone — sim runs do not
  // benefit from the Ollama probe (they have their own per-agent model
  // lifecycle and a /simulate/stop affordance).
  const { health } = useOllamaHealth(advisorySynthesizing);

  // Latch start timestamp on the active edge; clear it on the inactive edge.
  useEffect(() => {
    if (active && startedAt === null) {
      setStartedAt(Date.now());
      setNow(Date.now());
    } else if (!active && startedAt !== null) {
      setStartedAt(null);
    }
  }, [active, startedAt]);

  // Tick the elapsed counter while active.
  useEffect(() => {
    if (!active) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [active]);

  if (!active) return null;

  const elapsedMs = startedAt !== null ? now - startedAt : 0;
  const taskName = advisorySynthesizing
    ? 'ADVISORY SYNTHESIZING'
    : 'SIMULATION RUNNING';
  const isOllamaDead =
    advisorySynthesizing && health !== null && !health.connected;

  return (
    <div
      role="status"
      aria-live="polite"
      className="task-banner"
      data-state={isOllamaDead ? 'error' : 'active'}
      style={{
        padding: '6px 12px',
        background: isOllamaDead ? 'var(--sell)' : 'var(--accent)',
        color: 'var(--bg)',
        fontSize: 12,
        fontFamily: "'JetBrains Mono', monospace",
        letterSpacing: '0.08em',
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        fontWeight: 600,
      }}
    >
      <span style={{ fontWeight: 700 }}>{taskName}</span>
      <span>· {fmtElapsed(elapsedMs)}</span>
      {advisorySynthesizing && health && (
        <span>
          · OLLAMA {health.connected ? 'CONNECTED' : 'DISCONNECTED'}
          {health.connected && health.models_loaded.length > 0
            ? ` (${health.models_loaded.length} model${
                health.models_loaded.length === 1 ? '' : 's'
              })`
            : ''}
        </span>
      )}
      <span style={{ marginLeft: 'auto' }} />
      {running && (
        <button
          type="button"
          className="btn ghost"
          style={{
            height: 22,
            padding: '0 8px',
            borderColor: 'var(--bg)',
            color: 'var(--bg)',
          }}
          onClick={onCancelSim}
        >
          Cancel
        </button>
      )}
      {advisorySynthesizing && isOllamaDead && onRetryAdvisory && (
        <button
          type="button"
          className="btn ghost"
          style={{
            height: 22,
            padding: '0 8px',
            borderColor: 'var(--bg)',
            color: 'var(--bg)',
          }}
          onClick={onRetryAdvisory}
        >
          Retry Advisory
        </button>
      )}
    </div>
  );
}
