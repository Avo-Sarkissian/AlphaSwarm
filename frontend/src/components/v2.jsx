// v2 components — Signal Wire ticker + Data Sources inspector modal.
// Per plan: SignalWire and DataSourcesModal are EXCEPTIONS to the "no mocks
// on the live render path" rule — they are scaffolding UIs that will continue
// to be stubbed from mocks/wire.ts + mocks/sources.ts until a dedicated
// feed lands in a later phase. The tree-shaking still excludes holdings.ts.
import { useState, useEffect, useRef, useMemo } from 'react';
import { Icon } from './icons';
import { SIGNAL_WIRE_SEED, DATA_SOURCES, SOURCE_GROUP_COLOR, SOURCE_STATS } from '../mocks';

// ──────────────────────────────────────────────────────────────────────
// SIGNAL WIRE — live ticker strip of agent → API activity
// ──────────────────────────────────────────────────────────────────────
export function SignalWire({ running, onInspect }) {
  const sourceById = useMemo(
    () => Object.fromEntries(DATA_SOURCES.map(s => [s.id, s])),
    []
  );

  // Rolling buffer of events; newest appended to the right.
  const [events, setEvents] = useState(() =>
    SIGNAL_WIRE_SEED.slice(0, 10).map((e, i) => ({ ...e, key: `seed-${i}`, age: i * 0.6 }))
  );
  const tickIx = useRef(10);

  useEffect(() => {
    if (!running) return;
    const iv = setInterval(() => {
      setEvents(prev => {
        const next = SIGNAL_WIRE_SEED[tickIx.current % SIGNAL_WIRE_SEED.length];
        tickIx.current++;
        const entry = { ...next, key: `t-${tickIx.current}`, age: 0 };
        const bumped = prev.map(e => ({ ...e, age: e.age + 1 })).filter(e => e.age < 12);
        return [...bumped, entry];
      });
    }, 1400);
    return () => clearInterval(iv);
  }, [running]);

  return (
    <div className="signal-wire">
      <div className="sw-label">
        <span className="label" style={{color: 'var(--accent)'}}>SIGNAL WIRE</span>
        <span className="sw-rate">{events.length} recent · 5Hz</span>
      </div>
      <div className="sw-track">
        {events.map((e) => {
          const src = sourceById[e.source];
          const color = SOURCE_GROUP_COLOR[src?.group] || '#8a93a0';
          return (
            <div
              key={e.key}
              className="sw-tick"
              data-fresh={e.age < 1}
              data-unused={!e.used}
              title={`${e.agent} → ${src?.label} · ${e.query}`}
            >
              <span className="sw-agent">{e.agent}</span>
              <span className="sw-arrow" style={{color}}>→</span>
              <span className="sw-source" style={{color}}>{src?.label || e.source}</span>
              <span className="sw-query">{e.query}</span>
              <span className="sw-result">{e.result}</span>
              {!e.used && <span className="sw-unused-dot" title="fetched but not cited" />}
            </div>
          );
        })}
      </div>
      <button className="sw-inspect" onClick={onInspect} title="Inspect all data sources">
        <Icon name="search" />
        <span>Sources</span>
      </button>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// DATA SOURCES INSPECTOR MODAL
// ──────────────────────────────────────────────────────────────────────
export function DataSourcesModal({ onClose }) {
  const statsById = useMemo(
    () => Object.fromEntries(SOURCE_STATS.map(s => [s.id, s])),
    []
  );
  const [selected, setSelected] = useState(DATA_SOURCES[0].id);
  const sel = DATA_SOURCES.find(s => s.id === selected);
  const stats = statsById[selected];

  // Recent queries for the selected source
  const recent = useMemo(
    () => SIGNAL_WIRE_SEED.filter(e => e.source === selected).slice(0, 8),
    [selected]
  );

  // Group sources for the left list
  const grouped = useMemo(() => {
    const g = {};
    for (const s of DATA_SOURCES) (g[s.group] = g[s.group] || []).push(s);
    return g;
  }, []);

  // Totals header
  const totals = useMemo(() => {
    const sum = SOURCE_STATS.reduce(
      (a, s) => ({ calls: a.calls + s.calls, cached: a.cached + s.cached, errors: a.errors + s.errors }),
      { calls: 0, cached: 0, errors: 0 }
    );
    return sum;
  }, []);

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal ds-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div>
            <div className="modal-title">Data Sources</div>
            <div className="modal-sub">
              Live API access audit · {totals.calls.toLocaleString()} calls ·
              &nbsp;{Math.round((totals.cached / totals.calls) * 100)}% cached · {totals.errors} errors
            </div>
          </div>
          <button className="modal-close" onClick={onClose}><Icon name="close" /></button>
        </div>

        <div className="ds-body">
          {/* Left: grouped source list */}
          <div className="ds-list">
            {Object.entries(grouped).map(([group, sources]) => (
              <div key={group} className="ds-group">
                <div className="ds-group-head">
                  <span className="ds-group-dot" style={{background: SOURCE_GROUP_COLOR[group]}} />
                  <span className="label">{group}</span>
                </div>
                {sources.map(s => {
                  const st = statsById[s.id];
                  return (
                    <button
                      key={s.id}
                      className="ds-row"
                      data-active={selected === s.id}
                      onClick={() => setSelected(s.id)}
                    >
                      <span className="ds-row-label">{s.label}</span>
                      <span className="ds-row-calls num">{st?.calls ?? 0}</span>
                    </button>
                  );
                })}
              </div>
            ))}
          </div>

          {/* Right: detail pane */}
          <div className="ds-detail">
            <div className="ds-detail-head">
              <div>
                <div className="ds-detail-title">
                  <span className="ds-group-dot" style={{background: SOURCE_GROUP_COLOR[sel.group]}} />
                  {sel.label}
                </div>
                <div className="ds-detail-desc">{sel.desc}</div>
              </div>
              <div className="ds-detail-meta">
                <div><span className="label">RATE LIMIT</span><div className="mono">{sel.rate}</div></div>
                <div><span className="label">BASELINE LATENCY</span><div className="mono">{sel.latency}ms</div></div>
              </div>
            </div>

            {/* Stats grid */}
            <div className="ds-stats">
              <StatCell label="CALLS" value={stats.calls.toLocaleString()} />
              <StatCell label="CACHE HITS" value={`${Math.round((stats.cached/stats.calls)*100)}%`} sub={`${stats.cached.toLocaleString()} of ${stats.calls.toLocaleString()}`} />
              <StatCell label="ERRORS" value={stats.errors} tone={stats.errors > 5 ? 'sell' : stats.errors > 0 ? 'hold' : 'buy'} />
              <StatCell label="P50 / P95" value={`${stats.lat_p50} / ${stats.lat_p95}`} sub="ms" />
              <StatCell label="EGRESS" value={stats.bytes} />
              <StatCell label="STATUS" value="OK" tone="buy" />
            </div>

            {/* Recent queries */}
            <div className="ds-section-title"><span className="label">RECENT QUERIES</span></div>
            <div className="ds-recent">
              {recent.length === 0 && <div className="ds-empty">No queries this cycle.</div>}
              {recent.map((r, i) => (
                <div key={i} className="ds-recent-row">
                  <span className="mono ds-agent">{r.agent}</span>
                  <span className="ds-query mono">{r.query}</span>
                  <span className="ds-result mono">{r.result}</span>
                  <span className={`ds-used ${r.used ? 'yes' : 'no'}`}>{r.used ? 'CITED' : 'UNUSED'}</span>
                </div>
              ))}
            </div>

            <div className="ds-footnote">
              <Icon name="lock" />
              <span>Inference is local (Ollama). Data calls leave your machine — credentials in <span className="mono">~/.alphaswarm/keys.toml</span>.</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function StatCell({ label, value, sub, tone }) {
  return (
    <div className="stat-cell" data-tone={tone || 'default'}>
      <span className="label">{label}</span>
      <div className="stat-value mono">{value}</div>
      {sub && <div className="stat-sub mono">{sub}</div>}
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// REPORT V2 — editorial treatment with data visualizations
// ──────────────────────────────────────────────────────────────────────
export function ReportModalV2({ onClose }) {
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
      {rounds.map((rd) => (
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
