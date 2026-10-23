// v2 states — idle and seeding.
// Idle and seeding are overlays inside the dashboard canvas (.canvas-wrap);
// the shell stays visible around them. A lost or stalled WebSocket shows the
// global ConnectionBanner instead of a takeover, and a governor pause shows a
// dismissible banner.
//
// Lifted from AlphaSwarm-2/src/states.jsx (W2 Plan 41.6-02 task 2) and
// converted to ES modules (docs/DECISIONS.md#p41-6-d-03). Sourced design's
// BRACKETS reference is replaced with the import from '../data'
// (docs/DECISIONS.md#p41-6-d-14).
import { Icon } from './icons';
import { BRACKETS } from '../data';
import { fetchHealth } from '../api/health';
import { usePolling } from '../hooks/usePolling';
import { formatDuration } from '../lib/format';
import { systemChecks } from '../lib/systemChecks';

// ─── IDLE ─────────────────────────────────────────────────────────────
// Overlay inside the dashboard canvas while idle: the topbar (seed, Run,
// Settings, replay) stays usable above it. The seed is entered in
// the topbar only. System-check rows come from /api/health components
// (docs/DECISIONS.md#kr-41-6-11).
/** @param {{ seed: string, numRounds: number, onShowHistory?: () => void }} props */
export function IdleState({ seed, numRounds, onShowHistory }) {
  const totalPersonas = BRACKETS.reduce((sum, b) => sum + b.count, 0);
  const { data: health, error } = usePolling({ key: 'health-idle', fetchFn: fetchHealth, intervalMs: 10_000 });
  const rows = systemChecks(health, error, { personas: totalPersonas, brackets: BRACKETS.length });
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
            : `Enter a market-moving scenario in the seed bar above. ${totalPersonas} agents across ${BRACKETS.length} brackets will deliberate over ${numRounds} rounds.`}
        </div>
        {onShowHistory && (
          <button
            type="button"
            className="idle-history-btn"
            onClick={onShowHistory}
            title="Browse and replay previous simulation cycles"
          >
            <Icon name="replay" size={13} />
            <span>Browse previous runs</span>
          </button>
        )}
        <div className="idle-grid">
          {rows.map((r) => (
            <SystemCheck key={r.label} {...r} />
          ))}
        </div>
      </div>
    </div>
  );
}
function SystemCheck({ label, value, state, fix }) {
  return (
    <div className="syscheck" data-state={state}>
      <span className={`syscheck-dot ${state}`} />
      <span className="label">{label}</span>
      <span className="syscheck-val mono">{value}</span>
      {fix && <code className="syscheck-fix mono">{fix}</code>}
    </div>
  );
}

// ─── SEEDING ──────────────────────────────────────────────────────────
// While the phase is SEEDING the orchestrator parses the seed into entities
// and persona modifiers, then market prices and headlines are fetched. There
// is no per-agent progress at this stage, so none is shown.
export function SeedingState({ seed, elapsedSeconds = 0 }) {
  return (
    <div className="state-overlay">
      <div className="state-center seeding-center">
        <div className="state-kicker label" style={{ color: 'var(--accent)' }}>
          SEEDING · {formatDuration(elapsedSeconds)}
        </div>
        <div className="state-headline">Preparing the swarm…</div>
        <div className="state-sub">
          The orchestrator is parsing the seed into entities and persona modifiers; market prices
          and headlines are fetched next. Round 1 starts when both are done.
        </div>
        {seed && (
          <div className="state-sub mono" style={{ fontSize: 11, opacity: 0.8 }}>
            seed: "{seed}"
          </div>
        )}
      </div>
    </div>
  );
}
