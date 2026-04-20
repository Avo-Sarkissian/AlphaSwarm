// v2 states — idle, seeding, memory-paused, error, empty-cycles.
// Each is a full-canvas overlay that replaces the force graph.
// WAVE-1-NOTE: BRACKETS inlined as a local static constant. The seeding state
// is a pre-run visual overlay, not a live-data surface, so it does not need
// to pull from the agents/bracket contexts. Wave 2 can replace with real counts
// from BracketContext if the PM wants cycle-specific seed counts.
import { useState, useEffect } from 'react';

const BRACKETS = [
  { display: 'Quants',       count: 14 },
  { display: 'Degens',       count: 12 },
  { display: 'Sovereigns',   count: 8  },
  { display: 'Macro',        count: 12 },
  { display: 'Suits',        count: 10 },
  { display: 'Insiders',     count: 10 },
  { display: 'Agents',       count: 10 },
  { display: 'Doom-Posters', count: 8  },
  { display: 'Policy Wonks', count: 8  },
  { display: 'Whales',       count: 8  },
];

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
          Enter a market-moving scenario as a seed. 100 agents will be spawned
          across 10 brackets and deliberate across 3 rounds.
        </div>
        <div className="idle-grid">
          <SystemCheck label="Ollama" value="llama3.3:70b · 48GB RAM" ok />
          <SystemCheck label="Agents" value="100 ready · 10 brackets" ok />
          <SystemCheck label="Data sources" value="10 online · 0 errors" ok />
          <SystemCheck label="Storage" value="~/.alphaswarm · 2.1GB used" ok />
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
export function SeedingState() {
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
export function MemoryPausedState({ onResume }) {
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
        <div className="state-kicker label" style={{color: 'var(--sell)'}}>MEMORY CEILING · 91%</div>
        <div className="state-headline">Inference paused.</div>
        <div className="state-sub">
          RAM usage crossed the 90% threshold you set in settings.
          Agents have checkpointed; resume when safe, or lower the concurrent-slots ceiling.
        </div>
        <div className="mempaused-meter">
          <div className="mempaused-bar">
            <div className="mempaused-fill" style={{width: '91%'}} />
            <div className="mempaused-threshold" style={{left: '90%'}} />
          </div>
          <div className="mempaused-legend mono">
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
