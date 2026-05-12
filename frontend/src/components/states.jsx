// v2 states — idle, seeding, memory-paused, error, empty-cycles.
// Each is a full-canvas overlay that replaces the force graph.
//
// Lifted from AlphaSwarm-2/src/states.jsx (W2 Plan 41.6-02 task 2) and
// converted to ES modules per D-03. Sourced design's BRACKETS reference is
// replaced with the import from '../data' per D-14.
import { useEffect, useState } from 'react';
import { Icon } from './icons';
import { BRACKETS } from '../data';

// ─── IDLE ─────────────────────────────────────────────────────────────
// Pre-seed state: system ready, waiting for user to enter a seed + Run.
// SystemCheck rows: Ollama RAM matches CLAUDE.md M1 Max 64GB target;
// Agents/brackets derived from BRACKETS (CONTRACT §6 source of truth);
// Data sources discloses mocked status (KR-41.1-02); Storage drops the
// fabricated byte count. KR-41.6-11 partial closure — full live probes
// (real Ollama health, disk usage) still pending W4 Onboarding wiring.
export function IdleState({ seed, setSeed, onStart, ollamaOk = true, onShowHistory }) {
  const totalPersonas = BRACKETS.reduce((sum, b) => sum + b.count, 0);
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
        {/* Optional inline seed editor + Run handler — used when the parent
            wants to mount IdleState as a true pre-run gate. The Topbar's
            seed input is the canonical entry; these props are no-ops if not
            supplied. KR-41.6-11: SystemCheck rows below are design copy. */}
        {setSeed && (
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', margin: '12px 0' }}>
            <input
              value={seed || ''}
              onChange={(e) => setSeed(e.target.value)}
              placeholder="Seed rumor…"
              style={{
                flex: 1, padding: '6px 10px', background: 'var(--bg-2)',
                border: '1px solid var(--border-2)', color: 'var(--text)',
                fontFamily: "'JetBrains Mono', monospace", fontSize: 11,
              }}
            />
            {onStart && (
              <button className="btn primary" onClick={onStart}>
                <Icon name="play" /> Run
              </button>
            )}
          </div>
        )}
        <div className="idle-grid">
          <SystemCheck label="Ollama" value="qwen3:8b · 64GB RAM" ok={ollamaOk} />
          <SystemCheck label="Agents" value={`${totalPersonas} personas · ${BRACKETS.length} brackets`} ok />
          <SystemCheck label="Data sources" value="mocked · pending live wire" ok />
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
// Spawning 100 agents: show cascade of agent IDs lighting up by bracket.
export function SeedingState({ seed }) {
  const [n, setN] = useState(0);
  useEffect(() => {
    const iv = setInterval(() => setN(x => (x >= 100 ? 100 : x + 3)), 80);
    return () => clearInterval(iv);
  }, []);
  return (
    <div className="state-overlay">
      <div className="state-center seeding-center">
        <div className="state-kicker label" style={{color: 'var(--accent)'}}>
          SEEDING · {String(n).padStart(3,'0')}/100
        </div>
        <div className="state-headline">Spawning agents…</div>
        {seed && (
          <div className="state-sub mono" style={{ fontSize: 11, opacity: 0.8 }}>
            seed: "{seed}"
          </div>
        )}
        <div className="seeding-bar">
          <div className="seeding-bar-fill" style={{width: `${n}%`}} />
        </div>
        <div className="seeding-stream mono">
          {BRACKETS.flatMap(b => {
            const arr = [];
            const prefix = { Quants:'Q', Degens:'D', Sovereigns:'S', Macro:'M', Suits:'U', Insiders:'I', Agents:'A', 'Doom-Posters':'X', 'Policy Wonks':'P', Whales:'W' }[b.display];
            for (let i = 1; i <= b.count; i++) arr.push(`${prefix}-${String(i).padStart(2,'0')}`);
            return arr;
          }).slice(0, n).reverse().slice(0, 14).map((id, i) => (
            <div key={id} className="seeding-line" style={{opacity: 1 - i*0.08}}>
              <span style={{color: 'var(--buy)'}}>+ spawn </span>
              <span style={{color: 'var(--accent)'}}>{id}</span>
              <span style={{color: 'var(--text-3)'}}> · persona loaded · context primed</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── MEMORY PAUSED ────────────────────────────────────────────────────
// Inference halted because RAM crossed threshold.
// KR-41.1-04: GB legend literal stays as design placeholder (backend emits
// percent only; no MB conversion available).
export function MemoryPausedState({ pct, onResume }) {
  const memPct = Math.max(0, Math.min(100, pct ?? 91));
  return (
    <div className="state-overlay dim">
      <div className="state-center mempaused-center">
        <div className="mempaused-icon">
          <svg viewBox="0 0 48 48" width="56" height="56" fill="none" stroke="currentColor" strokeWidth="2">
            <rect x="6" y="14" width="36" height="20" rx="2"/>
            <path d="M14 14 V34 M22 14 V34 M30 14 V34 M38 14 V34"/>
            <circle cx="24" cy="42" r="2" fill="currentColor"/>
          </svg>
        </div>
        <div className="state-kicker label" style={{color: 'var(--sell)'}}>MEMORY CEILING · {memPct.toFixed(0)}%</div>
        <div className="state-headline">Inference paused.</div>
        <div className="state-sub">
          RAM usage crossed the 90% threshold you set in settings.
          Agents have checkpointed; resume when safe, or lower the concurrent-slots ceiling.
        </div>
        <div className="mempaused-meter">
          <div className="mempaused-bar">
            <div className="mempaused-fill" style={{width: `${memPct}%`}} />
            <div className="mempaused-threshold" style={{left: '90%'}} />
          </div>
          <div className="mempaused-legend mono">
            {/* KR-41.1-04: GB literal stays — backend emits percent only. */}
            <span>43.7 / 48.0 GB</span>
            <span style={{color: 'var(--sell)'}}>▲ threshold 90%</span>
          </div>
        </div>
        <div className="state-actions">
          <button className="btn primary" onClick={onResume}>Resume inference</button>
          <button className="btn ghost">Lower slots to 6</button>
          <button className="btn ghost">Adjust threshold</button>
        </div>
      </div>
    </div>
  );
}

// ─── ERROR ────────────────────────────────────────────────────────────
// KR-41.1-08: structured event log lines are design copy (no backend
// structured error stream yet). Trigger comes from useConnection().reconnectFailed
// in app_v2.tsx.
export function ErrorState({ onRetry }) {
  return (
    <div className="state-overlay dim">
      <div className="state-center error-center">
        <div className="error-glyph">
          <svg viewBox="0 0 48 48" width="56" height="56" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M24 6 L42 38 H6 Z"/>
            <path d="M24 18 V26 M24 30 V32"/>
          </svg>
        </div>
        <div className="state-kicker label" style={{color: 'var(--sell)'}}>
          RUNTIME ERROR · ollama-rpc
        </div>
        <div className="state-headline">Lost connection to Ollama.</div>
        <div className="state-sub">
          Agent <span className="mono" style={{color:'var(--accent)'}}>M-06</span> returned a malformed response
          on round 2. The swarm has been paused to preserve state.
        </div>
        <div className="error-log mono">
          {/* KR-41.1-08: rows below are design copy — backend has no structured error stream. */}
          <div><span className="log-time">09:42:18.203</span> <span style={{color:'var(--sell)'}}>ERROR</span> M-06 parse_error: expected JSON, got plaintext</div>
          <div><span className="log-time">09:42:18.204</span> <span style={{color:'var(--accent)'}}>WARN</span>  retry 1/3 · backoff 250ms</div>
          <div><span className="log-time">09:42:18.461</span> <span style={{color:'var(--sell)'}}>ERROR</span> M-06 parse_error: expected JSON, got plaintext</div>
          <div><span className="log-time">09:42:18.462</span> <span style={{color:'var(--accent)'}}>WARN</span>  retry 2/3 · backoff 500ms</div>
          <div><span className="log-time">09:42:18.968</span> <span style={{color:'var(--sell)'}}>ERROR</span> ollama_rpc: ECONNRESET</div>
          <div><span className="log-time">09:42:18.969</span> <span style={{color:'var(--text-3)'}}>INFO</span>  swarm.pause(preserve=true)</div>
        </div>
        <div className="state-actions">
          <button className="btn primary" onClick={onRetry}>Retry from checkpoint</button>
          <button className="btn ghost">Quarantine M-06</button>
          <button className="btn ghost">Open ollama logs</button>
        </div>
      </div>
    </div>
  );
}
