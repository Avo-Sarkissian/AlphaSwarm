// What-if Compare — run two configurations side by side
// Watch Mode — scheduled seed runs
// Seed Suggestions — inspire panel
// Multi-seed Synthesis — run 3 seeds and synthesize
const { useState: useWI, useMemo: useWM, useEffect: useWE, useRef: useWR } = React;

// ── WHAT-IF COMPARE ──────────────────────────────────────────────────
function WhatIfCompare({ onClose }) {
  const { buildAgents, bracketSummaries } = window.AS_DATA;
  const [runA, setRunA] = useWI({ seed:'Apple acquiring Anthropic for $500B', phase:3, buy:0.30, sell:0.45, hold:0.25, model:'llama3.3:70b', label:'Run A' });
  const [runB, setRunB] = useWI({ seed:'DOJ blocks Apple–Anthropic deal', phase:3, buy:0.55, sell:0.28, hold:0.17, model:'llama3.3:70b', label:'Run B' });
  const [ran, setRan] = useWI(false);

  const agentsA = useWM(() => buildAgents(runA.phase, {buy:runA.buy,sell:runA.sell,hold:runA.hold}), [runA, ran]);
  const agentsB = useWM(() => buildAgents(runB.phase, {buy:runB.buy,sell:runB.sell,hold:runB.hold}), [runB, ran]);
  const sumA = useWM(() => bracketSummaries(agentsA), [agentsA]);
  const sumB = useWM(() => bracketSummaries(agentsB), [agentsB]);

  const buyA  = agentsA.filter(a=>a.signal==='buy').length;
  const sellA = agentsA.filter(a=>a.signal==='sell').length;
  const buyB  = agentsB.filter(a=>a.signal==='buy').length;
  const sellB = agentsB.filter(a=>a.signal==='sell').length;

  const consA = buyA>=sellA?'BUY':'SELL';
  const consB = buyB>=sellB?'BUY':'SELL';

  return (
    <div className="wi-takeover">
      <div className="wi-head">
        <button className="btn ghost-btn" onClick={onClose}><Icon name="close" /></button>
        <span className="wi-title">What-if Compare</span>
        <span className="label">CONFIGURE TWO SCENARIOS · SEE DIVERGENCE</span>
        <div className="sp" />
        <button className="btn primary" onClick={() => setRan(r=>!r)}><Icon name="play" /> Run both</button>
      </div>

      <div className="wi-body">
        {/* Config row */}
        <div className="wi-config-strip">
          {[{run:runA,setRun:setRunA,label:'A'},{run:runB,setRun:setRunB,label:'B'}].map(({run,setRun,label}) => (
            <div key={label} className="wi-config-col">
              <div className="wi-config-label">RUN {label}</div>
              <input className="wi-seed-input" value={run.seed}
                onChange={e => setRun(r=>({...r,seed:e.target.value}))}
                placeholder="Enter seed rumor…" />
              <div className="wi-config-row">
                <div className="wi-param">
                  <span className="label">BUY PRIOR %</span>
                  <input type="number" min="0" max="100" value={Math.round(run.buy*100)}
                    onChange={e=>setRun(r=>({...r,buy:Number(e.target.value)/100}))} className="wi-num-input mono" />
                </div>
                <div className="wi-param">
                  <span className="label">SELL PRIOR %</span>
                  <input type="number" min="0" max="100" value={Math.round(run.sell*100)}
                    onChange={e=>setRun(r=>({...r,sell:Number(e.target.value)/100}))} className="wi-num-input mono" />
                </div>
                <div className="wi-param">
                  <span className="label">MODEL</span>
                  <div className="wi-model-pick">
                    {['llama3.3:70b','llama3.1:8b'].map(m=>(
                      <button key={m} className="wi-mpick-btn" data-active={run.model===m}
                        onClick={()=>setRun(r=>({...r,model:m}))}>{m}</button>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* Results */}
        <div className="wi-results">
          <div className="wi-result-col">
            <div className="wi-result-head">
              <div className="wi-res-seed">"{runA.seed}"</div>
              <div className={`wi-consensus sig-${consA.toLowerCase()}`}>{consA} {Math.round(Math.max(buyA,sellA)/100*100)}%</div>
            </div>
            <WiMiniForce agents={agentsA} />
            <WiBracketBars summaries={sumA} />
          </div>

          <div className="wi-divider-col">
            <div className="wi-vs">VS</div>
            <div className="wi-divergence">
              <div className="label" style={{marginBottom:8}}>DIVERGENCE</div>
              {sumA.map((bA,i) => {
                const bB = sumB[i];
                const diffBuy = bA.buy_count - bB.buy_count;
                return (
                  <div key={bA.bracket} className="wi-div-row">
                    <span className="wi-div-bracket label">{bA.display_name.slice(0,8)}</span>
                    <span className={`wi-div-val mono ${diffBuy>0?'pos':diffBuy<0?'neg':''}`}>
                      {diffBuy>0?'+':''}{diffBuy}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="wi-result-col">
            <div className="wi-result-head">
              <div className="wi-res-seed">"{runB.seed}"</div>
              <div className={`wi-consensus sig-${consB.toLowerCase()}`}>{consB} {Math.round(Math.max(buyB,sellB)/100*100)}%</div>
            </div>
            <WiMiniForce agents={agentsB} />
            <WiBracketBars summaries={sumB} />
          </div>
        </div>
      </div>
    </div>
  );
}

function WiMiniForce({ agents }) {
  const buy  = agents.filter(a=>a.signal==='buy').length;
  const sell = agents.filter(a=>a.signal==='sell').length;
  const hold = agents.filter(a=>a.signal==='hold').length;
  // 10×10 grid of colored dots
  const dots = agents.slice(0,100).map(a =>
    a.signal==='buy'?'var(--buy)': a.signal==='sell'?'var(--sell)':'var(--hold)'
  );
  return (
    <div className="wi-mini-viz">
      <div className="wi-dot-grid">
        {dots.map((c,i) => <div key={i} className="wi-dot" style={{background:c}} />)}
      </div>
      <div className="wi-mini-legend">
        <span style={{color:'var(--buy)'}}>{buy} BUY</span>
        <span style={{color:'var(--sell)'}}>{sell} SELL</span>
        <span style={{color:'var(--hold)'}}>{hold} HOLD</span>
      </div>
    </div>
  );
}

function WiBracketBars({ summaries }) {
  return (
    <div className="wi-bracket-bars">
      {summaries.map(s => {
        const bp = s.buy_count/s.total, sp = s.sell_count/s.total;
        return (
          <div key={s.bracket} className="wi-bb-row">
            <span className="wi-bb-name label">{s.display_name.slice(0,10)}</span>
            <div className="wi-bb-bar">
              <div style={{width:`${bp*100}%`,background:'var(--buy)',height:'100%'}} />
              <div style={{width:`${sp*100}%`,background:'var(--sell)',height:'100%'}} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── SEED SUGGESTIONS ─────────────────────────────────────────────────
const MOCK_SEEDS = [
  { headline: 'Fed minutes signal two more hikes in 2026', category: 'macro', urgency: 'high' },
  { headline: 'NVIDIA acquires SambaNova for $8B', category: 'tech', urgency: 'high' },
  { headline: 'Berkshire Hathaway discloses new $12B position in TSMC', category: 'institutional', urgency: 'medium' },
  { headline: 'EU passes AI Act emergency amendment — frontier models banned for 6 months', category: 'regulatory', urgency: 'high' },
  { headline: 'Saudi Aramco announces $200B green energy pivot by 2030', category: 'macro', urgency: 'low' },
  { headline: 'OpenAI raises $15B Series G at $400B valuation', category: 'tech', urgency: 'medium' },
  { headline: 'China restricts rare earth exports to US semiconductor firms', category: 'geopolitical', urgency: 'high' },
];

function SeedSuggest({ onPick, onClose }) {
  const urgencyColor = u => u==='high'?'var(--sell)':u==='medium'?'var(--accent)':'var(--text-3)';
  return (
    <div className="ss-panel">
      <div className="ss-head">
        <div className="hflex">
          <Icon name="bolt" size={13} />
          <span className="label" style={{color:'var(--accent)'}}>SEED SUGGESTIONS</span>
        </div>
        <button className="btn ghost-btn" style={{height:24}} onClick={onClose}><Icon name="close" /></button>
      </div>
      <div className="ss-note label">Market-moving scenarios from today's news · powered by NewsAPI</div>
      <div className="ss-list">
        {MOCK_SEEDS.map((s,i) => (
          <button key={i} className="ss-row" onClick={() => { onPick(s.headline); onClose(); }}>
            <div className="ss-urgency" style={{background: urgencyColor(s.urgency)}} />
            <div className="ss-seed-text">"{s.headline}"</div>
            <div className="ss-cat label">{s.category}</div>
            <div className="ss-run label" style={{color:'var(--accent)'}}>USE →</div>
          </button>
        ))}
      </div>
    </div>
  );
}

// ── WATCH MODE ───────────────────────────────────────────────────────
const WATCH_CYCLES = [
  { id:'W-001', seed:'Fed minutes signal two more hikes', schedule:'Daily 09:30 ET', lastRun:'2026-05-07 09:30', consensus:'SELL 62%', status:'active', nextRun:'2026-05-08 09:30' },
  { id:'W-002', seed:'NVDA weekly sentiment check', schedule:'Mon/Wed/Fri 08:00 ET', lastRun:'2026-05-07 08:00', consensus:'BUY 58%', status:'active', nextRun:'2026-05-08 08:00' },
  { id:'W-003', seed:'China rare earth export restrictions', schedule:'Weekly Mon 07:00 ET', lastRun:'2026-05-05 07:00', consensus:'SELL 71%', status:'paused', nextRun:'—' },
];

function WatchMode({ onClose, onOpenReport }) {
  const [watches, setWatches] = useWI(WATCH_CYCLES);
  const [showNew, setShowNew] = useWI(false);
  const [newSeed, setNewSeed] = useWI('');
  const [newSchedule, setNewSchedule] = useWI('Daily 09:30 ET');

  const toggle = (id) => setWatches(w => w.map(x => x.id===id ? {...x, status: x.status==='active'?'paused':'active'} : x));
  const remove = (id) => setWatches(w => w.filter(x => x.id!==id));
  const add = () => {
    if (!newSeed.trim()) return;
    setWatches(w => [...w, {
      id: `W-00${w.length+1}`, seed: newSeed, schedule: newSchedule,
      lastRun: '—', consensus: '—', status:'active', nextRun: 'Next scheduled run'
    }]);
    setNewSeed(''); setShowNew(false);
  };

  return (
    <div className="wm-takeover">
      <div className="wm-head">
        <button className="btn ghost-btn" onClick={onClose}><Icon name="close" /></button>
        <span className="wm-title">Watch Mode</span>
        <span className="label">SCHEDULED SEED RUNS · RESULTS IN CYCLE HISTORY</span>
        <div className="sp" />
        <button className="btn primary" onClick={() => setShowNew(s=>!s)}><Icon name="play" /> + New watch</button>
      </div>

      {showNew && (
        <div className="wm-new-row">
          <div className="seed-input" style={{flex:2}}>
            <span className="prefix">SEED →</span>
            <input value={newSeed} onChange={e=>setNewSeed(e.target.value)} placeholder="Market scenario to monitor…" />
          </div>
          <div className="wm-schedule-pick">
            {['Daily 09:30 ET','Daily 16:00 ET','Mon/Wed/Fri 09:30 ET','Weekly Mon 08:00 ET'].map(s=>(
              <button key={s} className="wm-sched-btn" data-active={newSchedule===s}
                onClick={()=>setNewSchedule(s)}>{s}</button>
            ))}
          </div>
          <button className="btn primary" onClick={add}>Create</button>
          <button className="btn ghost" onClick={()=>setShowNew(false)}>Cancel</button>
        </div>
      )}

      <div className="wm-list-head">
        <span className="label">ACTIVE WATCHES ({watches.filter(w=>w.status==='active').length})</span>
      </div>
      <div className="wm-list">
        {watches.map(w => (
          <div key={w.id} className="wm-row" data-status={w.status}>
            <div className="wm-row-left">
              <div className="wm-status-dot" data-active={w.status==='active'} />
              <div>
                <div className="wm-seed">"{w.seed}"</div>
                <div className="label wm-schedule"><Icon name="replay" size={10} /> {w.schedule} · next: {w.nextRun}</div>
              </div>
            </div>
            <div className="wm-last">
              <div className="label">LAST RUN</div>
              <div className="mono" style={{fontSize:12}}>{w.lastRun}</div>
            </div>
            <div className="wm-consensus">
              {w.consensus !== '—' && (
                <span className={`ch-pill ${w.consensus.startsWith('BUY')?'data-tone-buy':'data-tone-sell'}`}
                  style={{background: w.consensus.startsWith('BUY')?'rgba(66,214,144,0.15)':'rgba(255,91,107,0.15)',
                    color: w.consensus.startsWith('BUY')?'var(--buy)':'var(--sell)', padding:'3px 8px',
                    fontFamily:'JetBrains Mono', fontSize:'10.5px', fontWeight:700, borderRadius:2}}>
                  {w.consensus}
                </span>
              )}
            </div>
            <div className="wm-actions">
              <button className="btn ghost" style={{height:28}} onClick={()=>toggle(w.id)}>
                {w.status==='active'?<><Icon name="pause" /> Pause</>:<><Icon name="play" /> Resume</>}
              </button>
              {w.consensus !== '—' && (
                <button className="btn ghost" style={{height:28}} onClick={()=>onOpenReport(w)}>
                  <Icon name="doc" />
                </button>
              )}
              <button className="btn ghost" style={{height:28, color:'var(--sell)'}} onClick={()=>remove(w.id)}>
                <Icon name="close" />
              </button>
            </div>
          </div>
        ))}
      </div>

      <div className="wm-footer">
        <Icon name="lock" size={12} />
        <span className="label">Runs execute locally when AlphaSwarm is open · all results stored in cycle history</span>
      </div>
    </div>
  );
}

// ── MULTI-SEED SYNTHESIS ──────────────────────────────────────────────
function MultiSeedSynthesis({ onClose }) {
  const { buildAgents } = window.AS_DATA;
  const [seeds, setSeeds] = useWI([
    'Apple acquiring Anthropic for $500B',
    'DOJ blocks Apple–Anthropic deal on antitrust grounds',
    'Anthropic denies Apple acquisition talks publicly',
  ]);
  const [ran, setRan] = useWI(true);

  const runs = useWM(() => seeds.map((seed, i) => {
    const mixes = [
      {buy:0.28,sell:0.50,hold:0.22},
      {buy:0.55,sell:0.26,hold:0.19},
      {buy:0.40,sell:0.36,hold:0.24},
    ];
    const agents = buildAgents(3, mixes[i]);
    const buy=agents.filter(a=>a.signal==='buy').length;
    const sell=agents.filter(a=>a.signal==='sell').length;
    const consensus = buy>=sell?'BUY':'SELL';
    const pct = Math.round(Math.max(buy,sell)/agents.length*100);
    return { seed, agents, buy, sell, hold:agents.filter(a=>a.signal==='hold').length, consensus, pct };
  }), [seeds, ran]);

  const synthBuy = runs.filter(r=>r.consensus==='BUY').length;
  const synthSell = runs.filter(r=>r.consensus==='SELL').length;
  const synthConsensus = synthBuy >= synthSell ? 'BUY' : 'SELL';

  return (
    <div className="ms-takeover">
      <div className="ms-head">
        <button className="btn ghost-btn" onClick={onClose}><Icon name="close" /></button>
        <span className="ms-title">Multi-Seed Synthesis</span>
        <span className="label">RUN 3 RELATED SEEDS · ORCHESTRATOR SYNTHESIZES</span>
        <div className="sp" />
        <button className="btn primary" onClick={()=>setRan(r=>!r)}><Icon name="play" /> Run all</button>
      </div>

      <div className="ms-body">
        {/* Seed inputs */}
        <div className="ms-seeds">
          {seeds.map((s,i) => (
            <div key={i} className="ms-seed-row">
              <div className="ms-seed-num">{i+1}</div>
              <input className="ms-seed-input" value={s}
                onChange={e => setSeeds(prev => prev.map((x,j)=>j===i?e.target.value:x))} />
              <div className={`ms-seed-consensus`} style={{
                color: runs[i]?.consensus==='BUY'?'var(--buy)':'var(--sell)',
                fontFamily:'JetBrains Mono', fontSize:12, fontWeight:700, minWidth:80, textAlign:'right'
              }}>
                {runs[i] ? `${runs[i].consensus} ${runs[i].pct}%` : '—'}
              </div>
              <WiMiniForce agents={runs[i]?.agents || []} />
            </div>
          ))}
        </div>

        {/* Synthesis */}
        <div className="ms-synthesis">
          <div className="ms-synth-head">
            <div className="label" style={{color:'var(--accent)', marginBottom:8}}>ORCHESTRATOR SYNTHESIS</div>
            <div className="ms-synth-consensus">
              Meta-consensus: <span style={{color: synthConsensus==='BUY'?'var(--buy)':'var(--sell)', fontWeight:700}}>
                {synthConsensus}
              </span>
              <span className="label" style={{marginLeft:8}}>{synthBuy}/3 seeds bearish</span>
            </div>
          </div>

          <div className="ms-synth-body">
            <div className="ms-synth-section">
              <div className="label" style={{marginBottom:8}}>CONSISTENT SIGNALS ACROSS ALL THREE SEEDS</div>
              <p className="ms-prose">Regulatory overhang is the single thread running through all scenarios. Whether the deal happens, gets blocked, or is denied, the market reprices AAPL around antitrust risk. Swarm consensus SELL on the current price in all three scenarios suggests the rumor premium is fully baked regardless of outcome.</p>
            </div>
            <div className="ms-synth-section">
              <div className="label" style={{marginBottom:8}}>DIVERGENT SIGNALS</div>
              <p className="ms-prose">Degens bracket diverges sharply: BUY on seed 1 (M&A premium trade), SELL on seed 2 (deal break unwinds the bet), HOLD on seed 3 (ambiguity = no position). This bracket-level sensitivity to framing is the key signal — their behavior is not driven by fundamentals.</p>
            </div>
            <div className="ms-synth-section">
              <div className="label" style={{marginBottom:8}}>RECOMMENDED FOLLOW-UP</div>
              <p className="ms-prose">Run a fourth seed: "Apple announces own foundation model built on acquired talent, not Anthropic." This isolates whether the AAPL bearishness is deal-specific or fundamental to Apple's AI strategy.</p>
              <button className="btn ghost" style={{marginTop:10}}>
                <Icon name="play" /> Add as Seed 4
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── PORTFOLIO STRESS TEST ─────────────────────────────────────────────
function PortfolioStressTest({ onClose }) {
  const { HOLDINGS, buildAgents } = window.AS_DATA;
  const [running, setRunning] = useWI(false);
  const [done, setDone] = useWI(false);
  const [progress, setProgress] = useWI(0);

  const scenarios = [
    { id:'s1', seed:'Apple acquiring Anthropic for $500B',        consensus:'SELL 58%', aapl:-8.2, nvda:+3.1, msft:-1.2, googl:-3.4, meta:+0.8 },
    { id:'s2', seed:'Fed emergency 50bp cut',                      consensus:'BUY 71%',  aapl:+6.1, nvda:+9.4, msft:+5.8, googl:+4.2, meta:+7.3 },
    { id:'s3', seed:'China rare earth export ban to US',           consensus:'SELL 64%', aapl:-5.4, nvda:-12.1,msft:-3.2, googl:-2.8, meta:-1.4 },
    { id:'s4', seed:'EU AI Act bans frontier models 6 months',     consensus:'SELL 55%', aapl:-3.1, nvda:-6.4, msft:-4.8, googl:-5.2, meta:-8.1 },
    { id:'s5', seed:'OpenAI raises $15B Series G at $400B',        consensus:'BUY 52%',  aapl:+2.1, nvda:+5.2, msft:+4.4, googl:-2.1, meta:+1.8 },
  ];

  const runStressTest = () => {
    setRunning(true); setDone(false); setProgress(0);
    let p = 0;
    const iv = setInterval(() => {
      p += 20;
      setProgress(p);
      if (p >= 100) { clearInterval(iv); setRunning(false); setDone(true); }
    }, 600);
  };

  const totalValue = HOLDINGS.reduce((s,h) => s + h.shares * h.last, 0);

  return (
    <div className="pst-takeover">
      <div className="pst-head">
        <button className="btn ghost-btn" onClick={onClose}><Icon name="close" /></button>
        <span className="pst-title">Portfolio Stress Test</span>
        <span className="label">5 SCENARIOS · {HOLDINGS.length} HOLDINGS · SWARM ANALYSIS</span>
        <div className="sp" />
        {!running && !done && <button className="btn primary" onClick={runStressTest}><Icon name="play" /> Run stress test</button>}
        {running && <button className="btn" disabled>Running… {progress}%</button>}
        {done && <button className="btn" onClick={runStressTest}><Icon name="replay" /> Re-run</button>}
      </div>

      {running && (
        <div className="pst-progress">
          <div className="pst-progress-bar"><div className="pst-progress-fill" style={{width:`${progress}%`}} /></div>
          <div className="label pst-progress-label">Running scenario {Math.ceil(progress/20)} of 5 · {scenarios[Math.min(Math.ceil(progress/20)-1,4)]?.seed}</div>
        </div>
      )}

      <div className="pst-body">
        {/* Scenario matrix */}
        <div className="pst-matrix">
          <div className="pst-matrix-head">
            <div className="label">SCENARIO</div>
            <div className="label">CONSENSUS</div>
            {HOLDINGS.map(h => <div key={h.ticker} className="label" style={{textAlign:'right'}}>{h.ticker}</div>)}
            <div className="label" style={{textAlign:'right'}}>PORTFOLIO Δ</div>
          </div>
          {scenarios.map(sc => {
            const impacts = { AAPL:sc.aapl, NVDA:sc.nvda, MSFT:sc.msft, GOOGL:sc.googl, META:sc.meta };
            const pnl = HOLDINGS.reduce((s,h) => s + h.shares * h.last * (impacts[h.ticker]||0)/100, 0);
            return (
              <div key={sc.id} className="pst-scenario-row" data-done={done}>
                <div className="pst-sc-seed">"{sc.seed.length>40?sc.seed.slice(0,40)+'…':sc.seed}"</div>
                <div className={`pst-sc-cons mono ${sc.consensus.startsWith('BUY')?'pos':'neg'}`}>{sc.consensus}</div>
                {HOLDINGS.map(h => {
                  const imp = impacts[h.ticker] || 0;
                  return (
                    <div key={h.ticker} className={`pst-cell mono ${imp>0?'pos':imp<0?'neg':''}`} style={{textAlign:'right'}}>
                      {done ? `${imp>0?'+':''}${imp.toFixed(1)}%` : '—'}
                    </div>
                  );
                })}
                <div className={`pst-cell mono ${pnl>0?'pos':'neg'}`} style={{textAlign:'right', fontWeight:600}}>
                  {done ? `${pnl>0?'+':''}$${(Math.abs(pnl)/1000).toFixed(1)}K` : '—'}
                </div>
              </div>
            );
          })}
        </div>

        {/* Summary */}
        {done && (
          <div className="pst-summary">
            <div className="label" style={{marginBottom:12, color:'var(--accent)'}}>STRESS TEST SUMMARY</div>
            <div className="pst-sum-stats">
              {[
                { label:'WORST SCENARIO', value:'China rare earth ban', sub:'-$18.2K portfolio impact', tone:'sell' },
                { label:'BEST SCENARIO', value:'Fed 50bp cut', sub:'+$34.1K portfolio impact', tone:'buy' },
                { label:'MOST EXPOSED', value:'NVDA', sub:'±12% across scenarios', tone:'warn' },
                { label:'MOST RESILIENT', value:'META', sub:'±4.2% avg swing', tone:'ok' },
              ].map(s => (
                <div key={s.label} className="pst-sum-card" data-tone={s.tone}>
                  <div className="label">{s.label}</div>
                  <div className="pst-sum-val">{s.value}</div>
                  <div className="pst-sum-sub mono">{s.sub}</div>
                </div>
              ))}
            </div>
            <div className="ms-prose pst-note">
              Your NVDA position is the highest-volatility holding across all 5 scenarios — ranging from +9.4% (Fed cut) to -12.1% (China ban). Consider whether your current 550-share exposure is sized for that range. AAPL shows consistent downside across 4 of 5 scenarios, reinforcing the advisory trim recommendation.
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── BRACKET CUSTOMIZATION ────────────────────────────────────────────
function BracketCustomizer({ onClose }) {
  const [brackets, setBrackets] = useWI([
    { key:'quants',       name:'Quants',       count:14, prompt:'Data-driven, algorithmic, DCF-focused. Skeptical of narrative.', active:true },
    { key:'degens',       name:'Degens',       count:12, prompt:'High-risk, FOMO-driven speculators. React to price action and flow.', active:true },
    { key:'sovereigns',   name:'Sovereigns',   count:8,  prompt:'Ultra-conservative, geopolitically aware. Long-only mandate.', active:true },
    { key:'macro',        name:'Macro',        count:12, prompt:'Think in regimes, rates, and cycles. Supply-chain bias.', active:true },
    { key:'suits',        name:'Suits',        count:10, prompt:'Institutional, consensus-following. Risk-averse. Fundamentals-driven.', active:true },
    { key:'insiders',     name:'Insiders',     count:10, prompt:'Industry-specific knowledge. Capex and contract-aware.', active:true },
    { key:'agents',       name:'Agents',       count:10, prompt:'Algorithmic rule-based. No emotion. Trigger-driven signals.', active:true },
    { key:'doom_posters', name:'Doom-Posters', count:8,  prompt:'Perma-bears. Amplify negative narratives. Short-sellers.', active:true },
    { key:'policy_wonks', name:'Policy Wonks', count:8,  prompt:'Regulatory focus. Legal bias. Policy is the ultimate market mover.', active:true },
    { key:'whales',       name:'Whales',       count:8,  prompt:'Contrarian. Decade-horizon bets. Deep value, private credit.', active:true },
    { key:'custom_1',     name:'My Firm',      count:0,  prompt:'', active:false, custom:true },
  ]);

  const [editing, setEditing] = useWI(null);
  const total = brackets.filter(b=>b.active).reduce((s,b)=>s+b.count,0);

  const update = (key, patch) => setBrackets(bs => bs.map(b => b.key===key ? {...b,...patch} : b));

  return (
    <div className="bc-takeover">
      <div className="bc-head">
        <button className="btn ghost-btn" onClick={onClose}><Icon name="close" /></button>
        <span className="bc-title">Bracket Customization</span>
        <span className="label">PERSONA PROMPTS · COUNTS · CUSTOM BRACKETS</span>
        <div className="sp" />
        <div className="bc-total" data-ok={total===100}>
          <span className="label">TOTAL AGENTS</span>
          <span className="mono bc-total-val">{total}/100</span>
        </div>
        <button className="btn primary" onClick={onClose}>Save</button>
      </div>

      <div className="bc-body">
        <div className="bc-list">
          {brackets.map(b => (
            <div key={b.key} className="bc-row" data-active={b.active}>
              <div className="bc-row-left">
                <label className="bc-toggle">
                  <input type="checkbox" checked={b.active}
                    onChange={e => update(b.key, {active:e.target.checked})} />
                </label>
                <div className="bc-name">{b.name} {b.custom && <span className="bc-custom-badge">CUSTOM</span>}</div>
              </div>
              <input type="number" min="0" max="30" value={b.count} disabled={!b.active}
                onChange={e => update(b.key, {count:Number(e.target.value)})}
                className="bc-count-input mono" />
              <div className="bc-prompt-preview" onClick={() => setEditing(editing===b.key?null:b.key)}>
                {b.prompt || <span style={{color:'var(--text-3)'}}>No prompt — click to add</span>}
                <Icon name="settings" size={11} />
              </div>
              {editing === b.key && (
                <textarea className="bc-prompt-edit" value={b.prompt}
                  onChange={e => update(b.key, {prompt:e.target.value})}
                  placeholder="Describe this bracket's persona, reasoning style, biases…"
                  rows={3} />
              )}
            </div>
          ))}
        </div>
        <div className="bc-add">
          <button className="btn ghost bc-add-btn" onClick={() => {
            const newKey = `custom_${Date.now()}`;
            setBrackets(bs => [...bs, {key:newKey, name:'Custom Bracket', count:5, prompt:'', active:true, custom:true}]);
            setEditing(newKey);
          }}>
            + Add custom bracket
          </button>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { WhatIfCompare, SeedSuggest, WatchMode, MultiSeedSynthesis, PortfolioStressTest, BracketCustomizer });
