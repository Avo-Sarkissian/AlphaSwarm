// v2 components — Signal Wire (CSS scroll), Data Sources (full takeover), Advisory V2, Model Status
// Relies on window.AS_DATA and window.Icon from earlier scripts.

const { useState, useEffect, useRef, useMemo } = React;

// ──────────────────────────────────────────────────────────────────────
// SIGNAL WIRE — continuous CSS-scroll live wire
// ──────────────────────────────────────────────────────────────────────
function SignalWire({ running, onInspect }) {
  const { SIGNAL_WIRE_SEED, DATA_SOURCES, SOURCE_GROUP_COLOR } = window.AS_DATA;
  const sourceById = useMemo(
    () => Object.fromEntries(DATA_SOURCES.map(s => [s.id, s])),
    []
  );

  // Pure static content — no React state, no re-renders, no skipping.
  // Triple the seed list so the loop is long enough to be seamless.
  const items = useMemo(() => [...SIGNAL_WIRE_SEED, ...SIGNAL_WIRE_SEED, ...SIGNAL_WIRE_SEED], []);

  return (
    <div className="signal-wire">
      <div className="sw-label">
        <span className="label" style={{color:'var(--accent)'}}>WIRE</span>
        {running && <span className="sw-live-dot" />}
      </div>

      <div className="sw-scroll-wrap">
        <div className="sw-scroll-inner" style={{animationPlayState: running ? 'running' : 'paused'}}>
          {items.map((e, i) => {
            const src = sourceById[e.source];
            const color = SOURCE_GROUP_COLOR[src?.group] || '#8a93a0';
            return (
              <div key={i} className="sw-event" data-unused={!e.used}>
                <span className="sw-agent">{e.agent}</span>
                <span className="sw-sep" style={{color}}>→</span>
                <span className="sw-src" style={{color}}>{src?.label || e.source}</span>
                <span className="sw-q">{e.query}</span>
                <span className="sw-r">{e.result}</span>
                {!e.used && <span className="sw-unused" title="fetched, not cited">○</span>}
                <span className="sw-divider">·</span>
              </div>
            );
          })}
        </div>
      </div>

      <button className="sw-inspect" onClick={onInspect} title="Open Data Sources inspector">
        <Icon name="search" size={12} />
        <span>Sources</span>
      </button>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// MODEL STATUS — topbar inline status chip
// ──────────────────────────────────────────────────────────────────────
function ModelStatus({ running, phase, tps, slots }) {
  const ops = [
    `${phase === 'done' ? 'complete' : `round ${phase}/3`}`,
    `${slots} slots`,
    `${tps?.toFixed(1)} t/s`,
  ];
  return (
    <div className="model-status" data-running={running}>
      <div className="ms-model">
        <span className="ms-dot" data-running={running} />
        <span className="mono ms-name">llama3.3:70b</span>
      </div>
      <div className="ms-ops">
        {ops.map((o, i) => (
          <span key={i} className="ms-op">{o}</span>
        ))}
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// DATA SOURCES — full-screen takeover
// ──────────────────────────────────────────────────────────────────────
function DataSourcesTakeover({ onClose }) {
  const { DATA_SOURCES, SOURCE_GROUP_COLOR, SOURCE_STATS, SIGNAL_WIRE_SEED } = window.AS_DATA;
  const statsById = useMemo(() => Object.fromEntries(SOURCE_STATS.map(s => [s.id, s])), []);
  const [selected, setSelected] = useState(DATA_SOURCES[0].id);
  const [groupFilter, setGroupFilter] = useState('all');

  const sel = DATA_SOURCES.find(s => s.id === selected);
  const stats = statsById[selected];
  const recent = useMemo(() => SIGNAL_WIRE_SEED.filter(e => e.source === selected).slice(0, 8), [selected]);

  const groups = useMemo(() => {
    const g = {};
    for (const s of DATA_SOURCES) (g[s.group] = g[s.group] || []).push(s);
    return g;
  }, []);

  const totalCalls = SOURCE_STATS.reduce((a, s) => a + s.calls, 0);
  const totalErrors = SOURCE_STATS.reduce((a, s) => a + s.errors, 0);
  const totalBytes = '82.1 MB';

  const filtered = groupFilter === 'all' ? DATA_SOURCES : DATA_SOURCES.filter(s => s.group === groupFilter);

  return (
    <div className="ds-takeover">
      <div className="ds-head">
        <div className="ds-head-left">
          <button className="btn ghost-btn" onClick={onClose}><Icon name="close" /></button>
          <div className="ds-head-title">Data Sources</div>
          <div className="label" style={{color:'var(--text-3)'}}>API AUDIT · THIS CYCLE</div>
        </div>
        <div className="ds-head-stats">
          <DsStat label="TOTAL CALLS" value={totalCalls.toLocaleString()} />
          <DsStat label="ERRORS" value={totalErrors} tone={totalErrors > 10 ? 'sell' : 'ok'} />
          <DsStat label="EGRESS" value={totalBytes} />
          <DsStat label="CACHE RATE" value={`${Math.round(SOURCE_STATS.reduce((a,s)=>a+s.cached,0)/totalCalls*100)}%`} />
        </div>
      </div>

      <div className="ds-body">
        {/* Left: source list */}
        <div className="ds-left">
          <div className="ds-group-tabs">
            {['all','market','macro','news','social','filings'].map(g => (
              <button key={g} className="ds-gtab" data-active={groupFilter===g}
                onClick={() => setGroupFilter(g)}>
                {g === 'all' ? 'All' : g}
              </button>
            ))}
          </div>
          <div className="ds-source-list">
            {filtered.map(s => {
              const st = statsById[s.id];
              const cacheRate = st ? Math.round((st.cached/st.calls)*100) : 0;
              const errRate = st ? st.errors / st.calls : 0;
              const color = SOURCE_GROUP_COLOR[s.group];
              return (
                <button key={s.id} className="ds-source-row"
                  data-active={selected === s.id}
                  onClick={() => setSelected(s.id)}>
                  <div className="ds-src-top">
                    <div className="ds-src-name">
                      <span className="ds-src-dot" style={{background: color}} />
                      <span>{s.label}</span>
                    </div>
                    <span className={`ds-src-calls mono ${errRate > 0.02 ? 'err' : ''}`}>
                      {st?.calls?.toLocaleString() ?? 0}
                    </span>
                  </div>
                  {/* Mini bar: cache rate */}
                  <div className="ds-src-bar">
                    <div className="ds-src-bar-fill" style={{width: `${cacheRate}%`, background: color, opacity: 0.6}} />
                    {errRate > 0 && (
                      <div className="ds-src-bar-err" style={{width: `${errRate*100}%`}} />
                    )}
                  </div>
                  <div className="ds-src-meta">
                    <span>{cacheRate}% cached</span>
                    {st?.errors > 0 && <span className="ds-err-badge">{st.errors} err</span>}
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        {/* Right: detail pane */}
        {sel && stats && (
          <div className="ds-detail-pane">
            <div className="ds-detail-hero">
              <div className="ds-detail-name">
                <span className="ds-src-dot lg" style={{background: SOURCE_GROUP_COLOR[sel.group]}} />
                <h2>{sel.label}</h2>
                <span className="label ds-group-tag">{sel.group}</span>
              </div>
              <div className="ds-detail-desc">{sel.desc}</div>
              <div className="ds-detail-chips">
                <span className="ds-chip">rate: {sel.rate}</span>
                <span className="ds-chip">baseline: {sel.latency}ms</span>
                <span className="ds-chip">{stats.bytes} transferred</span>
              </div>
            </div>

            {/* Stats grid */}
            <div className="ds-stats-grid">
              <DsStatCard label="CALLS" value={stats.calls.toLocaleString()} />
              <DsStatCard label="CACHE HIT" value={`${Math.round(stats.cached/stats.calls*100)}%`}
                sub={`${stats.cached.toLocaleString()} of ${stats.calls.toLocaleString()}`}
                tone="buy" />
              <DsStatCard label="ERRORS" value={stats.errors}
                tone={stats.errors > 5 ? 'sell' : stats.errors > 0 ? 'warn' : 'buy'} />
              <DsStatCard label="P50 LATENCY" value={`${stats.lat_p50}ms`} />
              <DsStatCard label="P95 LATENCY" value={`${stats.lat_p95}ms`}
                tone={stats.lat_p95 > 600 ? 'warn' : 'ok'} />
              <DsStatCard label="STATUS" value="ONLINE" tone="buy" />
            </div>

            {/* Latency bar visualization */}
            <div className="ds-latency-viz">
              <div className="label" style={{marginBottom:10}}>LATENCY DISTRIBUTION</div>
              <div className="ds-lat-bars">
                {[
                  {label:'p10', val: Math.round(stats.lat_p50*0.6)},
                  {label:'p25', val: Math.round(stats.lat_p50*0.8)},
                  {label:'p50', val: stats.lat_p50},
                  {label:'p75', val: Math.round((stats.lat_p50+stats.lat_p95)/2)},
                  {label:'p95', val: stats.lat_p95},
                  {label:'p99', val: Math.round(stats.lat_p95*1.4)},
                ].map(({label, val}) => {
                  const maxVal = Math.round(stats.lat_p95 * 1.4);
                  const pct = (val / maxVal) * 100;
                  const color = val > stats.lat_p95 ? 'var(--sell)' : val > stats.lat_p50 ? 'var(--accent)' : 'var(--buy)';
                  return (
                    <div key={label} className="ds-lat-col">
                      <div className="ds-lat-bar-wrap">
                        <div className="ds-lat-bar" style={{height:`${pct}%`, background: color}} />
                      </div>
                      <div className="ds-lat-val mono">{val}</div>
                      <div className="label">{label}</div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Recent queries */}
            <div className="ds-recent-section">
              <div className="label" style={{marginBottom:10}}>RECENT QUERIES · THIS CYCLE</div>
              {recent.length === 0 ? (
                <div className="ds-empty">No queries recorded for this source this cycle.</div>
              ) : (
                <div className="ds-recent-table">
                  <div className="ds-recent-head">
                    <span className="label">AGENT</span>
                    <span className="label">QUERY</span>
                    <span className="label">RESULT</span>
                    <span className="label">CITED</span>
                  </div>
                  {recent.map((r, i) => (
                    <div key={i} className="ds-recent-row-v2">
                      <span className="mono" style={{color:'var(--accent)'}}>{r.agent}</span>
                      <span className="mono ds-q-text">{r.query}</span>
                      <span className="mono ds-r-text">{r.result}</span>
                      <span className={`ds-cited-badge ${r.used ? 'yes' : 'no'}`}>{r.used ? 'YES' : 'NO'}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="ds-privacy-note">
              <Icon name="lock" size={12} />
              <span>Inference is 100% local (Ollama). These calls are the only network egress this cycle.
              Keys stored in <span className="mono">~/.alphaswarm/keys.toml</span></span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function DsStat({ label, value, tone }) {
  return (
    <div className="ds-head-stat" data-tone={tone}>
      <div className="label">{label}</div>
      <div className="ds-head-stat-v mono">{value}</div>
    </div>
  );
}

function DsStatCard({ label, value, sub, tone }) {
  return (
    <div className="ds-stat-card" data-tone={tone}>
      <div className="label">{label}</div>
      <div className="ds-stat-v">{value}</div>
      {sub && <div className="ds-stat-sub mono">{sub}</div>}
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// ADVISORY V2 — full-screen personalized analysis
// ──────────────────────────────────────────────────────────────────────
function AdvisoryV2({ onClose }) {
  const { HOLDINGS } = window.AS_DATA;
  const [tab, setTab] = useState('overview');

  const swarmConsensus = { signal: 'SELL', pct: 58, buy: 22, sell: 58, hold: 20 };

  const holdingAnalysis = [
    { ticker: 'AAPL', shares: 1200, basis: 142.30, last: 218.40, value: 262080,
      sentiment: -0.48, swarmSignal: 'SELL', weight: 34.2,
      rec: 'TRIM 15–25%', recTone: 'sell',
      rationale: 'Your largest holding directly involved in the seed rumor. Swarm consensus SELL 58% driven by compute-dependency and FTC risk. Cost basis $142.30 gives room to trim gains while protecting upside.',
      risk: 'Regulatory delay 18mo+', upside: 'Deal confirmed at premium', agents: 87 },
    { ticker: 'NVDA', shares: 550, basis: 88.50, last: 142.20, value: 78210,
      sentiment: +0.31, swarmSignal: 'BUY', weight: 10.2,
      rec: 'HOLD / ADD on dip', recTone: 'buy',
      rationale: 'Macro bracket constructive. 3 agents specifically cited AAPL/Anthropic deal failure as NVDA tailwind — AI compute demand shifts to independent providers if vertical integration fails.',
      risk: 'Valuation stretch at 35× fwd', upside: 'Compute scarcity thesis', agents: 31 },
    { ticker: 'MSFT', shares: 380, basis: 228.10, last: 410.75, value: 156085,
      sentiment: +0.12, swarmSignal: 'HOLD', weight: 20.4,
      rec: 'NO ACTION', recTone: 'hold',
      rationale: 'Swarm view neutral. OpenAI partnership priced in per Suits bracket rationale. No direct exposure to this seed\'s thesis.',
      risk: 'OpenAI dependency', upside: 'Copilot enterprise expansion', agents: 12 },
    { ticker: 'GOOGL', shares: 410, basis: 115.00, last: 165.90, value: 68019,
      sentiment: -0.22, swarmSignal: 'SELL', weight: 8.9,
      rec: 'MONITOR', recTone: 'hold',
      rationale: 'TPU commitment to Anthropic creates indirect exposure. If deal collapses, Google\'s compute advantage is preserved. 2 Insiders flagged GOOGL as secondary beneficiary.',
      risk: 'TPU commitment renegotiation cost', upside: 'Retained Anthropic relationship', agents: 18 },
    { ticker: 'META', shares: 180, basis: 298.40, last: 528.10, value: 95058,
      sentiment: +0.08, swarmSignal: 'HOLD', weight: 12.4,
      rec: 'NO ACTION', recTone: 'hold',
      rationale: 'Swarm view neutral to slightly positive. Llama open-source advantage grows if proprietary AI integration at Apple fails. Low direct exposure.',
      risk: 'Regulatory headwinds', upside: 'Open-source AI momentum', agents: 8 },
  ];

  const totalValue = holdingAnalysis.reduce((a, h) => a + h.value, 0);
  const exposureToSeed = holdingAnalysis.filter(h => h.ticker === 'AAPL')[0].value;
  const exposurePct = (exposureToSeed / totalValue * 100).toFixed(1);

  return (
    <div className="adv-takeover">
      <div className="adv-head">
        <div className="adv-head-left">
          <button className="btn ghost-btn" onClick={onClose}><Icon name="close" /></button>
          <div>
            <div className="adv-title">Personalized Advisory</div>
            <div className="label adv-subtitle">ORCHESTRATOR SYNTHESIS · SWARM CONSENSUS APPLIED TO YOUR PORTFOLIO</div>
          </div>
          <div className="adv-isolation-badge">
            <Icon name="lock" size={11} />
            <span>Holdings never seen by swarm agents</span>
          </div>
        </div>
        <div className="adv-head-right">
          <div className="adv-tabs">
            {['overview','holdings','risk','isolation'].map(t => (
              <button key={t} className="adv-tab" data-active={tab===t} onClick={() => setTab(t)}>
                {t.charAt(0).toUpperCase()+t.slice(1)}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="adv-body">
        {tab === 'overview' && (
          <div className="adv-overview">
            {/* Primary rec */}
            <div className="adv-primary-rec">
              <div className="adv-rec-tag">PRIMARY RECOMMENDATION</div>
              <div className="adv-rec-headline">
                Trim <span style={{color:'var(--accent)'}}>AAPL</span> exposure 15–25%
                ahead of regulatory clarity on the Apple–Anthropic deal.
              </div>
              <div className="adv-rec-body">
                Your {exposurePct}% AAPL concentration (${(exposureToSeed/1000).toFixed(0)}K of ${(totalValue/1000).toFixed(0)}K portfolio) 
                is directly exposed to swarm consensus <strong style={{color:'var(--sell)'}}>SELL 58%</strong>.
                87 of 100 agents flagged regulatory risk as the primary bear case.
                Cost basis $142.30 vs last $218.40 — trimming locks gains while preserving optional upside on deal confirmation.
              </div>
              <div className="adv-rec-actions">
                <button className="btn primary">Generate trim order</button>
                <button className="btn ghost">Set price alert at $208</button>
                <button className="btn ghost">Run counter-scenario</button>
              </div>
            </div>

            {/* Summary stats */}
            <div className="adv-summary-stats">
              <AdvStat label="PORTFOLIO" value={`$${(totalValue/1000).toFixed(0)}K`} sub="5 holdings" />
              <AdvStat label="SEED EXPOSURE" value={`${exposurePct}%`} sub="AAPL direct" tone="sell" />
              <AdvStat label="SWARM VIEW" value="SELL 58%" sub="strong consensus" tone="sell" />
              <AdvStat label="AGENTS RELEVANT" value="87/100" sub="cited seed entities" />
              <AdvStat label="CONFIDENCE" value="HIGH" sub="3-round convergence" tone="buy" />
            </div>

            {/* Quick holding view */}
            <div className="adv-quick-holdings">
              <div className="label" style={{marginBottom:12}}>SWARM VIEW ON YOUR HOLDINGS</div>
              {holdingAnalysis.map(h => (
                <AdvHoldingRow key={h.ticker} h={h} totalValue={totalValue} />
              ))}
            </div>
          </div>
        )}

        {tab === 'holdings' && (
          <div className="adv-holdings-detail">
            {holdingAnalysis.map(h => (
              <div key={h.ticker} className="adv-holding-card">
                <div className="adv-hc-head">
                  <div className="adv-hc-ticker">{h.ticker}</div>
                  <div className="adv-hc-value">
                    <div className="adv-hc-val mono">${h.last.toFixed(2)}</div>
                    <div className="label">{h.shares} sh · ${(h.value/1000).toFixed(0)}K · {((h.value/totalValue)*100).toFixed(1)}%</div>
                  </div>
                  <div className={`adv-hc-rec adv-rec-${h.recTone}`}>{h.rec}</div>
                  <div className="adv-hc-agents label">{h.agents} agents analyzed</div>
                </div>
                <div className="adv-hc-sentiment">
                  <div className="adv-sentiment-bar">
                    <div className="adv-sent-fill"
                      style={{
                        width: `${Math.abs(h.sentiment)*100}%`,
                        background: h.sentiment < 0 ? 'var(--sell)' : 'var(--buy)',
                        marginLeft: h.sentiment < 0 ? `${50 - Math.abs(h.sentiment)*50}%` : '50%',
                      }} />
                    <div className="adv-sent-center" />
                  </div>
                  <div className="adv-sent-label">
                    <span>BEARISH</span>
                    <span className="mono" style={{color: h.sentiment < 0 ? 'var(--sell)' : 'var(--buy)'}}>
                      {h.sentiment >= 0 ? '+' : ''}{(h.sentiment*100).toFixed(0)}%
                    </span>
                    <span>BULLISH</span>
                  </div>
                </div>
                <div className="adv-hc-body">{h.rationale}</div>
                <div className="adv-hc-footer">
                  <div><span className="label">RISK</span> <span className="adv-risk-text">{h.risk}</span></div>
                  <div><span className="label">UPSIDE</span> <span className="adv-up-text">{h.upside}</span></div>
                </div>
              </div>
            ))}
          </div>
        )}

        {tab === 'risk' && (
          <div className="adv-risk-view">
            <div className="adv-risk-matrix">
              <div className="label" style={{marginBottom:16}}>RISK / OPPORTUNITY MATRIX · SEED-SPECIFIC</div>
              <div className="adv-matrix-grid">
                <div className="adv-matrix-axis-y label">HIGH IMPACT</div>
                <div className="adv-matrix-cells">
                  {[
                    { ticker:'AAPL', x: 78, y: 82, label:'Sell 15–25%', tone:'sell' },
                    { ticker:'NVDA', x: 62, y: 42, label:'Add on dip', tone:'buy' },
                    { ticker:'GOOGL', x: 38, y: 55, label:'Monitor', tone:'hold' },
                    { ticker:'MSFT', x: 22, y: 28, label:'No action', tone:'hold' },
                    { ticker:'META', x: 18, y: 22, label:'No action', tone:'hold' },
                  ].map(p => (
                    <div key={p.ticker} className={`adv-matrix-node adv-mn-${p.tone}`}
                      style={{left:`${p.x}%`, top:`${100-p.y}%`}}>
                      <div className="adv-mn-label">{p.ticker}</div>
                    </div>
                  ))}
                  <div className="adv-matrix-quadrant-label tl">HIGH RISK<br/>HIGH IMPACT</div>
                  <div className="adv-matrix-quadrant-label tr">HIGH OPP<br/>HIGH IMPACT</div>
                  <div className="adv-matrix-quadrant-label bl">LOW RISK<br/>LOW IMPACT</div>
                  <div className="adv-matrix-quadrant-label br">HIGH OPP<br/>LOW IMPACT</div>
                  <div className="adv-matrix-crosshair-h" />
                  <div className="adv-matrix-crosshair-v" />
                </div>
                <div className="adv-matrix-axis-y label" style={{bottom:0, top:'auto'}}>LOW IMPACT</div>
                <div className="adv-matrix-axis-x">
                  <span className="label">LOW PROBABILITY</span>
                  <span className="label">HIGH PROBABILITY</span>
                </div>
              </div>
            </div>

            <div className="adv-scenarios">
              <div className="label" style={{marginBottom:12}}>SCENARIO ANALYSIS</div>
              {[
                { scenario: 'Deal confirmed at $500B', prob: '~35%', aapl: '+8–12%', note: 'Acquisition premium baked in. Short-term spike likely.' },
                { scenario: 'Deal blocked by FTC', prob: '~45%', aapl: '-4–8%', note: 'Overhang clears but narrative deflation follows.' },
                { scenario: 'Deal restructured (partial stake)', prob: '~15%', aapl: '+2–4%', note: 'Compromise satisfies regulatory; limited synergy.' },
                { scenario: 'Anthropic denies publicly', prob: '~5%', aapl: '-2–5%', note: 'Rumor premium collapses quickly.' },
              ].map((s, i) => (
                <div key={i} className="adv-scenario-row">
                  <div className="adv-sc-scenario">{s.scenario}</div>
                  <div className="adv-sc-prob mono">{s.prob}</div>
                  <div className={`adv-sc-aapl mono ${s.aapl.startsWith('+') ? 'pos' : 'neg'}`}>{s.aapl}</div>
                  <div className="adv-sc-note">{s.note}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {tab === 'isolation' && (
          <div className="adv-isolation">
            <div className="adv-iso-hero">
              <div className="adv-iso-arch">
                <div className="adv-iso-layer swarm">
                  <div className="adv-iso-layer-title">Swarm Layer</div>
                  <div className="adv-iso-layer-desc">100 agents · 3 rounds · real market data</div>
                  <div className="adv-iso-items">
                    <div className="adv-iso-item">✓ Sees: seed rumor</div>
                    <div className="adv-iso-item">✓ Sees: yfinance, FRED, news, filings</div>
                    <div className="adv-iso-item adv-iso-no">✗ Never sees: your holdings</div>
                    <div className="adv-iso-item adv-iso-no">✗ Never sees: your cost basis</div>
                  </div>
                </div>
                <div className="adv-iso-arrow">↓ consensus only</div>
                <div className="adv-iso-layer orchestrator">
                  <div className="adv-iso-layer-title">Orchestrator Layer</div>
                  <div className="adv-iso-layer-desc">Post-simulation synthesis only</div>
                  <div className="adv-iso-items">
                    <div className="adv-iso-item">✓ Reads: swarm consensus output</div>
                    <div className="adv-iso-item">✓ Reads: your portfolio CSV</div>
                    <div className="adv-iso-item adv-iso-no">✗ No direct API access</div>
                    <div className="adv-iso-item adv-iso-no">✗ No network calls</div>
                  </div>
                </div>
              </div>
              <div className="adv-iso-explain">
                <h3>Why this architecture matters</h3>
                <p>If agents knew your holdings, they would be susceptible to position-confirmation bias — reasoning toward outcomes that benefit your portfolio rather than the most accurate market analysis. The isolation wall between the two layers prevents this.</p>
                <p>The orchestrator reads only the consensus output — signals, rationales, influence graph — never the raw agent prompts. Your portfolio data is read once, locally, and never persisted to any database or log.</p>
                <div className="adv-iso-audit">
                  <Icon name="doc" size={13} />
                  <span>Full audit log available at <span className="mono">~/.alphaswarm/advisory-audit.jsonl</span></span>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function AdvStat({ label, value, sub, tone }) {
  return (
    <div className="adv-stat" data-tone={tone}>
      <div className="label">{label}</div>
      <div className="adv-stat-v">{value}</div>
      {sub && <div className="adv-stat-sub">{sub}</div>}
    </div>
  );
}

function AdvHoldingRow({ h, totalValue }) {
  const negW = Math.max(0, -h.sentiment) * 100;
  const posW = Math.max(0, h.sentiment) * 100;
  return (
    <div className="adv-qh-row">
      <div className="adv-qh-ticker">{h.ticker}</div>
      <div className="adv-qh-shares mono">{h.shares} sh</div>
      <div className="adv-qh-val mono">${(h.value/1000).toFixed(0)}K</div>
      <div className="adv-qh-weight mono">{((h.value/totalValue)*100).toFixed(1)}%</div>
      <div className="adv-qh-sent-bar">
        <div className="adv-qs-neg" style={{width:`${negW/2}%`}} />
        <div className="adv-qs-mid" />
        <div className="adv-qs-pos" style={{width:`${posW/2}%`}} />
      </div>
      <div className={`adv-qh-signal mono sig-${h.swarmSignal.toLowerCase()}`}>{h.swarmSignal}</div>
      <div className={`adv-qh-rec adv-rec-${h.recTone}`}>{h.rec}</div>
    </div>
  );
}

Object.assign(window, {
  SignalWire, ModelStatus, DataSourcesTakeover,
  AdvisoryV2, AdvStat, AdvHoldingRow,
  ReportModalV2, ConvergenceFlow, InfluenceChart, Moment, Followup
});

// ──────────────────────────────────────────────────────────────────────
// ──────────────────────────────────────────────────────────────────────
function ReportModalV2({ onClose }) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal report-v2" onClick={e => e.stopPropagation()}>
        {/* sticky header */}
        <div className="rv2-head">
          <div className="rv2-head-left">
            <Icon name="doc" size={14} />
            <span className="label">REPORT · C_2026_0418_A1</span>
          </div>
          <div className="rv2-head-right">
            <button className="btn ghost"><Icon name="doc" /> Export .md</button>
            <button className="btn ghost"><Icon name="brief" /> Export .pdf</button>
            <button className="btn ghost" onClick={onClose}><Icon name="close" /></button>
          </div>
        </div>

        <div className="rv2-scroll">

          {/* HERO */}
          <div className="rv2-hero">
            <div className="rv2-kicker label">
              APR 18 2026 · 09:42–09:47 · CYCLE C_2026_0418_A1
            </div>
            <h1 className="rv2-title">
              Compute-scarcity skepticism overrides acquisition hype.
              <span className="rv2-title-sub">Swarm converges <em>SELL 58%</em> by round three.</span>
            </h1>
            <div className="rv2-seed">
              <span className="label">SEED</span>
              <span className="rv2-seed-text">"Apple acquiring Anthropic for $500B"</span>
            </div>

            {/* marquee stats */}
            <div className="rv2-stats">
              <div className="rv2-stat">
                <div className="label">CONSENSUS</div>
                <div className="rv2-stat-v" style={{color: 'var(--sell)'}}>SELL 58%</div>
                <div className="rv2-stat-sub">from BUY 44% @ R1</div>
              </div>
              <div className="rv2-stat">
                <div className="label">FLIPS</div>
                <div className="rv2-stat-v">18<span className="rv2-stat-unit">/100</span></div>
                <div className="rv2-stat-sub">14 BUY→SELL · 3 HOLD→SELL · 1 SELL→HOLD</div>
              </div>
              <div className="rv2-stat">
                <div className="label">DURATION</div>
                <div className="rv2-stat-v mono">4:18</div>
                <div className="rv2-stat-sub">local · llama3.3:70b · 8 slots</div>
              </div>
              <div className="rv2-stat">
                <div className="label">DATA PULLS</div>
                <div className="rv2-stat-v mono">2,927</div>
                <div className="rv2-stat-sub">43% cached · 27 errors · 82 MB</div>
              </div>
            </div>
          </div>

          {/* CONVERGENCE FLOW — Sankey-esque round-by-round */}
          <section className="rv2-section">
            <div className="rv2-section-head">
              <h2>Convergence</h2>
              <div className="label">ROUND-BY-ROUND SIGNAL DISTRIBUTION</div>
            </div>
            <ConvergenceFlow />
            <p className="rv2-prose">
              Round 1 split three ways — Quants and Insiders went <em>SELL</em> early on compute-scarcity
              logic, while Degens and Whales started <em>BUY</em> on acquisition-premium reasoning.
              By Round 2, Q-03's rationale citing Anthropic's existing Google TPU commitments had
              propagated through the Insiders and Suits brackets, tipping 14 agents. The Policy Wonks
              bracket flipped <em>unanimously</em> after P-02 introduced FTC-review precedent.
            </p>
          </section>

          {/* KEY MOMENTS */}
          <section className="rv2-section">
            <div className="rv2-section-head">
              <h2>Key moments</h2>
              <div className="label">THREE BEATS THAT SHAPED THE CYCLE</div>
            </div>
            <div className="rv2-moments">
              <Moment t="01:47" title="Q-03 introduces compute-scarcity thesis"
                body="Quants anchor. 'Pull-through narrative ignores existing OpenAI licensing leverage.' Cited by 31 downstream agents — the highest out-degree of the cycle." />
              <Moment t="02:34" title="P-02 cites FTC precedent"
                body="Policy Wonks bracket flips unanimously. 'FTC Lina Khan successor still hawkish on vertical AI integration.' Catalyzed 3 cross-bracket flips within 12s." />
              <Moment t="03:21" title="Degens hold the line"
                body="Despite 18 flips across the swarm, Degens sustain BUY cluster. D-14's options-flow rationale escalates confidence from 0.62 → 0.81 — the only bracket to resist." />
            </div>
          </section>

          {/* DISSENT */}
          <section className="rv2-section">
            <div className="rv2-section-head">
              <h2>Dissent</h2>
              <div className="label">AGENTS WHO RESISTED CONSENSUS</div>
            </div>
            <div className="rv2-dissent">
              {[
                { id: 'D-14', bracket: 'Degens',  stance: 'BUY',  tone: 'buy',  conf: '0.81', note: 'Maintained BUY through all rounds. Cited unusual options volume on $220 strikes. Confidence grew under pressure.' },
                { id: 'W-04', bracket: 'Whales',  stance: 'HOLD', tone: 'hold', conf: '0.72', note: 'Decade-horizon thesis. Treated rumor volatility as noise. Unmoved by FTC precedent citation.' },
                { id: 'A-11', bracket: 'Agents',  stance: 'BUY',  tone: 'buy',  conf: '0.95', note: 'Algorithmic rule-set. No discretionary input. Included for reference — represents pure quantitative dissent.' },
              ].map(d => (
                <div key={d.id} className="rv2-dissent-row">
                  <div className="rv2-dissent-id mono">{d.id}</div>
                  <div className="rv2-dissent-bracket label">{d.bracket}</div>
                  <div className="rv2-dissent-stance" data-tone={d.tone}>{d.stance}</div>
                  <div className="rv2-dissent-conf mono">conf {d.conf}</div>
                  <div className="rv2-dissent-note">{d.note}</div>
                </div>
              ))}
            </div>
          </section>

          {/* INFLUENCE TOPOLOGY */}
          <section className="rv2-section">
            <div className="rv2-section-head">
              <h2>Influence topology</h2>
              <div className="label">TOP OUT-DEGREE · PERSISTED TO NEO4J</div>
            </div>
            <InfluenceChart />
            <p className="rv2-prose">
              The Quants→Suits channel activated 9 times — the strongest cross-bracket link of the
              cycle. Doom-Posters, despite high message volume, failed to influence any downstream
              bracket; citations stayed within their own cluster.
            </p>
          </section>

          {/* FOLLOW-UPS */}
          <section className="rv2-section">
            <div className="rv2-section-head">
              <h2>Recommended follow-ups</h2>
              <div className="label">COUNTERFACTUALS WORTH RUNNING</div>
            </div>
            <div className="rv2-followups">
              <Followup n="01" title="Shock with DOJ filing confirmation"
                body="Does the current SELL consensus hold under regulatory certainty, or does it deepen?" />
              <Followup n="02" title="Inject compute-supply resolution"
                body="Release Google TPU capacity as a counter-event. Measure Quants-bracket signal drift specifically." />
              <Followup n="03" title="Re-run with doubled Degens weight"
                body="Did D-14's dissent represent signal or noise? Amplify the bracket to find out." />
            </div>
          </section>

          <footer className="rv2-foot">
            <span className="label">ALPHASWARM · LOCAL · NO TELEMETRY</span>
            <span className="label">GENERATED 2026-04-18 09:47:22 UTC</span>
          </footer>

        </div>
      </div>
    </div>
  );
}

// Mini convergence chart: 3 stacked bars (R1, R2, R3) with BUY/SELL/HOLD
function ConvergenceFlow() {
  const rounds = [
    { r: 'R1', buy: 44, sell: 31, hold: 25 },
    { r: 'R2', buy: 32, sell: 45, hold: 23 },
    { r: 'R3', buy: 22, sell: 58, hold: 20 },
  ];
  return (
    <div className="cv-flow">
      {rounds.map((rd, i) => (
        <div key={rd.r} className="cv-col">
          <div className="cv-bar">
            <div className="cv-seg buy"  style={{height: `${rd.buy}%`}}><span className="cv-n">{rd.buy}</span></div>
            <div className="cv-seg hold" style={{height: `${rd.hold}%`}}><span className="cv-n">{rd.hold}</span></div>
            <div className="cv-seg sell" style={{height: `${rd.sell}%`}}><span className="cv-n">{rd.sell}</span></div>
          </div>
          <div className="cv-r label">{rd.r}</div>
        </div>
      ))}
      <div className="cv-legend">
        <div><span className="cv-dot buy" /> BUY</div>
        <div><span className="cv-dot hold" /> HOLD</div>
        <div><span className="cv-dot sell" /> SELL</div>
      </div>
    </div>
  );
}

function InfluenceChart() {
  const rows = [
    { id: 'Q-03', bracket: 'Quants',       out: 31 },
    { id: 'P-02', bracket: 'Policy Wonks', out: 22 },
    { id: 'I-04', bracket: 'Insiders',     out: 18 },
    { id: 'M-06', bracket: 'Macro',        out: 14 },
    { id: 'X-01', bracket: 'Doom-Posters', out: 11 },
    { id: 'U-02', bracket: 'Suits',        out:  9 },
    { id: 'S-01', bracket: 'Sovereigns',   out:  7 },
  ];
  const max = 31;
  return (
    <div className="infl-chart">
      {rows.map(r => (
        <div key={r.id} className="infl-row">
          <span className="infl-id mono">{r.id}</span>
          <span className="infl-bracket label">{r.bracket}</span>
          <div className="infl-bar-wrap">
            <div className="infl-bar" style={{width: `${(r.out/max)*100}%`}} />
          </div>
          <span className="infl-n mono">{r.out}</span>
        </div>
      ))}
    </div>
  );
}

function Moment({ t, title, body }) {
  return (
    <div className="rv2-moment">
      <div className="rv2-moment-t mono">{t}</div>
      <div>
        <div className="rv2-moment-title">{title}</div>
        <div className="rv2-moment-body">{body}</div>
      </div>
    </div>
  );
}

function Followup({ n, title, body }) {
  return (
    <div className="rv2-followup">
      <div className="rv2-followup-n">{n}</div>
      <div>
        <div className="rv2-followup-title">{title}</div>
        <div className="rv2-followup-body">{body}</div>
      </div>
      <button className="btn ghost-btn rv2-followup-run" title="Run this counterfactual">
        <Icon name="play" />
      </button>
    </div>
  );
}

// (merged into new Object.assign above)
