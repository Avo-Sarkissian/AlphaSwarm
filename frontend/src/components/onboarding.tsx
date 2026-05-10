// Onboarding — 3-step first-run flow (real-wired per D-12 / KR-41.6-04).
//
// Source: AlphaSwarm-2/src/onboarding.jsx (204 LOC, CDN-globals format).
// Conversion notes per RESEARCH.md wiring map row 27:
//   - ObStep1 ollamaOk = true mock REPLACED with /api/health fetch — KR-41.6-04
//     coarse gate (status==='ok'); no per-model status from backend.
//   - Model list rendered as design copy (no /api/settings to wire); cosmetic only.
//   - ObStep2 (seed) Run button wired to simStart(seed) before invoking onComplete().
//   - Source's CDN-globals export DELETED — module export only (no global pollution).
//
// onComplete signature: (seed: string, model: string) => void.
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
  onComplete: (seed: string, model: string) => void;
}

export function Onboarding({ onComplete }: OnboardingProps) {
  const [step, setStep] = useState<0 | 1 | 2>(0);
  const [model, setModel] = useState<string>('qwen3:8b');
  const [seed, setSeed] = useState<string>('');

  const seeds = [
    'Fed cuts 50bp at emergency session',
    'TSMC Arizona fab delayed 18 months',
    'China announces rare-earth export restrictions',
  ];

  const next = () => setStep((s) => (Math.min(2, s + 1) as 0 | 1 | 2));
  const back = () => setStep((s) => (Math.max(0, s - 1) as 0 | 1 | 2));

  return (
    <div className="ob-backdrop">
      <div className="ob-card">
        {/* step dots */}
        <div className="ob-steps">
          {[0, 1, 2].map((i) => (
            <div key={i} className="ob-dot" data-active={step === i} data-done={step > i} />
          ))}
        </div>

        {step === 0 && <ObStep0 onNext={next} />}
        {step === 1 && (
          <ObStep1 model={model} setModel={setModel} onNext={next} onBack={back} />
        )}
        {step === 2 && (
          <ObStep2
            seed={seed}
            setSeed={setSeed}
            seeds={seeds}
            onBack={back}
            onComplete={(finalSeed) => onComplete(finalSeed, model)}
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
          Feed it a market rumor. Watch 100 AI personas — quants, degens, whales,
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
// Step 1 — Model + Ollama check (KR-41.6-04 coarse gate via /api/health)
// ────────────────────────────────────────────────────────────────────────────
interface ObStep1Props {
  model: string;
  setModel: (m: string) => void;
  onNext: () => void;
  onBack: () => void;
}

function ObStep1({ model, setModel, onNext, onBack }: ObStep1Props) {
  // null = loading; true = backend reachable + simulation phase known; false = unreachable.
  const [ollamaOk, setOllamaOk] = useState<boolean | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiFetch<HealthResponse>('/api/health')
      .then((h) => {
        if (cancelled) return;
        setOllamaOk(h.status === 'ok');
        setHealthError(null);
      })
      .catch((e) => {
        if (cancelled) return;
        setOllamaOk(false);
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

  // Model list — design copy per RESEARCH.md row 27. NO /api/settings to wire;
  // selection is purely cosmetic. Default = qwen3:8b (Phase 41.4 lock — matches
  // src/alphaswarm/config.py:32 OllamaSettings.worker_model).
  const models = [
    { k: 'qwen3:8b', size: '5.2 GB', ram: '12 GB', quality: 'good', speed: 'fast', recommended: true },
    { k: 'llama3.3:70b', size: '42 GB', ram: '48 GB', quality: 'excellent', speed: 'medium', recommended: false },
    { k: 'mistral-small3', size: '14 GB', ram: '18 GB', quality: 'very good', speed: 'fast', recommended: false },
    { k: 'qwen2.5:72b', size: '47 GB', ram: '52 GB', quality: 'excellent', speed: 'slow', recommended: false },
  ];

  const statusLabel =
    ollamaOk === null
      ? 'Checking backend…'
      : ollamaOk
      ? 'Backend OK · /api/health responded'
      : `Backend unreachable${healthError ? ` · ${healthError}` : ''}`;

  return (
    <div className="ob-step ob-step-model">
      <div className="ob-content ob-content-wide">
        <div className="ob-kicker label">STEP 2 OF 3</div>
        <h2 className="ob-section-title">Choose your model</h2>
        <p className="ob-sub">AlphaSwarm uses Ollama for local inference. Pick a model that fits your RAM.</p>

        <div className="ob-ollama-status" data-ok={ollamaOk === true}>
          <span className={`ob-status-dot ${ollamaOk === true ? 'ok' : ollamaOk === false ? 'err' : ''}`} />
          <span className="mono" style={{ fontSize: 12 }}>{statusLabel}</span>
        </div>

        <div className="ob-model-list">
          {models.map((m) => (
            <button
              key={m.k}
              className="ob-model-row"
              data-active={model === m.k}
              onClick={() => setModel(m.k)}
            >
              <div className="ob-model-left">
                <div className="ob-model-radio" data-active={model === m.k} />
                <div>
                  <div className="ob-model-name mono">
                    {m.k}
                    {m.recommended && <span className="ob-rec-badge">recommended</span>}
                  </div>
                  <div className="ob-model-meta">
                    {m.size} · needs {m.ram} RAM · speed: {m.speed} · quality: {m.quality}
                  </div>
                </div>
              </div>
            </button>
          ))}
        </div>

        <div className="ob-model-foot label">
          Model selection wires in v6.x (render-only here). Default matches the orchestrator's worker model.
        </div>

        <div className="ob-btns">
          <button className="btn ghost" onClick={onBack}>← Back</button>
          <button
            className="btn primary"
            onClick={onNext}
            disabled={ollamaOk !== true}
          >
            {ollamaOk === true ? 'Continue →' : ollamaOk === null ? 'Checking…' : 'Start backend first'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────────────
// Step 2 — First seed + Run (wires to simStart)
// ────────────────────────────────────────────────────────────────────────────
interface ObStep2Props {
  seed: string;
  setSeed: (s: string) => void;
  seeds: string[];
  onBack: () => void;
  onComplete: (seed: string) => void;
}

function ObStep2({ seed, setSeed, seeds, onBack, onComplete }: ObStep2Props) {
  const [runError, setRunError] = useState<string | null>(null);
  const [busy, setBusy] = useState<boolean>(false);

  const handleRun = async () => {
    const trimmed = seed.trim();
    if (!trimmed || busy) return;
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
        <div className="ob-kicker label">STEP 3 OF 3</div>
        <h2 className="ob-section-title">Enter a seed rumor</h2>
        <p className="ob-sub">
          A market-moving scenario for the swarm to debate. Be specific — the orchestrator
          extracts entities to shape each agent's context.
        </p>

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
          <span>The orchestrator will extract entities from your seed and inject situation-specific context into each agent's prompt.</span>
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
            disabled={!seed.trim() || busy}
            onClick={() => void handleRun()}
          >
            <Icon name="play" /> {busy ? 'Starting…' : 'Run first cycle'}
          </button>
        </div>
      </div>
    </div>
  );
}
