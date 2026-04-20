// Modals: Interview, Report, Shock, Replay, Advisory
import { useState } from 'react';
import { Icon } from './icons';

export function InterviewModal({ agent, onClose }) {
  const [messages, setMessages] = useState([
    { role: 'agent', text: `I'm ${agent.id}, bracket ${agent.bracketDisplay}. I closed Round 3 on ${agent.signal.toUpperCase()} with ${(agent.confidence*100).toFixed(0)}% confidence. What would you like me to unpack?` },
  ]);
  const [input, setInput] = useState('');

  const send = () => {
    if (!input.trim()) return;
    const userMsg = input;
    const responses = {
      default: `I weighed peer rationale from Q-03 and I-04 heavily — both surfaced the Google TPU commitment issue. That shifted my signal from BUY to SELL between R1 and R2. My final confidence reflects the regulatory overhang.`,
      flip: `Round 1 I was bullish — narrative momentum. In Round 2 I read Q-03's DCF critique and I-04 on compute contracts. Evidence outweighed vibe. Flipped to SELL.`,
      risk: `Main downside: vertical AI integration precedent. Main upside: Apple's cash position absorbs regulatory delay cost. I weighted downside ~2.3x.`,
    };
    const pick = /flip|change|round/i.test(userMsg) ? 'flip' : /risk|downside/i.test(userMsg) ? 'risk' : 'default';
    setMessages(m => [...m, { role: 'user', text: userMsg }, { role: 'agent', text: responses[pick] }]);
    setInput('');
  };

  const sigClass = agent.signal === 'buy' ? 'sig-buy' : agent.signal === 'sell' ? 'sig-sell' : 'sig-hold';

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-head">
          <div style={{display:'flex', alignItems:'center', gap:10}}>
            <div className="chat-avatar" style={{width:36, height:36, fontSize:12}}>{agent.id}</div>
            <div>
              <div style={{fontSize:14, fontWeight:600}}>{agent.id} · <span style={{color:'var(--text-3)'}}>{agent.bracketDisplay}</span></div>
              <div className="label" style={{marginTop:2}}>
                <span className={`rationale-signal ${sigClass}`}>{agent.signal.toUpperCase()}</span>
                <span style={{marginLeft:8}}>Conf {(agent.confidence*100).toFixed(0)}% · 3 rounds · 47 peer reads</span>
              </div>
            </div>
          </div>
          <div className="sp" />
          <button className="btn ghost" onClick={onClose}><Icon name="close" /> Close</button>
        </div>
        <div className="modal-body">
          <div className="chat-log">
            {messages.map((m, i) => (
              <div key={i} className={`chat-msg ${m.role}`}>
                <div className="chat-avatar">{m.role === 'user' ? 'YOU' : agent.id}</div>
                <div className="chat-bubble">{m.text}</div>
              </div>
            ))}
          </div>
        </div>
        <div className="modal-foot" style={{gap:8}}>
          <div className="seed-input" style={{flex:1}}>
            <span className="prefix">›</span>
            <input value={input} onChange={e => setInput(e.target.value)} onKeyDown={e => e.key === 'Enter' && send()} placeholder={`Ask ${agent.id} about rationale, peer influence, risk weighting…`} />
          </div>
          <button className="btn primary" onClick={send}>Send</button>
        </div>
      </div>
    </div>
  );
}

export function ReportModal({ onClose }) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal modal-big" onClick={e => e.stopPropagation()}>
        <div className="modal-head">
          <Icon name="doc" size={16} />
          <span style={{fontFamily:"'JetBrains Mono', monospace", fontSize:11, letterSpacing:'0.12em', textTransform:'uppercase', color:'var(--text-2)'}}>REPORT · cycle c_2026_0418_a1</span>
          <div className="sp" />
          <button className="btn ghost"><Icon name="doc" /> Export .md</button>
          <button className="btn ghost" onClick={onClose}><Icon name="close" /> Close</button>
        </div>
        <div className="modal-body no-pad report">
          <div className="report-hero">
            <div className="report-meta">
              <span>SEED · "Apple acquiring Anthropic for $500B"</span>
              <span>3 ROUNDS · 100 AGENTS · 4M 18S</span>
              <span>GENERATED 2026-04-18 09:47</span>
            </div>
            <h1 style={{marginTop:10}}>Narrative of compute skepticism overrides acquisition hype — swarm converges SELL 58%.</h1>
          </div>

          <div className="report-section">
            <h3>Executive Summary</h3>
            <p>Across three rounds, the swarm migrated from a fragmented Round 1 (BUY 44%, SELL 31%, HOLD 25%) to a coherent bearish consensus (BUY 22%, SELL 58%, HOLD 20%). The decisive shift occurred in Round 2 when rationale from Q-03 and I-04 — both citing Anthropic's existing Google TPU commitments — propagated through Quants, Insiders, and Suits. The Degens bracket partially resisted, sustaining a speculative BUY cluster driven by options-flow rationale.</p>
          </div>

          <div className="report-section">
            <h3>Key Dissenting Voices</h3>
            <p><strong>D-14 (Degens)</strong> — maintained BUY through all three rounds despite peer pressure, citing unusual options volume on $220 strikes. Confidence escalated from 0.62 → 0.81.</p>
            <p><strong>W-04 (Whales)</strong> — held HOLD on a decade-horizon thesis; treated rumor volatility as noise.</p>
            <p><strong>A-11 (Agents)</strong> — algorithmic rule-set remained BUY throughout; no discretionary input.</p>
          </div>

          <div className="report-section">
            <h3>Signal Flips</h3>
            <p>18 agents flipped signal between Round 1 and Round 3. 14 moved BUY→SELL, 3 moved HOLD→SELL, 1 moved SELL→HOLD. The Policy Wonks bracket flipped unanimously from HOLD to SELL after P-02's FTC-review rationale was cited by 22 downstream agents.</p>
          </div>

          <div className="report-section">
            <h3>Influence Topology</h3>
            <p>Highest out-degree: <strong>Q-03</strong> (31 downstream citations), <strong>P-02</strong> (22), <strong>I-04</strong> (18). The cross-bracket influence link Quants→Suits activated 9 times, the strongest such channel of the cycle. INFLUENCED_BY graph persisted to Neo4j.</p>
          </div>

          <div className="report-section">
            <h3>Recommended Follow-ups</h3>
            <p>Re-run cycle with shock injection — specifically, DOJ filing confirmation — to observe whether the current consensus holds under regulatory certainty. Alternative: inject a compute-supply resolution (Google TPU release) and measure Quants-bracket signal drift.</p>
          </div>
        </div>
      </div>
    </div>
  );
}

export function ShockDrawer({ onClose, onInject }) {
  const [text, setText] = useState('DOJ files formal antitrust complaint against Apple–Anthropic deal');
  const presets = [
    'DOJ files formal antitrust complaint against Apple–Anthropic deal',
    'Fed cuts 50bp at emergency session',
    'Anthropic CEO denies acquisition talks publicly',
    'Treasury yields spike 40bp on inflation print',
  ];
  return (
    <div className="shock-drawer">
      <div className="hflex" style={{marginBottom:10}}>
        <Icon name="bolt" size={14} />
        <span className="label" style={{color:'var(--sell)'}}>Shock Injection · between rounds 2 & 3</span>
        <div className="sp" />
        <button className="btn ghost" onClick={onClose}><Icon name="close" /></button>
      </div>
      <div className="seed-input" style={{marginBottom:10}}>
        <span className="prefix">⚡</span>
        <input value={text} onChange={e => setText(e.target.value)} placeholder="Disruptive event text…" />
      </div>
      <div style={{display:'flex', flexWrap:'wrap', gap:6, marginBottom:12}}>
        {presets.map(p => (
          <button key={p} className="btn ghost" style={{fontSize:10, height:26}} onClick={() => setText(p)}>{p.length > 40 ? p.slice(0,40)+'…' : p}</button>
        ))}
      </div>
      <div className="hflex">
        <span className="label">Impact preview · ~{Math.floor(20 + (text.length*0.7))} agents re-evaluate</span>
        <div className="sp" />
        <button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn primary" onClick={() => { onInject && onInject(text); onClose(); }}><Icon name="bolt" /> Inject</button>
      </div>
    </div>
  );
}

export function AdvisoryModal({ onClose }) {
  // WAVE-1-NOTE: HOLDINGS is live-render path — Plan 04 wires GET /api/holdings.
  // Wave 1 renders with no holdings; Plan 04 will swap in a useHoldings() hook.
  const holdings = [];
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal modal-big" onClick={e => e.stopPropagation()}>
        <div className="modal-head">
          <Icon name="brief" size={16} />
          <span style={{fontFamily:"'JetBrains Mono', monospace", fontSize:11, letterSpacing:'0.12em', textTransform:'uppercase', color:'var(--text-2)'}}>PERSONALIZED ADVISORY · v6.0</span>
          <span style={{marginLeft:8, padding:'2px 6px', border:'1px solid var(--border)', borderRadius:3, fontSize:10, fontFamily:'JetBrains Mono', color:'var(--accent)'}}>ORCHESTRATOR-ONLY</span>
          <div className="sp" />
          <button className="btn ghost" onClick={onClose}><Icon name="close" /> Close</button>
        </div>
        <div className="modal-body">
          <div className="advisory-card">
            <span className="advisory-tag">Primary Recommendation</span>
            <div style={{fontSize:18, fontWeight:600, marginBottom:6, lineHeight:1.3}}>Consider trimming AAPL exposure 15–25% ahead of regulatory clarity.</div>
            <div style={{fontSize:13, color:'var(--text-2)', lineHeight:1.55}}>
              Your 1,200-share AAPL position (<span className="num">34.2%</span> of portfolio) sits against a swarm consensus of <strong style={{color:'var(--sell)'}}>SELL 58%</strong> with high agent concurrence on regulatory risk. Cost basis <span className="num">$142.30</span> vs last <span className="num">$218.40</span> — partial trim locks gains while preserving optional upside.
            </div>
          </div>

          <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:14, marginBottom:14}}>
            <div style={{padding:14, border:'1px solid var(--border)', borderRadius:6}}>
              <div className="label" style={{marginBottom:8}}>Swarm view on your holdings</div>
              {holdings.map(h => {
                const negW = Math.max(0, -h.sentiment) * 100;
                const posW = Math.max(0, h.sentiment) * 100;
                return (
                  <div key={h.ticker} className="holding-row">
                    <div className="ticker-logo">{h.ticker.slice(0,2)}</div>
                    <div>
                      <div style={{color:'var(--text)', fontSize:12}}>{h.ticker}</div>
                      <div style={{color:'var(--text-3)', fontSize:10}}>{h.shares} sh · ${h.basis.toFixed(2)}</div>
                    </div>
                    <div className="sent-bar">
                      <span className="neg" style={{width: `${negW}%`}} />
                      <span className="pos" style={{width: `${posW}%`}} />
                    </div>
                    <div style={{color: h.sentiment >= 0 ? 'var(--buy)' : 'var(--sell)', textAlign:'right', minWidth:44}}>
                      {h.sentiment >= 0 ? '+' : ''}{(h.sentiment*100).toFixed(0)}%
                    </div>
                  </div>
                );
              })}
            </div>
            <div style={{padding:14, border:'1px solid var(--border)', borderRadius:6}}>
              <div className="label" style={{marginBottom:8}}>Information isolation</div>
              <div style={{fontSize:12, color:'var(--text-2)', lineHeight:1.6}}>
                <p style={{marginBottom:8}}><strong style={{color:'var(--text)'}}>Swarm layer</strong> — reasoned on market data only (prices, news, filings). Never saw your holdings.</p>
                <p style={{marginBottom:8}}><strong style={{color:'var(--text)'}}>Orchestrator layer</strong> — synthesized this advisory post-simulation by cross-referencing swarm consensus against your portfolio CSV.</p>
                <p style={{color:'var(--text-3)'}}>No holdings data entered agent prompts. Audit log available.</p>
              </div>
            </div>
          </div>

          <div style={{padding:14, border:'1px solid var(--border)', borderRadius:6, background:'var(--bg-3)'}}>
            <div className="label" style={{marginBottom:8}}>Secondary signals</div>
            <div style={{display:'grid', gridTemplateColumns:'repeat(3, 1fr)', gap:10, fontSize:12}}>
              <div><div style={{color:'var(--buy)', fontWeight:600}}>NVDA — Hold / accumulate</div><div style={{color:'var(--text-2)', marginTop:4}}>Macro bracket constructive on compute scarcity; 3 agents cite AAPL/Anthropic failure as NVDA tailwind.</div></div>
              <div><div style={{color:'var(--hold)', fontWeight:600}}>MSFT — No action</div><div style={{color:'var(--text-2)', marginTop:4}}>Swarm view neutral; OpenAI partnership already priced in per Suits rationale.</div></div>
              <div><div style={{color:'var(--sell)', fontWeight:600}}>GOOGL — Monitor</div><div style={{color:'var(--text-2)', marginTop:4}}>TPU commitment visibility could shift if Anthropic renegotiates; 2 Insiders flagged.</div></div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export function ReplayBar({ cycle, round, onRound, onExit }) {
  return (
    <div className="replay-bar">
      <div className="label" style={{color:'var(--accent)'}}>
        <Icon name="replay" size={11} /> REPLAY · {cycle.id}
      </div>
      <button className="btn ghost" onClick={() => onRound(Math.max(1, round-1))}><Icon name="rewind" /></button>
      <div className="replay-track">
        <div className="replay-fill" style={{width: `${(round/3)*100}%`}} />
        <div className="replay-ticks">
          {['SEED','R1','R2','R3'].map((t, i) => (
            <span key={t} style={{color: i <= round ? 'var(--accent)' : 'var(--text-3)', cursor:'pointer'}} onClick={() => onRound(i)}>{t}</span>
          ))}
        </div>
      </div>
      <button className="btn ghost" onClick={() => onRound(Math.min(3, round+1))}><Icon name="forward" /></button>
      <button className="btn" onClick={onExit}>Exit replay</button>
    </div>
  );
}

export function CyclePickerModal({ onPick, onClose }) {
  // WAVE-1-NOTE: REPLAY_CYCLES was a mock-only design seed; Plan 03 wires /api/replay/cycles here.
  const cycles = [];
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()} style={{width:'min(720px, 94%)'}}>
        <div className="modal-head">
          <Icon name="replay" />
          <span style={{fontFamily:"'JetBrains Mono', monospace", fontSize:11, letterSpacing:'0.12em', textTransform:'uppercase', color:'var(--text-2)'}}>SELECT CYCLE TO REPLAY</span>
          <div className="sp" />
          <button className="btn ghost" onClick={onClose}><Icon name="close" /></button>
        </div>
        <div className="modal-body no-pad">
          {cycles.map(c => (
            <div key={c.id} style={{padding:'14px 20px', borderBottom:'1px solid var(--border)', cursor:'pointer', display:'grid', gridTemplateColumns:'1fr auto auto auto', gap:18, alignItems:'center'}}
              onClick={() => onPick(c)}
              onMouseOver={e => e.currentTarget.style.background='var(--bg-3)'}
              onMouseOut={e => e.currentTarget.style.background='transparent'}>
              <div>
                <div style={{fontSize:14, color:'var(--text)', marginBottom:4}}>"{c.seed}"</div>
                <div className="label">{c.id}</div>
              </div>
              <div className="label">{c.when}</div>
              <div className="label">{c.dur}</div>
              <div style={{fontFamily:'JetBrains Mono', fontSize:12, color: c.consensus.startsWith('BUY')?'var(--buy)':c.consensus.startsWith('SELL')?'var(--sell)':'var(--hold)'}}>{c.consensus}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
