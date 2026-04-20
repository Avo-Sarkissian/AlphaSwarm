// Settings — full-screen takeover. Keys, model, thresholds, bracket weights.
import { useState } from 'react';
import { Icon } from './icons';

export function Settings({ onClose }) {
  const [s, setS] = useState({
    model: 'llama3.3:70b',
    memThreshold: 90,
    slotMax: 8,
    agentCount: 100,
    telemetry: false,
    cacheTtl: 300,
    keysPath: '~/.alphaswarm/keys.toml',
    storageDir: '~/.alphaswarm/cycles',
    weights: {
      quants: 14, degens: 12, sovereigns: 8, macro: 12, suits: 10,
      insiders: 10, agents: 10, doom_posters: 8, policy_wonks: 8, whales: 8,
    }
  });
  const [section, setSection] = useState('runtime');
  const setWeight = (k, v) => setS(x => ({...x, weights: {...x.weights, [k]: Math.max(0, Math.min(40, Number(v) || 0))}}));
  const totalAgents = Object.values(s.weights).reduce((a,b) => a+b, 0);

  const sections = [
    { k: 'runtime',  label: 'Runtime' },
    { k: 'model',    label: 'Model' },
    { k: 'brackets', label: 'Brackets' },
    { k: 'keys',     label: 'Data keys' },
    { k: 'storage',  label: 'Storage' },
    { k: 'privacy',  label: 'Privacy' },
  ];

  return (
    <div className="st-takeover">
      <div className="st-head">
        <div className="st-head-left">
          <span className="label" style={{color: 'var(--text-3)'}}>CONFIGURATION</span>
          <span className="st-title">Settings</span>
        </div>
        <div className="st-head-right">
          <button className="btn ghost" onClick={onClose}>Cancel</button>
          <button className="btn primary" onClick={onClose}>Save & close</button>
        </div>
      </div>

      <div className="st-body">
        <div className="st-nav">
          {sections.map(x => (
            <button key={x.k} className="st-nav-btn" data-active={section === x.k}
              onClick={() => setSection(x.k)}>{x.label}</button>
          ))}
          <div className="st-nav-foot">
            <div className="label">ALPHASWARM v0.7.2</div>
            <div className="mono" style={{fontSize:11, color:'var(--text-3)', marginTop:4}}>commit 9f2a1b · local only</div>
          </div>
        </div>

        <div className="st-content">
          {section === 'runtime' && (
            <>
              <SettingGroup title="Memory ceiling" desc="Inference pauses when RAM usage crosses this threshold. Agents checkpoint their state and resume when safe.">
                <div className="st-slider-row">
                  <input type="range" min="50" max="98" value={s.memThreshold}
                    onChange={e => setS(x => ({...x, memThreshold: Number(e.target.value)}))} />
                  <div className="st-slider-val mono">{s.memThreshold}%</div>
                </div>
                <div className="st-meter">
                  <div className="st-meter-track">
                    <div className="st-meter-safe"  style={{width: '70%'}}><span>safe</span></div>
                    <div className="st-meter-warn"  style={{width: '20%'}}><span>caution</span></div>
                    <div className="st-meter-crit"  style={{width: '10%'}}><span>critical</span></div>
                    <div className="st-meter-mark" style={{left: `${s.memThreshold}%`}} />
                  </div>
                </div>
              </SettingGroup>

              <SettingGroup title="Concurrent inference slots" desc="How many agents can be thinking at once. Higher = faster cycles, but more RAM pressure. Your machine supports up to 16.">
                <div className="st-seg">
                  {[4,6,8,10,12,16].map(n => (
                    <button key={n} data-active={s.slotMax === n}
                      onClick={() => setS(x => ({...x, slotMax: n}))}>{n}</button>
                  ))}
                </div>
                <div className="st-help">
                  <span style={{color:'var(--text-3)'}}>Recommendation:</span>
                  <span className="mono" style={{color:'var(--accent)'}}>8 slots</span>
                  <span style={{color:'var(--text-3)'}}>for llama3.3:70b on 48GB RAM</span>
                </div>
              </SettingGroup>

              <SettingGroup title="Agent population" desc="Total number of personas per cycle. Must match bracket weights below.">
                <div className="st-seg">
                  {[50, 100, 150, 200].map(n => (
                    <button key={n} data-active={s.agentCount === n}
                      onClick={() => setS(x => ({...x, agentCount: n}))}>{n}</button>
                  ))}
                </div>
              </SettingGroup>

              <SettingGroup title="Cache TTL" desc="How long data-source responses are cached. Lower values = fresher data, more API calls.">
                <div className="st-slider-row">
                  <input type="range" min="30" max="3600" step="30" value={s.cacheTtl}
                    onChange={e => setS(x => ({...x, cacheTtl: Number(e.target.value)}))} />
                  <div className="st-slider-val mono">{s.cacheTtl < 60 ? `${s.cacheTtl}s` : `${Math.round(s.cacheTtl/60)}m`}</div>
                </div>
              </SettingGroup>
            </>
          )}

          {section === 'model' && (
            <>
              <SettingGroup title="Active model" desc="All 100 agents share one Ollama model. Switching requires a cycle restart.">
                <div className="st-model-list">
                  {[
                    { k: 'llama3.3:70b',   size: '42 GB', ram: '48 GB', status: 'active', speed: 'medium', quality: 'excellent' },
                    { k: 'llama3.1:8b',    size: '4.7 GB', ram: '8 GB',  status: 'available', speed: 'fast',  quality: 'good' },
                    { k: 'qwen2.5:72b',    size: '47 GB', ram: '52 GB', status: 'available', speed: 'slow',  quality: 'excellent' },
                    { k: 'mistral-small3', size: '14 GB', ram: '18 GB', status: 'available', speed: 'fast',  quality: 'very good' },
                    { k: 'deepseek-r1:70b',size: '43 GB', ram: '48 GB', status: 'downloading', speed: 'slow', quality: 'excellent' },
                  ].map(m => (
                    <button key={m.k} className="st-model-row"
                      data-active={s.model === m.k}
                      data-status={m.status}
                      onClick={() => m.status !== 'downloading' && setS(x => ({...x, model: m.k}))}>
                      <div className="st-model-name">
                        <span className="mono">{m.k}</span>
                        {m.status === 'active' && <span className="st-badge active">ACTIVE</span>}
                        {m.status === 'downloading' && <span className="st-badge dl">↓ 43% · 18min</span>}
                      </div>
                      <div className="st-model-meta">
                        <span>{m.size}</span>
                        <span>needs {m.ram} RAM</span>
                        <span>speed: {m.speed}</span>
                        <span>quality: {m.quality}</span>
                      </div>
                    </button>
                  ))}
                </div>
                <button className="st-add">+ Pull another model from Ollama</button>
              </SettingGroup>
            </>
          )}

          {section === 'brackets' && (
            <>
              <SettingGroup title="Bracket composition" desc={`Distribution of personas across the 10 brackets. Total must equal ${s.agentCount}. Currently: ${totalAgents}.`}>
                <div className="st-bracket-grid">
                  {Object.entries(s.weights).map(([k, v]) => (
                    <div key={k} className="st-bracket-row">
                      <div className="st-bracket-name">{k.replace(/_/g,' ')}</div>
                      <input type="range" min="0" max="30" value={v}
                        onChange={e => setWeight(k, e.target.value)} />
                      <input type="number" min="0" max="30" value={v}
                        onChange={e => setWeight(k, e.target.value)} className="st-bracket-num mono" />
                    </div>
                  ))}
                </div>
                <div className="st-bracket-total" data-ok={totalAgents === s.agentCount}>
                  <span className="label">TOTAL</span>
                  <span className="mono" style={{fontSize: 16, fontWeight: 600}}>{totalAgents} / {s.agentCount}</span>
                  {totalAgents !== s.agentCount && (
                    <span style={{color: 'var(--sell)', fontSize: 11}}>
                      {totalAgents > s.agentCount ? `${totalAgents - s.agentCount} over — trim some` : `${s.agentCount - totalAgents} under — add more`}
                    </span>
                  )}
                </div>
              </SettingGroup>
            </>
          )}

          {section === 'keys' && (
            <>
              <SettingGroup title="Data source credentials" desc="API keys for live data sources. Stored in keys.toml — never leaves your machine. Empty = use free/public tier (rate-limited).">
                <div className="st-keys">
                  {[
                    { id: 'fmp',    label: 'Financial Modeling Prep', set: true,  free: false, tier: 'Starter ($14/mo)' },
                    { id: 'finnhub',label: 'Finnhub',                  set: true,  free: true,  tier: 'Free (60 req/min)' },
                    { id: 'fred',   label: 'FRED (St. Louis Fed)',     set: true,  free: true,  tier: 'Free · unlimited' },
                    { id: 'sec',    label: 'SEC EDGAR',                set: false, free: true,  tier: 'Free · no key needed' },
                    { id: 'newsapi',label: 'NewsAPI',                  set: false, free: true,  tier: 'Not configured' },
                    { id: 'reddit', label: 'Reddit',                   set: true,  free: true,  tier: 'OAuth · 60 req/min' },
                    { id: 'alphav', label: 'Alpha Vantage',            set: false, free: true,  tier: 'Not configured' },
                    { id: 'yfin',   label: 'yfinance',                 set: true,  free: true,  tier: 'No key · scraped' },
                    { id: 'polygon',label: 'Polygon.io',               set: false, free: false, tier: 'Not configured' },
                    { id: 'tweet',  label: 'X (Twitter)',              set: false, free: false, tier: 'Not configured' },
                  ].map(k => (
                    <div key={k.id} className="st-key-row">
                      <div className="st-key-left">
                        <span className={`st-key-dot ${k.set ? 'set' : 'unset'}`} />
                        <span className="st-key-label">{k.label}</span>
                      </div>
                      <div className="st-key-tier">{k.tier}</div>
                      <button className="btn ghost" style={{height: 26}}>{k.set ? 'Edit' : 'Add key'}</button>
                    </div>
                  ))}
                </div>
                <div className="st-keys-foot">
                  <Icon name="lock" />
                  <span>Keys live in <span className="mono" style={{color:'var(--accent)'}}>{s.keysPath}</span> · chmod 600 · never logged · never transmitted</span>
                </div>
              </SettingGroup>
            </>
          )}

          {section === 'storage' && (
            <>
              <SettingGroup title="Cycle archive" desc="Every cycle is saved locally as a reproducible JSONL trace. Delete any time.">
                <div className="st-storage-stats">
                  <div className="st-storage-cell">
                    <span className="label">LOCATION</span>
                    <div className="mono" style={{color:'var(--text)', fontSize: 13, marginTop: 4}}>{s.storageDir}</div>
                  </div>
                  <div className="st-storage-cell">
                    <span className="label">CYCLES SAVED</span>
                    <div style={{fontFamily:'Newsreader, serif', fontSize: 22, color: 'var(--text)', marginTop: 4}}>247</div>
                  </div>
                  <div className="st-storage-cell">
                    <span className="label">DISK USED</span>
                    <div style={{fontFamily:'Newsreader, serif', fontSize: 22, color: 'var(--text)', marginTop: 4}}>2.14 GB</div>
                  </div>
                  <div className="st-storage-cell">
                    <span className="label">OLDEST</span>
                    <div className="mono" style={{color:'var(--text-2)', fontSize: 12, marginTop: 6}}>2026-01-04</div>
                  </div>
                </div>
                <div className="st-storage-actions">
                  <button className="btn ghost">Open in Finder</button>
                  <button className="btn ghost">Export archive as .tar</button>
                  <button className="btn ghost danger-text">Delete cycles older than 30 days</button>
                </div>
              </SettingGroup>

              <SettingGroup title="Retention policy" desc="Auto-prune old cycles.">
                <div className="st-seg">
                  {['Keep all', '90 days', '30 days', '7 days'].map(p => (
                    <button key={p} data-active={p === 'Keep all'}>{p}</button>
                  ))}
                </div>
              </SettingGroup>
            </>
          )}

          {section === 'privacy' && (
            <>
              <SettingGroup title="Local-first guarantees" desc="AlphaSwarm is designed to run entirely on your machine. Here's what crosses the network and what doesn't.">
                <div className="st-privacy">
                  <div className="st-privacy-row yes">
                    <span className="st-check">✓</span>
                    <div>
                      <div className="st-privacy-title">Inference stays local</div>
                      <div className="st-privacy-desc">All LLM calls go through Ollama on localhost. Prompts and rationales never leave your machine.</div>
                    </div>
                  </div>
                  <div className="st-privacy-row yes">
                    <span className="st-check">✓</span>
                    <div>
                      <div className="st-privacy-title">Cycles stay local</div>
                      <div className="st-privacy-desc">Every cycle is saved to {s.storageDir}. Nothing is uploaded.</div>
                    </div>
                  </div>
                  <div className="st-privacy-row warn">
                    <span className="st-check warn">!</span>
                    <div>
                      <div className="st-privacy-title">Data-source calls leave your machine</div>
                      <div className="st-privacy-desc">Agents fetch live data from yfinance, FRED, SEC, news providers, Reddit, etc. These are normal HTTP calls to public APIs. See the Signal Wire for an audit trail.</div>
                    </div>
                  </div>
                  <div className="st-privacy-row yes">
                    <span className="st-check">✓</span>
                    <div>
                      <div className="st-privacy-title">No telemetry</div>
                      <div className="st-privacy-desc">AlphaSwarm makes zero outbound calls for analytics, crash reporting, or anything else.</div>
                      <label className="st-checkbox" style={{marginTop: 8}}>
                        <input type="checkbox" disabled checked={!s.telemetry} />
                        <span>Hard-disabled at build time</span>
                      </label>
                    </div>
                  </div>
                </div>
              </SettingGroup>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function SettingGroup({ title, desc, children }) {
  return (
    <div className="st-group">
      <div className="st-group-head">
        <div className="st-group-title">{title}</div>
        {desc && <div className="st-group-desc">{desc}</div>}
      </div>
      <div className="st-group-body">{children}</div>
    </div>
  );
}
