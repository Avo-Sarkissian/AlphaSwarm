// Onboarding — 2-step first-run flow (real-wired per D-12 / KR-41.6-04).
//
// 2026-06-11: the old "Choose your model" step removed — it rendered a stale
// hardcoded model list (qwen3:8b / llama3.3:70b era) and was render-only
// anyway. Models are configured backend-side (src/alphaswarm/config.py /
// .env / modelfiles) and DISPLAYED in Settings → Model. The /api/health
// gate moved onto the seed step's Run button.
//
// onComplete signature: (seed: string) => void.
// App.tsx is responsible for setting the localStorage flag in its event handler
// (codex LOW-9 — never write localStorage during render).

import { useEffect, useState } from 'react';
import { Icon } from './icons';
import { apiFetch, ApiError } from '../api/client';
import { simStart } from '../api/simulation';

interface HealthResponse {
  status: string;
  simulation_phase?: string;
  memory_percent?: number;
  is_simulation_running?: boolean;
}

interface OnboardingProps {
  onComplete: (seed: string) => void;
}

export function Onboarding({ onComplete }: OnboardingProps) {
  const [step, setStep] = useState<0 | 1>(0);
  const [seed, setSeed] = useState<string>('');

  const seeds = [
    'Fed cuts 50bp at emergency session',
    'TSMC Arizona fab delayed 18 months',
    'China announces rare-earth export restrictions',
  ];

  const next = () => setStep(1);
  const back = () => setStep(0);

  return (
    <div className="ob-backdrop">
      <div className="ob-card">
        {/* step dots */}
        <div className="ob-steps">
          {[0, 1].map((i) => (
            <div key={i} className="ob-dot" data-active={step === i} data-done={step > i} />
          ))}
        </div>

        {step === 0 && <ObStep0 onNext={next} />}
        {step === 1 && (
          <ObSeedStep
            seed={seed}
            setSeed={setSeed}
            seeds={seeds}
            onBack={back}
            onComplete={onComplete}
          />
        )}
      </div>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────────────
// Step 0 — What is AlphaSwarm
// ────────────────────────────────────────────────────────────────────────────
function ObStep0({ onNext }: { onNext: () => void }) {
  const [tick, setTick] = useState<number>(0);
  useEffect(() => {
    const iv = setInterval(() => setTick((t) => t + 1), 120);
    return () => clearInterval(iv);
  }, []);

  // 100 dots, animate colors over time (visual flourish only).
  const dots = Array.from({ length: 100 }, (_, i) => {
    const r = ((i * 9301 + tick * 13) % 233280) / 233280;
    const phase = (i + tick * 0.4) % 100;
    const color = phase < 40 ? 'var(--buy)' : phase < 65 ? 'var(--sell)' : 'var(--hold)';
    return { color, scale: 0.7 + r * 0.6 };
  });

  return (
    <div className="ob-step">
      <div className="ob-hero-viz">
        <div className="ob-swarm">
          {dots.map((d, i) => (
            <div
              key={i}
              className="ob-swarm-dot"
              style={{
                background: d.color,
                transform: `scale(${d.scale})`,
                opacity: 0.7 + d.scale * 0.3,
              }}
            />
          ))}
        </div>
      </div>
      <div className="ob-content">
        <div className="ob-kicker label">WELCOME TO</div>
        <h1 className="ob-title">AlphaSwarm</h1>
        <p className="ob-lede">
          Feed it a market rumor. Watch 100 AI personas — quants, degens, short-sellers,
          policy wonks — debate it across 3 rounds and converge toward consensus.
          All inference runs locally. No cloud. No API keys. No data leaves your machine.
        </p>
        <div className="ob-pills">
          <div className="ob-pill"><span style={{ color: 'var(--buy)' }}>●</span> BUY</div>
          <div className="ob-pill"><span style={{ color: 'var(--sell)' }}>●</span> SELL</div>
          <div className="ob-pill"><span style={{ color: 'var(--hold)' }}>●</span> HOLD</div>
          <div className="ob-pill-divider" />
          <div className="ob-pill">100 agents</div>
          <div className="ob-pill">10 brackets</div>
          <div className="ob-pill">3 rounds</div>
        </div>
        <button className="btn primary ob-next" onClick={onNext}>Get started →</button>
      </div>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────────────
// Step 1 — Seed + Run (backend health gate + simStart)
// Models are configured backend-side; see Settings → Model for the active stack.
// ────────────────────────────────────────────────────────────────────────────
interface ObSeedStepProps {
  seed: string;
  setSeed: (s: string) => void;
  seeds: string[];
  onBack: () => void;
  onComplete: (seed: string) => void;
}

function ObSeedStep({ seed, setSeed, seeds, onBack, onComplete }: ObSeedStepProps) {
  const [runError, setRunError] = useState<string | null>(null);
  const [busy, setBusy] = useState<boolean>(false);
  // null = loading; true = backend reachable; false = unreachable (KR-41.6-04 gate).
  const [backendOk, setBackendOk] = useState<boolean | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiFetch<HealthResponse>('/api/health')
      .then((h) => {
        if (cancelled) return;
        setBackendOk(h.status === 'ok');
        setHealthError(null);
      })
      .catch((e) => {
        if (cancelled) return;
        setBackendOk(false);
        if (e instanceof ApiError) {
          setHealthError(`HTTP ${e.status}`);
        } else {
          setHealthError(e instanceof Error ? e.message : String(e));
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const statusLabel =
    backendOk === null
      ? 'Checking backend…'
      : backendOk
      ? 'Backend OK · /api/health responded'
      : `Backend unreachable${healthError ? ` · ${healthError}` : ''}`;

  const handleRun = async () => {
    const trimmed = seed.trim();
    if (!trimmed || busy || backendOk !== true) return;
    setBusy(true);
    setRunError(null);
    try {
      await simStart(trimmed);
      onComplete(trimmed);
    } catch (e) {
      setRunError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };

  return (
    <div className="ob-step ob-step-seed">
      <div className="ob-content ob-content-wide">
        <div className="ob-kicker label">STEP 2 OF 2</div>
        <h2 className="ob-section-title">Enter a seed rumor</h2>
        <p className="ob-sub">
          A market-moving scenario for the swarm to debate. Be specific — the orchestrator
          extracts entities to shape each agent's context.
        </p>

        <div className="ob-ollama-status" data-ok={backendOk === true}>
          <span className={`ob-status-dot ${backendOk === true ? 'ok' : backendOk === false ? 'err' : ''}`} />
          <span className="mono" style={{ fontSize: 12 }}>{statusLabel}</span>
        </div>

        <div className="ob-seed-input">
          <span className="ob-seed-prefix label">SEED ⟶</span>
          <input
            autoFocus
            value={seed}
            onChange={(e) => setSeed(e.target.value)}
            placeholder="e.g. Fed announces emergency rate cut…"
            disabled={busy}
          />
        </div>

        <div className="ob-seed-examples">
          <div className="label" style={{ marginBottom: 8 }}>OR TRY ONE OF THESE</div>
          {seeds.map((s) => (
            <button key={s} className="ob-example" onClick={() => setSeed(s)} disabled={busy}>
              "{s}"
            </button>
          ))}
        </div>

        <div className="ob-seed-hint">
          <Icon name="bolt" size={12} />
          <span>
            Models are pre-configured (Settings → Model). The orchestrator will extract
            entities from your seed and inject situation-specific context into each
            agent's prompt.
          </span>
        </div>

        {runError && (
          <div
            className="ob-seed-hint"
            style={{ color: 'var(--sell)', borderColor: 'var(--sell)' }}
          >
            <span>Run failed: {runError}</span>
          </div>
        )}

        <div className="ob-btns">
          <button className="btn ghost" onClick={onBack} disabled={busy}>← Back</button>
          <button
            className="btn primary"
            disabled={!seed.trim() || busy || backendOk !== true}
            onClick={() => void handleRun()}
          >
            <Icon name="play" />{' '}
            {busy
              ? 'Starting…'
              : backendOk === false
              ? 'Start backend first'
              : 'Run first cycle'}
          </button>
        </div>
      </div>
    </div>
  );
}
