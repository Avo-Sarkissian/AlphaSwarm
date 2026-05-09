// v2 states — idle, seeding, memory-paused, error.
// Each is a full-canvas overlay that replaces the force graph.
//
// Plan 04 wiring: overlays now derive their kind from the split contexts
// (Plan 02 output). The decision table is inlined in LifecycleOverlay to
// avoid creating a new hook (per prompt <do_not>).
//
// Decision table (matches RESEARCH §states.jsx wiring):
//   connection.reconnectFailed              → 'error'    (highest priority)
//   telemetry.phase === 'idle'              → 'idle'
//   telemetry.phase === 'seeding'           → 'seeding'
//   telemetry.memMb  >= memThresholdPct     → 'mempause'
//   else                                    → null  (live graph shows)
import { useTelemetry } from '../context/TelemetryContext';
import { useAgents } from '../context/AgentsContext';
import { useConnection } from '../context/ConnectionContext';

// ─── IDLE ─────────────────────────────────────────────────────────────
// Pre-seed state: system ready, waiting for user to enter a seed + Run.
export function IdleState({ seed }) {
  return (
    <div className="state-overlay">
      <div className="state-center idle-center">
        <div className="idle-ring">
          <div className="idle-ring-inner" />
        </div>
        <div className="state-kicker label">READY</div>
        <div className="state-headline">Swarm is dormant.</div>
        <div className="state-sub">
          {seed
            ? `Seed staged: "${seed}". Press Run when ready.`
            : 'Enter a market-moving scenario as a seed. 100 agents will be spawned across 10 brackets and deliberate across 3 rounds.'}
        </div>
        <div className="idle-grid">
          {/* KR-41.1-02: system-check labels are fixture text — backend does
              not yet surface per-subsystem readiness via /ws/state. */}
          <SystemCheck label="Ollama" value="worker + orchestrator" ok />
          <SystemCheck label="Agents" value="100 ready · 10 brackets" ok />
          <SystemCheck label="Data sources" value="configured via keys.toml" ok />
          <SystemCheck label="Storage" value="~/.alphaswarm" ok />
        </div>
        <div className="idle-hint label">
          TIP · press <kbd>R</kbd> to run · <kbd>S</kbd> to seed · <kbd>?</kbd> for shortcuts
        </div>
      </div>
    </div>
  );
}
function SystemCheck({ label, value, ok }) {
  return (
    <div className="syscheck">
      <span className={`syscheck-dot ${ok ? 'ok' : 'err'}`} />
      <span className="label">{label}</span>
      <span className="syscheck-val mono">{value}</span>
    </div>
  );
}

// ─── SEEDING ──────────────────────────────────────────────────────────
// Spawning 100 agents: show cascade of agent IDs lighting up.
// Plan 04: reads useAgents().agents directly — no setInterval fake counter.
export function SeedingState() {
  const { agents } = useAgents();
  const ids = agents.map((a) => a.id);
  const n = ids.length;
  const shown = ids.slice(-14).reverse();
  return (
    <div className="state-overlay">
      <div className="state-center seeding-center">
        <div className="state-kicker label" style={{ color: 'var(--accent)' }}>
          SEEDING · {String(n).padStart(3, '0')}/100
        </div>
        <div className="state-headline">Spawning agents…</div>
        <div className="seeding-bar">
          <div className="seeding-bar-fill" style={{ width: `${Math.min(n, 100)}%` }} />
        </div>
        <div className="seeding-stream mono">
          {shown.map((id, i) => (
            <div
              key={id}
              className="seeding-line"
              style={{ opacity: 1 - i * 0.08 }}
            >
              <span style={{ color: 'var(--buy)' }}>+ spawn </span>
              <span style={{ color: 'var(--accent)' }}>{id}</span>
              <span style={{ color: 'var(--text-3)' }}>
                {' '}
                · persona loaded · context primed
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── MEMORY PAUSED ────────────────────────────────────────────────────
// Inference halted because RAM crossed threshold.
// Plan 04: memPct comes from telemetry via LifecycleOverlay; labels marked
// KR-41.1-04 (backend emits percent only, GB conversion not available).
export function MemoryPausedState({ onResume, memPct }) {
  const pct = Math.max(0, Math.min(100, memPct ?? 91));
  return (
    <div className="state-overlay dim">
      <div className="state-center mempaused-center">
        <div className="mempaused-icon">
          <svg
            viewBox="0 0 48 48"
            width="56"
            height="56"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          >
            <rect x="6" y="14" width="36" height="20" rx="2" />
            <path d="M14 14 V34 M22 14 V34 M30 14 V34 M38 14 V34" />
            <circle cx="24" cy="42" r="2" fill="currentColor" />
          </svg>
        </div>
        <div className="state-kicker label" style={{ color: 'var(--sell)' }}>
          MEMORY CEILING · {pct.toFixed(0)}%
        </div>
        <div className="state-headline">Inference paused.</div>
        <div className="state-sub">
          RAM usage crossed the threshold you set in settings. Agents have
          checkpointed; resume when safe, or lower the concurrent-slots ceiling.
        </div>
        <div className="mempaused-meter">
          <div className="mempaused-bar">
            <div className="mempaused-fill" style={{ width: `${pct}%` }} />
            <div className="mempaused-threshold" style={{ left: '90%' }} />
          </div>
          {/* KR-41.1-04: backend emits memory_percent only; absolute GB
              figures are not yet available from the broadcaster. */}
          <div className="mempaused-legend mono">
            <span>{pct.toFixed(0)}% used</span>
            <span style={{ color: 'var(--sell)' }}>▲ threshold 90%</span>
          </div>
        </div>
        <div className="state-actions">
          <button className="btn primary" onClick={onResume}>
            Resume inference
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── ERROR ────────────────────────────────────────────────────────────
// Plan 04: reads useConnection() and log errors to console.
// KR-41.1-08: structured per-error log lines below are illustrative —
// backend does not yet stream structured error events over /ws/state.
export function ErrorState({ onRetry, error }) {
  const conn = useConnection();
  // KR-41.1-08: surface operator-visible error via console.error plus a
  // friendly message. Structured error log rows below are design fixtures
  // (no backend stream of per-error events yet).
  if (error) {
    // eslint-disable-next-line no-console
    console.error('ErrorState surfaced', error);
  }
  return (
    <div className="state-overlay dim">
      <div className="state-center error-center">
        <div className="error-glyph">
          <svg
            viewBox="0 0 48 48"
            width="56"
            height="56"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          >
            <path d="M24 6 L42 38 H6 Z" />
            <path d="M24 18 V26 M24 30 V32" />
          </svg>
        </div>
        <div className="state-kicker label" style={{ color: 'var(--sell)' }}>
          CONNECTION LOST
        </div>
        <div className="state-headline">Lost connection to the swarm.</div>
        <div className="state-sub">
          {conn.reconnectFailed
            ? 'WebSocket reconnect failed after the retry budget was exhausted. The backend may be down, or the bridge has been interrupted.'
            : 'The UI lost its connection to the backend. Retrying…'}
        </div>
        <div className="error-log mono">
          {/* KR-41.1-08: rows below are illustrative; backend does not yet
              expose a ring buffer of recent errors over /ws/state. */}
          <div>
            <span className="log-time">--:--:--.---</span>{' '}
            <span style={{ color: 'var(--sell)' }}>ERROR</span> reconnect budget exhausted
          </div>
          <div>
            <span className="log-time">--:--:--.---</span>{' '}
            <span style={{ color: 'var(--text-3)' }}>INFO</span>{' '}
            overlay.pause(preserve=true)
          </div>
        </div>
        <div className="state-actions">
          <button className="btn primary" onClick={onRetry}>
            Retry from checkpoint
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── LIFECYCLE OVERLAY ────────────────────────────────────────────────
// Single entry consumed by app roots. Decision table is inlined below
// rather than living in a separate hook (per prompt <do_not>: no new
// hooks in Plan 04 scope).
export function LifecycleOverlay({
  seed,
  onResume,
  onRetry,
  memThresholdPct = 90,
}) {
  const tel = useTelemetry();
  const conn = useConnection();

  if (conn.reconnectFailed) {
    return <ErrorState onRetry={onRetry} />;
  }
  const phase = tel.phase;
  if (phase === 'idle') return <IdleState seed={seed} />;
  if (phase === 'seeding') return <SeedingState />;
  const memPct = tel.telemetry?.memMb ?? 0;
  if (memPct >= memThresholdPct) {
    return <MemoryPausedState memPct={memPct} onResume={onResume} />;
  }
  return null;
}
