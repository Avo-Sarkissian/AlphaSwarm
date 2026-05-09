// Interview V2 — full-screen takeover with signal trajectory, citation map, rationale log.

const { useState: useIV, useEffect: useIE, useRef: useIR, useMemo: useIM } = React;

// Bracket-aware persona responses
const PERSONA = {
  quants: {
    tone: 'terse, data-driven, cites specific figures',
    prompts: ['Walk me through the DCF model you ran.', 'What data sources shifted your confidence?', 'Which peer citation was highest signal?', 'What would change your position?'],
    responses: {
      dcf: 'EV/Revenue multiple at $500B implies 120x FY2025 revenue of ~$4.1B. Comps: OpenAI at ~80x, DeepMind (private) implied ~60x. Premium is unjustified unless Apple captures 90%+ of inference upside — which the Google TPU dependency makes structurally impossible.',
      sources: 'yfinance showed AAPL -0.8% pre-announcement, below SPX drift. SEC EDGAR confirmed no 8-K. That divergence — price softness with no disclosure — reads as smart money skepticism, not excitement.',
      peer: 'I-04\'s note on Anthropic\'s Google Cloud contract was the highest-signal cite. If true — and I weight it 0.82 — it means any acquirer inherits a 3-year compute liability. That\'s not in the deal price.',
      change: 'Regulatory clarity. If DOJ signals non-opposition AND Google terminates the TPU agreement by mutual consent, I flip BUY at this price. Neither looks likely within my 18-month model horizon.',
      default: 'My position is driven by one thing: the acquire-vs-operate cost curve for inference at scale. Apple does not have the model infra to run Claude independently. That gap is structural, not solvable with capital.',
    }
  },
  degens: {
    tone: 'high-energy, narrative-driven, talks about flow and momentum',
    prompts: ['What\'s the options market saying?', 'Are you chasing or leading this move?', 'What\'s your exit?', 'Did you read the Quants\' SELL thesis?'],
    responses: {
      options: '$220 calls printed 4× normal volume pre-announcement. That\'s not retail — that\'s a coordinated bet. I don\'t care if the deal makes sense fundamentally, the options market is betting it gets announced.',
      flow: 'Leading. I was in the $210 calls before Q-03 published anything. When the momentum is this clean — gap-up, high volume, unusual options — you ride it. Fundamentals catch up later or they don\'t.',
      exit: 'I\'m out at $225 or if the options flow reverses. Hard stop at $208. Not holding through an FTC filing — that\'s a different trade.',
      quants: 'Read it. The TPU argument is real. But Q-03 is pricing a 2-year outcome and I\'m pricing a 2-week outcome. We\'re both right about different things.',
      default: 'Look — 87% of rumors this size get officially denied within 48 hours or confirmed within 72. Either way, there\'s a vol event coming. I\'m long vol, not the deal.',
    }
  },
  policy_wonks: {
    tone: 'methodical, cites legal precedent, risk-focused on regulatory outcomes',
    prompts: ['Which FTC precedent concerns you most?', 'What\'s the realistic review timeline?', 'Could a structural remedy save the deal?', 'How do you weigh EU vs US risk?'],
    responses: {
      ftc: 'FTC v. Microsoft-Activision is the live precedent — vertical integration challenge, ultimately settled, but delayed 18 months. Apple-Anthropic is a stronger case for the government: AI infrastructure + consumer device + content = clear vertical foreclosure argument.',
      timeline: 'Second Request likely within 30 days. Full review 12–18 months. Deal certainty is functionally zero until the R&D phase closes. Equities are pricing a 65% close probability — I think that\'s 40% at best.',
      remedy: 'A behavioral remedy — non-discrimination for third-party models — is theoretically possible but historically weak in tech cases. The only structural remedy that works is a firewall between Apple Intelligence and Claude API, which defeats 80% of the synergy thesis.',
      eu: 'EU risk is additive, not duplicative. DMA Article 14 already puts Apple under gatekeeper obligations. Adding a 70B-parameter foundation model to the estate will trigger a separate Phase II investigation in Brussels, running parallel to the US review.',
      default: 'Policy is the terminal variable here. Everything else — synergies, model quality, integration timelines — is contingent on regulatory clearance. I weight regulatory failure at 60%.',
    }
  },
  whales: {
    tone: 'patient, contrarian, decade horizon, dismissive of short-term noise',
    prompts: ['Why are you holding in a SELL consensus?', 'What\'s the decade thesis on this rumor?', 'What would make you change from HOLD?', 'Are you building a position here?'],
    responses: {
      hold: 'Because the consensus has priced the regulatory risk twice — once in the options market, once in the swarm. When everyone is SELL, the asymmetric bet is HOLD or BUY. I\'m not there yet, but I\'m watching.',
      decade: 'Ten years from now, whether Apple acquires Anthropic or not, Apple will have model capabilities comparable to today\'s frontier. The question is build vs. buy. This rumor changes the timeline by 18 months, not the destination.',
      change: 'A meaningful pullback — AAPL below $190 — would make the risk/reward attractive enough to go BUY. At $218 with regulatory uncertainty, the premium is too thin for a decade hold.',
      position: 'Not adding at this price. Watching the reaction to the first DOJ statement. If the market overshoots on regulatory fear — which it usually does — that\'s when I step in.',
      default: 'My mandate is to be right over 10 years, not 10 days. This week\'s noise is irrelevant to that frame. I\'ll have a view worth hearing in about 6 months.',
    }
  },
  default: {
    tone: 'measured, analytical',
    prompts: ['What drove your signal?', 'Which peer influenced you most?', 'What\'s your confidence basis?', 'What would change your view?'],
    responses: {
      default: 'My analysis weighted the available signals across data sources and peer rationale. The compute-dependency thesis was well-supported across multiple independent agents — I treated that as strong evidence.',
      peer: 'I read rationale from Q-03 and I-04. Both converged on the same structural argument independently, which increased my confidence that it wasn\'t noise.',
      change: 'New information about the Google TPU contract — specifically a termination clause or exclusivity waiver — would materially change my position.',
      confidence: `My confidence of ${0}% reflects the signal strength in Round 2 after incorporating peer context. I would need contradicting evidence from at least 3 high-out-degree agents to revise downward.`,
    }
  }
};

function getPersona(bracket) {
  return PERSONA[bracket] || PERSONA.default;
}

function pickResponse(bracket, text) {
  const p = getPersona(bracket);
  const r = p.responses;
  const t = text.toLowerCase();
  // keyword matching
  const keys = Object.keys(r).filter(k => k !== 'default');
  for (const k of keys) {
    if (t.includes(k)) return r[k];
  }
  // fuzzy
  if (/flip|change|round|r1|r2/i.test(text)) return r.change || r.default;
  if (/risk|downside|ceiling|concern/i.test(text)) return r.change || r.default;
  if (/source|data|api|fetch/i.test(text)) return r.sources || r.default;
  if (/cite|peer|influence|read/i.test(text)) return r.peer || r.default;
  return r.default;
}

// Signal trajectory — mini sparkline across R1/R2/R3
function SignalTrajectory({ agent }) {
  const rounds = [
    { r: 1, signal: agent.flipped ? 'buy' : agent.signal, conf: agent.confidence * 0.72 },
    { r: 2, signal: agent.flipped ? 'buy' : agent.signal, conf: agent.confidence * 0.86 },
    { r: 3, signal: agent.signal, conf: agent.confidence },
  ];
  // If agent flipped, R1/R2 show opposite signal
  if (agent.flipped) {
    rounds[0].signal = agent.signal === 'sell' ? 'buy' : 'sell';
    rounds[1].signal = agent.signal;
  }
  const sigColor = s => s === 'buy' ? 'var(--buy)' : s === 'sell' ? 'var(--sell)' : 'var(--hold)';
  return (
    <div className="iv2-trajectory">
      <div className="label" style={{marginBottom: 10}}>SIGNAL TRAJECTORY</div>
      <div className="iv2-traj-track">
        {rounds.map((rd, i) => (
          <div key={rd.r} className="iv2-traj-col">
            <div className="iv2-traj-bar-wrap">
              <div className="iv2-traj-bar" style={{
                height: `${rd.conf * 100}%`,
                background: sigColor(rd.signal),
                boxShadow: i === 2 ? `0 0 8px ${sigColor(rd.signal)}` : 'none',
              }} />
            </div>
            <div className="iv2-traj-signal" style={{color: sigColor(rd.signal)}}>
              {rd.signal.toUpperCase()}
            </div>
            <div className="iv2-traj-label label">R{rd.r}</div>
            <div className="iv2-traj-conf mono">{(rd.conf * 100).toFixed(0)}%</div>
            {agent.flipped && i === 1 && <div className="iv2-flip-mark">↷ flip</div>}
          </div>
        ))}
      </div>
    </div>
  );
}

// Citation mini-graph — SVG showing in/out citations
function CitationGraph({ agent }) {
  const cited = ['Q-03', 'I-04'];   // agents this agent cited
  const citedBy = ['U-07', 'M-06', 'S-02']; // agents who cited this agent
  const cx = 100, cy = 80;
  const citedPos = cited.map((_, i) => ({ x: 38, y: 30 + i * 42 }));
  const byPos = citedBy.map((_, i) => ({ x: 162, y: 18 + i * 34 }));
  return (
    <div className="iv2-citations">
      <div className="label" style={{marginBottom: 10}}>CITATION NETWORK</div>
      <svg viewBox="0 0 200 160" width="100%" style={{display:'block'}}>
        {citedPos.map((p, i) => (
          <g key={i}>
            <line x1={p.x+18} y1={p.y+7} x2={cx-10} y2={cy} stroke="var(--text-3)" strokeWidth="0.8" strokeDasharray="3 2" markerEnd="url(#arrow)" />
            <rect x={p.x} y={p.y} width="36" height="14" rx="2" fill="var(--bg-3)" stroke="var(--border-2)" />
            <text x={p.x+18} y={p.y+9.5} textAnchor="middle" fill="var(--text-2)" fontSize="7.5" fontFamily="JetBrains Mono">{cited[i]}</text>
          </g>
        ))}
        {byPos.map((p, i) => (
          <g key={i}>
            <line x1={cx+10} y1={cy} x2={p.x} y2={p.y+7} stroke="var(--accent)" strokeWidth="0.8" opacity="0.6" markerEnd="url(#arrow2)" />
            <rect x={p.x} y={p.y} width="36" height="14" rx="2" fill="var(--bg-3)" stroke="var(--border-2)" />
            <text x={p.x+18} y={p.y+9.5} textAnchor="middle" fill="var(--text-2)" fontSize="7.5" fontFamily="JetBrains Mono">{citedBy[i]}</text>
          </g>
        ))}
        <defs>
          <marker id="arrow" markerWidth="5" markerHeight="5" refX="5" refY="2.5" orient="auto">
            <path d="M0,0 L5,2.5 L0,5" fill="var(--text-3)" />
          </marker>
          <marker id="arrow2" markerWidth="5" markerHeight="5" refX="5" refY="2.5" orient="auto">
            <path d="M0,0 L5,2.5 L0,5" fill="var(--accent)" opacity="0.7" />
          </marker>
        </defs>
        {/* center node */}
        <circle cx={cx} cy={cy} r="10" fill={agent.signal === 'buy' ? 'var(--buy)' : agent.signal === 'sell' ? 'var(--sell)' : 'var(--hold)'} />
        <text x={cx} y={cy+3.5} textAnchor="middle" fill="#000" fontSize="6.5" fontWeight="700" fontFamily="JetBrains Mono">{agent.id}</text>
      </svg>
      <div className="iv2-cite-legend">
        <div><span className="iv2-cite-dot cited" /> read {cited.length}</div>
        <div><span className="iv2-cite-dot citedby" /> cited by {citedBy.length}</div>
      </div>
    </div>
  );
}

// Main component
function InterviewV2({ agent, onClose }) {
  const persona = getPersona(agent.bracket);
  const [messages, setMessages] = useIV([
    { role: 'agent', ts: '09:47:02',
      text: `${agent.bracketDisplay}. Round 3 close: ${agent.signal.toUpperCase()}, confidence ${(agent.confidence*100).toFixed(0)}%.${agent.flipped ? ' I flipped from my Round 1 position.' : ''} Ask me anything about my reasoning.`
    }
  ]);
  const [input, setInput] = useIV('');
  const [tab, setTab] = useIV('chat'); // chat | rationale
  const [typing, setTyping] = useIV(false);
  const logRef = useIR(null);

  useIE(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [messages, typing]);

  const send = (text) => {
    const msg = text || input;
    if (!msg.trim()) return;
    setInput('');
    setMessages(m => [...m, { role: 'user', ts: new Date().toISOString().slice(11,19), text: msg }]);
    setTyping(true);
    setTimeout(() => {
      setTyping(false);
      setMessages(m => [...m, {
        role: 'agent',
        ts: new Date().toISOString().slice(11,19),
        text: pickResponse(agent.bracket, msg)
      }]);
    }, 900 + Math.random() * 600);
  };

  const roundRationales = [
    { r: 1, signal: agent.flipped ? (agent.signal === 'sell' ? 'buy' : 'sell') : agent.signal, conf: (agent.confidence*72).toFixed(0),
      text: 'Initial assessment based on seed context and my persona priors. Acquisition premium narratives typically overshoot on announcement day — but flow signals were ambiguous.' },
    { r: 2, signal: agent.signal, conf: (agent.confidence*86).toFixed(0),
      text: 'Read Q-03\'s DCF analysis (high-weight, well-sourced) and I-04\'s note on Google TPU commitments. Both pointed to structural integration risk. Updated my model.' },
    { r: 3, signal: agent.signal, conf: (agent.confidence*100).toFixed(0),
      text: 'Consensus forming around regulatory and compute-dependency thesis. No new counter-evidence. Maintained signal with increased conviction. Final position locked.' },
  ];

  const sigColor = s => s === 'buy' ? 'var(--buy)' : s === 'sell' ? 'var(--sell)' : 'var(--hold)';

  return (
    <div className="iv2-takeover">
      {/* header */}
      <div className="iv2-head">
        <div className="iv2-head-left">
          <button className="btn ghost-btn" onClick={onClose}><Icon name="close" /></button>
          <div className="iv2-agent-id">
            <div className="iv2-id-pill" style={{background: sigColor(agent.signal)}}>
              {agent.id}
            </div>
            <div>
              <div className="iv2-bracket">{agent.bracketDisplay}</div>
              <div className="label">CYCLE C_2026_0418_A1 · {agent.flipped ? 'FLIPPED' : 'HELD SIGNAL'}</div>
            </div>
          </div>
          <div className={`rationale-signal sig-${agent.signal}`} style={{marginLeft: 8, fontSize: 11}}>
            {agent.signal.toUpperCase()} {(agent.confidence*100).toFixed(0)}%
          </div>
        </div>
        <div className="iv2-head-right">
          <span className="label" style={{color:'var(--accent)', fontSize: 11}}>
            PERSONA ACTIVE · {persona.tone}
          </span>
        </div>
      </div>

      <div className="iv2-body">
        {/* LEFT — context rail */}
        <div className="iv2-left">
          <SignalTrajectory agent={agent} />
          <div className="iv2-divider" />
          <CitationGraph agent={agent} />
          <div className="iv2-divider" />
          <div className="iv2-stats">
            <div className="label" style={{marginBottom: 8}}>CYCLE STATS</div>
            {[
              ['Peer reads',   '47'],
              ['Out-degree',   '6'],
              ['In-degree',    '3'],
              ['Shock impact', agent.bracket === 'agents' ? 'none' : 'mild'],
              ['Data sources', '4'],
            ].map(([k,v]) => (
              <div key={k} className="iv2-stat-row">
                <span className="iv2-stat-k label">{k}</span>
                <span className="iv2-stat-v mono">{v}</span>
              </div>
            ))}
          </div>
        </div>

        {/* CENTER — chat */}
        <div className="iv2-center">
          <div className="iv2-tabs">
            <button className="iv2-tab" data-active={tab === 'chat'} onClick={() => setTab('chat')}>Interview</button>
            <button className="iv2-tab" data-active={tab === 'rationale'} onClick={() => setTab('rationale')}>Rationale log</button>
          </div>

          {tab === 'chat' && (
            <>
              <div className="iv2-log" ref={logRef}>
                {messages.map((m, i) => (
                  <div key={i} className={`iv2-msg iv2-msg-${m.role}`}>
                    <div className="iv2-msg-meta">
                      <span className="iv2-msg-who">{m.role === 'user' ? 'YOU' : agent.id}</span>
                      <span className="iv2-msg-ts mono">{m.ts}</span>
                    </div>
                    <div className="iv2-bubble" data-role={m.role}>{m.text}</div>
                  </div>
                ))}
                {typing && (
                  <div className="iv2-msg iv2-msg-agent">
                    <div className="iv2-msg-meta"><span className="iv2-msg-who">{agent.id}</span></div>
                    <div className="iv2-bubble iv2-typing" data-role="agent">
                      <span /><span /><span />
                    </div>
                  </div>
                )}
              </div>
              {/* suggested prompts */}
              <div className="iv2-prompts">
                {persona.prompts.slice(0,3).map((p,i) => (
                  <button key={i} className="iv2-prompt" onClick={() => send(p)}>{p}</button>
                ))}
              </div>
              <div className="iv2-input-row">
                <div className="seed-input" style={{flex:1, height:38}}>
                  <span className="prefix">›</span>
                  <input
                    value={input}
                    onChange={e => setInput(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && !e.shiftKey && send()}
                    placeholder={`Ask ${agent.id} anything…`}
                    autoFocus
                  />
                </div>
                <button className="btn primary" onClick={() => send()}>Ask</button>
              </div>
            </>
          )}

          {tab === 'rationale' && (
            <div className="iv2-rationale-log">
              {roundRationales.map(rd => (
                <div key={rd.r} className="iv2-round-block">
                  <div className="iv2-round-head">
                    <span className="iv2-round-num">Round {rd.r}</span>
                    <span className={`rationale-signal sig-${rd.signal}`}>{rd.signal.toUpperCase()}</span>
                    <span className="iv2-round-conf mono">{rd.conf}% conf</span>
                    {rd.r > 1 && rd.signal !== roundRationales[0].signal && (
                      <span className="iv2-flip-badge">↷ flip from R{rd.r-1}</span>
                    )}
                  </div>
                  <div className="iv2-round-text">{rd.text}</div>
                  {rd.r < 3 && <div className="iv2-round-connector" />}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { InterviewV2 });
