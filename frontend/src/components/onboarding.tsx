// Onboarding — 2-step first-run flow (real-wired per docs/DECISIONS.md#p41-6-d-12 / #kr-41-6-04).
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
import { InlineError } from './InlineError';
import { apiFetch } from '../api/client';
import { useRunGate } from '../hooks/useRunGate';
import { formatApiError } from '../lib/apiError';
import { parseHealth, type HealthSummary } from '../lib/health';
import { SEED_MAX_LENGTH, seedProblem } from '../lib/seed';

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
  // Health gate (/api/health components): Run needs every required component ok. A degraded
  // backend lists what is down with its fix; Re-check asks again without a reload
  // (docs/DECISIONS.md#p41-6-d-12).
  const [health, setHealth] = useState<HealthSummary | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [checkSeq, setCheckSeq] = useState(0);
  const backendOk = health?.status === 'ok';

  // Run gate: cost confirmation for cloud/mixed runs, then simStart. It settles
  // on success, failure and cancel alike, so the button never stays on
  // "Starting…".
  const { requestRun, modal: runConfirmModal, error: runError, pending } = useRunGate({
    onSettled: (ok) => {
      if (ok) onComplete(seed.trim());
    },
  });

  useEffect(() => {
    let cancelled = false;
    apiFetch<unknown>('/api/health')
      .then((raw) => {
        if (!cancelled) setHealth(parseHealth(raw));
      })
      .catch((e: unknown) => {
        if (!cancelled) setHealthError(formatApiError(e));
      });
    return () => {
      cancelled = true;
    };
  }, [checkSeq]);

  // Clears the last answer before asking again, so the status reads "Checking backend…".
  const recheck = () => {
    setHealth(null);
    setHealthError(null);
    setCheckSeq((n) => n + 1);
  };

  const statusLabel =
    healthError !== null
      ? `Backend unreachable · ${healthError}`
      : health === null
        ? 'Checking backend…'
        : health.status === 'ok'
          ? 'Backend ready · all required components OK'
          : health.status === 'degraded'
            ? `Backend degraded · ${health.down.length} component(s) need attention`
            : 'Backend answered without a status · re-check';
  const seedIssue = seedProblem(seed);

  const handleRun = () => {
    if (seedIssue !== null || pending || !backendOk) return;
    requestRun(seed.trim());
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

        <div className="ob-ollama-status" data-ok={backendOk}>
          <span
            className={`ob-status-dot ${backendOk ? 'ok' : health !== null || healthError !== null ? 'err' : ''}`}
          />
          <span className="mono" style={{ fontSize: 12 }}>{statusLabel}</span>
        </div>
        {health !== null && health.down.length > 0 && (
          <ul className="ob-health-down">
            {health.down.map((c) => (
              <li key={c.name}>
                <span className="mono">{c.name}</span>
                {c.detail && <span className="ob-health-detail"> — {c.detail}</span>}
                {c.fix && <code className="ob-health-fix">{c.fix}</code>}
              </li>
            ))}
          </ul>
        )}
        {!backendOk && (health !== null || healthError !== null) && (
          <button type="button" className="btn ghost" onClick={recheck}>
            Re-check
          </button>
        )}

        <div className="ob-seed-input">
          <span className="ob-seed-prefix label">SEED ⟶</span>
          <input
            autoFocus
            value={seed}
            onChange={(e) => setSeed(e.target.value)}
            placeholder="e.g. Fed announces emergency rate cut…"
            maxLength={SEED_MAX_LENGTH}
            aria-label="Seed rumor"
            disabled={pending}
          />
        </div>

        <div className="ob-seed-examples">
          <div className="label" style={{ marginBottom: 8 }}>OR TRY ONE OF THESE</div>
          {seeds.map((s) => (
            <button key={s} className="ob-example" onClick={() => setSeed(s)} disabled={pending}>
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

        <InlineError error={runError} />

        <div className="ob-btns">
          <button className="btn ghost" onClick={onBack} disabled={pending}>← Back</button>
          <button className="btn ghost" onClick={() => onComplete('')} disabled={pending}>
            Skip to dashboard
          </button>
          <button
            className="btn primary"
            disabled={seedIssue !== null || pending || !backendOk}
            title={seedIssue ?? undefined}
            onClick={handleRun}
          >
            <Icon name="play" />{' '}
            {pending
              ? 'Starting…'
              : healthError !== null
                ? 'Start backend first'
                : health !== null && !backendOk
                  ? 'Fix the items above first'
                  : 'Run first cycle'}
          </button>
        </div>
      </div>
      {runConfirmModal}
    </div>
  );
}
