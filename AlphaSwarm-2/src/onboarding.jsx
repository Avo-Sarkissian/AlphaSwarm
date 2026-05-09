// Onboarding — 3-step first-run flow.
// Step 1: What is AlphaSwarm (animated swarm preview)
// Step 2: Check Ollama + model selection
// Step 3: Enter first seed → Run

const { useState: useOB, useEffect: useOE } = React;

function Onboarding({ onComplete }) {
  const [step, setStep] = useOB(0); // 0,1,2
  const [model, setModel] = useOB('llama3.3:70b');
  const [seed, setSeed] = useOB('');
  const [ollamaOk] = useOB(true); // mock
  const seeds = [
    'Apple acquiring Anthropic for $500B',
    'Fed cuts 50bp at emergency session',
    'TSMC Arizona fab delayed 18 months',
    'China announces rare-earth export restrictions',
  ];

  const next = () => setStep(s => Math.min(2, s + 1));
  const back = () => setStep(s => Math.max(0, s - 1));

  return (
    <div className="ob-backdrop">
      <div className="ob-card">
        {/* step dots */}
        <div className="ob-steps">
          {[0,1,2].map(i => (
            <div key={i} className="ob-dot" data-active={step === i} data-done={step > i} />
          ))}
        </div>

        {step === 0 && <ObStep0 onNext={next} />}
        {step === 1 && <ObStep1 model={model} setModel={setModel} ollamaOk={ollamaOk} onNext={next} onBack={back} />}
        {step === 2 && <ObStep2 seed={seed} setSeed={setSeed} seeds={seeds} onBack={back} onComplete={() => onComplete(seed, model)} />}
      </div>
    </div>
  );
}

// Step 0: What is AlphaSwarm
function ObStep0({ onNext }) {
  const [tick, setTick] = useOB(0);
  useOE(() => {
    const iv = setInterval(() => setTick(t => t + 1), 120);
    return () => clearInterval(iv);
  }, []);

  // 100 dots, animate colors over time
  const dots = Array.from({length: 100}, (_, i) => {
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
            <div key={i} className="ob-swarm-dot" style={{
              background: d.color,
              transform: `scale(${d.scale})`,
              opacity: 0.7 + d.scale * 0.3,
            }} />
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
          <div className="ob-pill"><span style={{color:'var(--buy)'}}>●</span> BUY</div>
          <div className="ob-pill"><span style={{color:'var(--sell)'}}>●</span> SELL</div>
          <div className="ob-pill"><span style={{color:'var(--hold)'}}>●</span> HOLD</div>
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

// Step 1: Model + Ollama check
function ObStep1({ model, setModel, ollamaOk, onNext, onBack }) {
  const models = [
    { k: 'llama3.3:70b',    size: '42 GB', ram: '48 GB', quality: 'excellent', speed: 'medium',  recommended: true },
    { k: 'mistral-small3',  size: '14 GB', ram: '18 GB', quality: 'very good', speed: 'fast',    recommended: false },
    { k: 'llama3.1:8b',     size: '4.7 GB', ram: '8 GB', quality: 'good',      speed: 'fast',    recommended: false },
    { k: 'qwen2.5:72b',     size: '47 GB', ram: '52 GB', quality: 'excellent', speed: 'slow',    recommended: false },
  ];

  return (
    <div className="ob-step ob-step-model">
      <div className="ob-content ob-content-wide">
        <div className="ob-kicker label">STEP 2 OF 3</div>
        <h2 className="ob-section-title">Choose your model</h2>
        <p className="ob-sub">AlphaSwarm uses Ollama for local inference. Pick a model that fits your RAM.</p>

        <div className="ob-ollama-status" data-ok={ollamaOk}>
          <span className={`ob-status-dot ${ollamaOk ? 'ok' : 'err'}`} />
          <span className="mono" style={{fontSize: 12}}>
            {ollamaOk ? 'Ollama running · localhost:11434' : 'Ollama not detected — start it first'}
          </span>
          {!ollamaOk && (
            <button className="btn ghost" style={{marginLeft: 'auto', height: 26}}>
              Install Ollama →
            </button>
          )}
        </div>

        <div className="ob-model-list">
          {models.map(m => (
            <button key={m.k} className="ob-model-row"
              data-active={model === m.k}
              onClick={() => setModel(m.k)}>
              <div className="ob-model-left">
                <div className="ob-model-radio" data-active={model === m.k} />
                <div>
                  <div className="ob-model-name mono">{m.k}
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
          Don't have the model yet?
          <span className="mono" style={{color:'var(--accent)', marginLeft: 8}}>ollama pull {model}</span>
        </div>

        <div className="ob-btns">
          <button className="btn ghost" onClick={onBack}>← Back</button>
          <button className="btn primary" onClick={onNext} disabled={!ollamaOk}>
            {ollamaOk ? 'Continue →' : 'Start Ollama first'}
          </button>
        </div>
      </div>
    </div>
  );
}

// Step 2: First seed
function ObStep2({ seed, setSeed, seeds, onBack, onComplete }) {
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
            onChange={e => setSeed(e.target.value)}
            placeholder="e.g. Apple acquiring Anthropic for $500B…"
          />
        </div>

        <div className="ob-seed-examples">
          <div className="label" style={{marginBottom: 8}}>OR TRY ONE OF THESE</div>
          {seeds.map(s => (
            <button key={s} className="ob-example" onClick={() => setSeed(s)}>
              "{s}"
            </button>
          ))}
        </div>

        <div className="ob-seed-hint">
          <Icon name="bolt" size={12} />
          <span>The orchestrator will extract entities from your seed and inject situation-specific context into each agent's prompt.</span>
        </div>

        <div className="ob-btns">
          <button className="btn ghost" onClick={onBack}>← Back</button>
          <button className="btn primary" disabled={!seed.trim()} onClick={() => onComplete()}>
            <Icon name="play" /> Run first cycle
          </button>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { Onboarding });
