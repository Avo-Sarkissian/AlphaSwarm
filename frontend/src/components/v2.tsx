// v2 components — Signal Wire (CSS scroll), Data Sources (full takeover),
// Advisory V2, Model Status, plus the ReportModalV2 rich-section helpers
// (ConvergenceFlow, InfluenceChart, Moment, Followup, AdvStat, AdvHoldingRow).
//
// Ported from AlphaSwarm-2/src/v2.jsx (801 LOC) per D-03 (CDN-globals → ES
// modules) and renamed .jsx → .tsx per codex HIGH-1 — body uses generic
// usePolling<T>, typed AdvisoryV2 props, optional `as` casts.
//
// Wiring map (Plan 41.6-03):
//   • SignalWire / DataSourcesTakeover — DEV-only dynamic mock import per
//     codex HIGH-2 / KR-41.6-14 (top-level static import would survive
//     tree-shaking and fail the production grep gate). Production renders
//     the "unavailable in production build" placeholder.
//   • ModelStatus — wired to useTelemetry() + useConnection(); model name
//     hardcoded 'qwen3:8b' per KR-41.6-08 (matches src/alphaswarm/config.py:32
//     OllamaSettings.worker_model default).
//   • AdvisoryV2 — derive-or-stub per D-08; portfolio_outlook via renderMarkdown()
//     per D-09; 4 tabs per D-10; "HOLDINGS AFFECTED" relabel per D-22; strict
//     intersection citation count per gemini #G2 (closes KR-41.6-10);
//     GET-only polling (the manual brief trigger is forbidden) per codex HIGH-3
//     — synthesis is
//     auto-fired by backend on FINAL round per quick task 260507-19f.
//   • ReportModalV2 NOT exported — its rich layout folds into ./ReportModal.tsx
//     per D-20 (canonical-first, heading-gated subsections, codex HIGH-4).
import { useState, useEffect, useMemo, useRef } from 'react';
import { Icon } from './icons';
import { useTelemetry } from '../context/TelemetryContext';
import { useConnection } from '../context/ConnectionContext';
import { useAgents } from '../context/AgentsContext';
import { useCurrentCycle } from '../hooks/useCurrentCycle';
import { usePolling } from '../hooks/usePolling';
import { advisoryFetch, type AdvisoryContent } from '../api/advisory';
import { renderMarkdown } from '../lib/markdown';
import {
  parseOutlook,
  extractTickerSection,
  extractField,
  countAgentCitationsAgainst, // gemini #G2 — strict intersection (NOT bare countAgentCitations)
} from '../lib/advisoryParse';
// codex HIGH-2 / KR-41.6-14: NO top-level imports from '../mocks/*'.
// SignalWire and DataSourcesTakeover load mock seeds via DEV-only dynamic
// imports (see component bodies below). Production tree-shaking drops the
// mock chunks deterministically — verified by W3 task 4 production grep.

// ──────────────────────────────────────────────────────────────────────
// Types for the dynamically-loaded mock seed shapes (avoids any).
// ──────────────────────────────────────────────────────────────────────
interface SignalWireSeedItem {
  agent: string;
  source: string;
  query: string;
  result: string;
  used: boolean;
}

interface DataSourceShape {
  id: string;
  group: string;
  label: string;
  desc: string;
  rate: string;
  latency: number;
}

interface SourceStatShape {
  id: string;
  calls: number;
  cached: number;
  errors: number;
  lat_p50: number;
  lat_p95: number;
  bytes: string;
}

interface DataSourcesMock {
  DATA_SOURCES: ReadonlyArray<DataSourceShape>;
  SOURCE_GROUP_COLOR: Record<string, string>;
  SOURCE_STATS: ReadonlyArray<SourceStatShape>;
  SIGNAL_WIRE_SEED: ReadonlyArray<SignalWireSeedItem>;
}

// ──────────────────────────────────────────────────────────────────────
// SIGNAL WIRE — continuous CSS-scroll live wire
// codex HIGH-2 / KR-41.6-14: top-level static import of '../mocks/wire' would
// survive tree-shaking and fail the production grep gate. The DEV-only dynamic
// import below makes Vite drop the entire mocks chunk from production builds.
// ──────────────────────────────────────────────────────────────────────
export function SignalWire({ onInspect }: { onInspect?: () => void }) {
  const { running } = useTelemetry();
  const [mock, setMock] = useState<{
    seed: ReadonlyArray<SignalWireSeedItem>;
    sources: ReadonlyArray<DataSourceShape>;
    groupColor: Record<string, string>;
  } | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (import.meta.env.DEV) {
      void Promise.all([import('../mocks/wire'), import('../mocks/sources')]).then(
        ([w, s]) => {
          if (cancelled) return;
          setMock({
            seed: w.SIGNAL_WIRE_SEED,
            sources: s.DATA_SOURCES,
            groupColor: s.SOURCE_GROUP_COLOR,
          });
        },
      );
    }
    return () => {
      cancelled = true;
    };
  }, []);

  const items = useMemo(() => {
    if (!mock) return [] as SignalWireSeedItem[];
    return [...mock.seed, ...mock.seed, ...mock.seed];
  }, [mock]);

  const sourceById = useMemo(() => {
    if (!mock) return {} as Record<string, DataSourceShape>;
    return Object.fromEntries(mock.sources.map((s) => [s.id, s]));
  }, [mock]);

  if (mock === null) {
    // Production OR DEV-still-loading. Production should never advance past
    // this branch because the dynamic import never fires (KR-41.6-14).
    if (!import.meta.env.DEV) {
      return (
        <div className="signal-wire signal-wire-placeholder">
          <span className="label">WIRE · unavailable in production build (KR-41.6-14)</span>
        </div>
      );
    }
    return (
      <div className="signal-wire signal-wire-placeholder">
        <span className="label">WIRE · loading…</span>
      </div>
    );
  }

  return (
    <div className="signal-wire">
      <div className="sw-label">
        <span className="label" style={{ color: 'var(--accent)' }}>
          WIRE
        </span>
        {running && <span className="sw-live-dot" />}
      </div>

      <div className="sw-scroll-wrap">
        <div
          className="sw-scroll-inner"
          style={{ animationPlayState: running ? 'running' : 'paused' }}
        >
          {items.map((e, i) => {
            const src = sourceById[e.source];
            const color = mock.groupColor[src?.group ?? ''] || '#8a93a0';
            return (
              <div key={i} className="sw-event" data-unused={!e.used}>
                <span className="sw-agent">{e.agent}</span>
                <span className="sw-sep" style={{ color }}>
                  →
                </span>
                <span className="sw-src" style={{ color }}>
                  {src?.label || e.source}
                </span>
                <span className="sw-q">{e.query}</span>
                <span className="sw-r">{e.result}</span>
                {!e.used && (
                  <span className="sw-unused" title="fetched, not cited">
                    ○
                  </span>
                )}
                <span className="sw-divider">·</span>
              </div>
            );
          })}
        </div>
      </div>

      {onInspect && (
        <button className="sw-inspect" onClick={onInspect} title="Open Data Sources inspector">
          <Icon name="search" size={12} />
          <span>Sources</span>
        </button>
      )}
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// MODEL STATUS — topbar inline status chip
// KR-41.6-08: model name hardcoded 'qwen3:8b' (matches
// src/alphaswarm/config.py:32 OllamaSettings.worker_model — Phase 41.4
// locked qwen3:8b worker + qwen3.6:27b orchestrator).
// ──────────────────────────────────────────────────────────────────────
export function ModelStatus() {
  const tel = useTelemetry();
  const conn = useConnection();
  const running = conn.lastFrame !== null && tel.running;
  const phase = tel.phase;
  const tps = tel.telemetry.tps ?? 0;
  const slots = tel.telemetry.slotsUsed ?? 0;

  const ops = [
    `${phase === 'done' ? 'complete' : phase === 'idle' ? 'idle' : `round ${phase}/3`}`,
    `${slots} slots`,
    `${tps.toFixed(1)} t/s`,
  ];
  return (
    <div className="model-status" data-running={running}>
      <div className="ms-model">
        <span className="ms-dot" data-running={running} />
        <span className="mono ms-name">qwen3:8b</span>
      </div>
      <div className="ms-ops">
        {ops.map((o, i) => (
          <span key={i} className="ms-op">
            {o}
          </span>
        ))}
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// DATA SOURCES — full-screen takeover
// codex HIGH-2 / KR-41.6-14: same DEV-only dynamic import pattern as SignalWire.
// ──────────────────────────────────────────────────────────────────────
export function DataSourcesTakeover({ onClose }: { onClose: () => void }) {
  const [mockData, setMockData] = useState<DataSourcesMock | null>(null);
  useEffect(() => {
    let cancelled = false;
    if (import.meta.env.DEV) {
      void Promise.all([import('../mocks/sources'), import('../mocks/wire')]).then(
        ([s, w]) => {
          if (cancelled) return;
          setMockData({
            DATA_SOURCES: s.DATA_SOURCES,
            SOURCE_GROUP_COLOR: s.SOURCE_GROUP_COLOR,
            SOURCE_STATS: s.SOURCE_STATS,
            SIGNAL_WIRE_SEED: w.SIGNAL_WIRE_SEED,
          });
        },
      );
    }
    return () => {
      cancelled = true;
    };
  }, []);

  // Hooks must be called unconditionally — derive everything off mockData,
  // then bail with the placeholder render below.
  const statsById = useMemo(() => {
    if (!mockData) return {} as Record<string, SourceStatShape>;
    return Object.fromEntries(mockData.SOURCE_STATS.map((s) => [s.id, s]));
  }, [mockData]);
  const [selected, setSelected] = useState<string | null>(null);
  useEffect(() => {
    if (mockData && selected === null) {
      setSelected(mockData.DATA_SOURCES[0]?.id ?? null);
    }
  }, [mockData, selected]);
  const [groupFilter, setGroupFilter] = useState('all');

  if (mockData === null) {
    if (!import.meta.env.DEV) {
      return (
        <div className="ds-takeover">
          <div className="ds-head">
            <div className="ds-head-left">
              <button className="btn ghost-btn" onClick={onClose}>
                <Icon name="close" />
              </button>
              <div className="ds-head-title">Data Sources</div>
              <div className="label" style={{ color: 'var(--text-3)' }}>
                unavailable in production build (KR-41.6-14)
              </div>
            </div>
          </div>
        </div>
      );
    }
    return (
      <div className="ds-takeover">
        <div className="ds-head">
          <div className="ds-head-left">
            <button className="btn ghost-btn" onClick={onClose}>
              <Icon name="close" />
            </button>
            <div className="ds-head-title">Data Sources</div>
            <div className="label" style={{ color: 'var(--text-3)' }}>
              loading…
            </div>
          </div>
        </div>
      </div>
    );
  }

  const { DATA_SOURCES, SOURCE_GROUP_COLOR, SOURCE_STATS, SIGNAL_WIRE_SEED } = mockData;
  const sel = DATA_SOURCES.find((s) => s.id === selected);
  const stats = selected ? statsById[selected] : undefined;
  const recent = SIGNAL_WIRE_SEED.filter((e) => e.source === selected).slice(0, 8);

  const totalCalls = SOURCE_STATS.reduce((a, s) => a + s.calls, 0);
  const totalErrors = SOURCE_STATS.reduce((a, s) => a + s.errors, 0);
  const totalBytes = '82.1 MB';
  const cacheRatePct = totalCalls
    ? Math.round((SOURCE_STATS.reduce((a, s) => a + s.cached, 0) / totalCalls) * 100)
    : 0;

  const filtered =
    groupFilter === 'all'
      ? DATA_SOURCES
      : DATA_SOURCES.filter((s) => s.group === groupFilter);

  return (
    <div className="ds-takeover">
      <div className="ds-head">
        <div className="ds-head-left">
          <button className="btn ghost-btn" onClick={onClose}>
            <Icon name="close" />
          </button>
          <div className="ds-head-title">Data Sources</div>
          <div className="label" style={{ color: 'var(--text-3)' }}>
            API AUDIT · THIS CYCLE
          </div>
        </div>
        <div className="ds-head-stats">
          <DsStat label="TOTAL CALLS" value={totalCalls.toLocaleString()} />
          <DsStat
            label="ERRORS"
            value={String(totalErrors)}
            tone={totalErrors > 10 ? 'sell' : 'ok'}
          />
          <DsStat label="EGRESS" value={totalBytes} />
          <DsStat label="CACHE RATE" value={`${cacheRatePct}%`} />
        </div>
      </div>

      <div className="ds-body">
        {/* Left: source list */}
        <div className="ds-left">
          <div className="ds-group-tabs">
            {['all', 'market', 'macro', 'news', 'social', 'filings'].map((g) => (
              <button
                key={g}
                className="ds-gtab"
                data-active={groupFilter === g}
                onClick={() => setGroupFilter(g)}
              >
                {g === 'all' ? 'All' : g}
              </button>
            ))}
          </div>
          <div className="ds-source-list">
            {filtered.map((s) => {
              const st = statsById[s.id];
              const cacheRate = st && st.calls ? Math.round((st.cached / st.calls) * 100) : 0;
              const errRate = st && st.calls ? st.errors / st.calls : 0;
              const color = SOURCE_GROUP_COLOR[s.group];
              return (
                <button
                  key={s.id}
                  className="ds-source-row"
                  data-active={selected === s.id}
                  onClick={() => setSelected(s.id)}
                >
                  <div className="ds-src-top">
                    <div className="ds-src-name">
                      <span className="ds-src-dot" style={{ background: color }} />
                      <span>{s.label}</span>
                    </div>
                    <span
                      className={`ds-src-calls mono ${errRate > 0.02 ? 'err' : ''}`}
                    >
                      {st?.calls?.toLocaleString() ?? 0}
                    </span>
                  </div>
                  <div className="ds-src-bar">
                    <div
                      className="ds-src-bar-fill"
                      style={{ width: `${cacheRate}%`, background: color, opacity: 0.6 }}
                    />
                    {errRate > 0 && (
                      <div
                        className="ds-src-bar-err"
                        style={{ width: `${errRate * 100}%` }}
                      />
                    )}
                  </div>
                  <div className="ds-src-meta">
                    <span>{cacheRate}% cached</span>
                    {st && st.errors > 0 && (
                      <span className="ds-err-badge">{st.errors} err</span>
                    )}
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
                <span
                  className="ds-src-dot lg"
                  style={{ background: SOURCE_GROUP_COLOR[sel.group] }}
                />
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

            <div className="ds-stats-grid">
              <DsStatCard label="CALLS" value={stats.calls.toLocaleString()} />
              <DsStatCard
                label="CACHE HIT"
                value={`${Math.round((stats.cached / stats.calls) * 100)}%`}
                sub={`${stats.cached.toLocaleString()} of ${stats.calls.toLocaleString()}`}
                tone="buy"
              />
              <DsStatCard
                label="ERRORS"
                value={String(stats.errors)}
                tone={stats.errors > 5 ? 'sell' : stats.errors > 0 ? 'warn' : 'buy'}
              />
              <DsStatCard label="P50 LATENCY" value={`${stats.lat_p50}ms`} />
              <DsStatCard
                label="P95 LATENCY"
                value={`${stats.lat_p95}ms`}
                tone={stats.lat_p95 > 600 ? 'warn' : 'ok'}
              />
              <DsStatCard label="STATUS" value="ONLINE" tone="buy" />
            </div>

            <div className="ds-latency-viz">
              <div className="label" style={{ marginBottom: 10 }}>
                LATENCY DISTRIBUTION
              </div>
              <div className="ds-lat-bars">
                {[
                  { label: 'p10', val: Math.round(stats.lat_p50 * 0.6) },
                  { label: 'p25', val: Math.round(stats.lat_p50 * 0.8) },
                  { label: 'p50', val: stats.lat_p50 },
                  { label: 'p75', val: Math.round((stats.lat_p50 + stats.lat_p95) / 2) },
                  { label: 'p95', val: stats.lat_p95 },
                  { label: 'p99', val: Math.round(stats.lat_p95 * 1.4) },
                ].map(({ label, val }) => {
                  const maxVal = Math.round(stats.lat_p95 * 1.4);
                  const pct = maxVal ? (val / maxVal) * 100 : 0;
                  const color =
                    val > stats.lat_p95
                      ? 'var(--sell)'
                      : val > stats.lat_p50
                        ? 'var(--accent)'
                        : 'var(--buy)';
                  return (
                    <div key={label} className="ds-lat-col">
                      <div className="ds-lat-bar-wrap">
                        <div
                          className="ds-lat-bar"
                          style={{ height: `${pct}%`, background: color }}
                        />
                      </div>
                      <div className="ds-lat-val mono">{val}</div>
                      <div className="label">{label}</div>
                    </div>
                  );
                })}
              </div>
            </div>

            <div className="ds-recent-section">
              <div className="label" style={{ marginBottom: 10 }}>
                RECENT QUERIES · THIS CYCLE
              </div>
              {recent.length === 0 ? (
                <div className="ds-empty">
                  No queries recorded for this source this cycle.
                </div>
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
                      <span className="mono" style={{ color: 'var(--accent)' }}>
                        {r.agent}
                      </span>
                      <span className="mono ds-q-text">{r.query}</span>
                      <span className="mono ds-r-text">{r.result}</span>
                      <span className={`ds-cited-badge ${r.used ? 'yes' : 'no'}`}>
                        {r.used ? 'YES' : 'NO'}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="ds-privacy-note">
              <Icon name="lock" size={12} />
              <span>
                Inference is 100% local (Ollama). These calls are the only network egress
                this cycle. Keys stored in{' '}
                <span className="mono">~/.alphaswarm/keys.toml</span>
              </span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function DsStat({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: string;
}) {
  return (
    <div className="ds-head-stat" data-tone={tone}>
      <div className="label">{label}</div>
      <div className="ds-head-stat-v mono">{value}</div>
    </div>
  );
}

function DsStatCard({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: string;
}) {
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
// D-08 derive-or-stub. D-09 renderMarkdown for portfolio_outlook. D-10 4 tabs.
// D-22 design-label relabel → "HOLDINGS AFFECTED" using affected_holdings/total_holdings
// directly from backend. gemini #G2 strict-intersection citation count.
// codex HIGH-3: NO advisory POST trigger — backend auto-fires on FINAL round.
// ──────────────────────────────────────────────────────────────────────
interface AdvisoryItemPayload {
  ticker: string;
  consensus_signal: 'BUY' | 'SELL' | 'HOLD';
  confidence: number;
  rationale_summary: string;
  position_exposure: string | number;
}
interface AdvisoryReportPayload extends AdvisoryContent {
  items?: AdvisoryItemPayload[];
  portfolio_outlook?: string;
  total_holdings?: number;
  affected_holdings?: number;
}

interface HoldingAnalysis {
  ticker: string;
  swarmSignal: 'BUY' | 'SELL' | 'HOLD';
  recTone: 'buy' | 'sell' | 'hold';
  rec: string;
  rationale: string;
  value: number;
  weight: number;
  agents: number;
  shares: string | null;
  basis: string | null;
  last: string | null;
  sentiment: number;
  risk: string | null;
  upside: string | null;
}

export function AdvisoryV2({ onClose }: { onClose: () => void }) {
  const { cycleId } = useCurrentCycle();
  const { agents: liveAgents } = useAgents();
  const liveAgentIds = useMemo(
    () => new Set(liveAgents.map((a) => a.id)),
    [liveAgents],
  ); // gemini #G2 — used for strict citation intersection
  const [tab, setTab] = useState<'overview' | 'holdings' | 'risk' | 'isolation'>(
    'overview',
  );

  // codex HIGH-3: GET-only polling. No POST trigger — synthesis is
  // auto-fired by SimulationManager.on_complete (per quick task 260507-19f).
  // 404 → null (pending); 500 → polled.error (D-19 surfaces).
  const polled = usePolling<AdvisoryContent | null>({
    key: `advisory:${cycleId ?? 'none'}`,
    fetchFn: () => (cycleId ? advisoryFetch(cycleId) : Promise.resolve(null)),
    intervalMs: 3000,
    maxAttempts: 200,
  });
  const report = polled.data as AdvisoryReportPayload | null;
  const hadError = polled.error !== null;

  // D-08 derive-or-stub: build holdingAnalysis array
  const holdingAnalysis = useMemo<HoldingAnalysis[]>(() => {
    if (!report?.items) return [];
    const totalExposure = report.items.reduce(
      (sum, item) => sum + Number(item.position_exposure || 0),
      0,
    );
    const outlookMd = report.portfolio_outlook || '';
    return report.items.map((item) => {
      const value = Number(item.position_exposure || 0);
      const weight = totalExposure > 0 ? (value / totalExposure) * 100 : 0;
      const tickerSection = extractTickerSection(outlookMd, item.ticker);
      return {
        ticker: item.ticker,
        swarmSignal: item.consensus_signal,
        recTone: item.consensus_signal.toLowerCase() as 'buy' | 'sell' | 'hold',
        rec:
          (tickerSection && extractField(tickerSection, 'rec')) ||
          (item.consensus_signal === 'BUY'
            ? 'CONSIDER ADDING'
            : item.consensus_signal === 'SELL'
              ? 'CONSIDER TRIMMING'
              : 'NO ACTION'),
        rationale: item.rationale_summary,
        value,
        weight,
        // gemini #G2 — strict intersection (KR-41.6-10 closed for false positives)
        agents: countAgentCitationsAgainst(item.rationale_summary, liveAgentIds),
        // STUB per D-08 + KR-41.6-01:
        shares: null,
        basis: null,
        last: null,
        sentiment: 0,
        // PARSE per-ticker section (KR-41.6-12 if missing):
        risk: tickerSection ? extractField(tickerSection, 'risk') : null,
        upside: tickerSection ? extractField(tickerSection, 'upside') : null,
      };
    });
  }, [report, liveAgentIds]);

  const outlook = useMemo(
    () => parseOutlook(report?.portfolio_outlook ?? ''),
    [report],
  );
  const outlookHtml = useMemo(
    () => renderMarkdown(report?.portfolio_outlook ?? ''),
    [report],
  );

  const totalValue = holdingAnalysis.reduce((a, h) => a + h.value, 0);

  // Stat derivations for the Overview row
  const totalHoldings = report?.total_holdings ?? 0;
  const affectedHoldings = report?.affected_holdings ?? 0;
  // D-22 — display as `${affected}/${total}` directly from backend.
  const holdingsAffectedDisplay = `${affectedHoldings}/${totalHoldings}`;

  // CONFIDENCE: average across items, label HIGH (>0.7) / MED (>0.4) / LOW
  const avgConfidence = report?.items?.length
    ? report.items.reduce((a, i) => a + (i.confidence || 0), 0) / report.items.length
    : 0;
  const confidenceLabel =
    avgConfidence > 0.7 ? 'HIGH' : avgConfidence > 0.4 ? 'MED' : 'LOW';
  const confidenceTone: 'buy' | 'sell' | 'hold' =
    avgConfidence > 0.7 ? 'buy' : avgConfidence > 0.4 ? 'hold' : 'sell';

  // SWARM VIEW: dominant of items.consensus_signal counts
  const swarmCounts = useMemo(() => {
    const c = { BUY: 0, SELL: 0, HOLD: 0 };
    for (const item of report?.items ?? []) c[item.consensus_signal] += 1;
    return c;
  }, [report]);
  const swarmTotal = swarmCounts.BUY + swarmCounts.SELL + swarmCounts.HOLD;
  const swarmDominant: 'BUY' | 'SELL' | 'HOLD' =
    swarmCounts.SELL >= swarmCounts.BUY && swarmCounts.SELL >= swarmCounts.HOLD
      ? 'SELL'
      : swarmCounts.BUY >= swarmCounts.HOLD
        ? 'BUY'
        : 'HOLD';
  const swarmDominantPct = swarmTotal
    ? Math.round((swarmCounts[swarmDominant] / swarmTotal) * 100)
    : 0;
  const swarmTone: 'buy' | 'sell' | 'hold' =
    swarmDominant === 'BUY' ? 'buy' : swarmDominant === 'SELL' ? 'sell' : 'hold';

  return (
    <div className="adv-takeover">
      <div className="adv-head">
        <div className="adv-head-left">
          <button className="btn ghost-btn" onClick={onClose}>
            <Icon name="close" />
          </button>
          <div>
            <div className="adv-title">Personalized Advisory</div>
            <div className="label adv-subtitle">
              ORCHESTRATOR SYNTHESIS · SWARM CONSENSUS APPLIED TO YOUR PORTFOLIO
            </div>
          </div>
          <div className="adv-isolation-badge">
            <Icon name="lock" size={11} />
            <span>Holdings never seen by swarm agents</span>
          </div>
        </div>
        <div className="adv-head-right">
          <div className="adv-tabs">
            {(['overview', 'holdings', 'risk', 'isolation'] as const).map((t) => (
              <button
                key={t}
                className="adv-tab"
                data-active={tab === t}
                onClick={() => setTab(t)}
              >
                {t.charAt(0).toUpperCase() + t.slice(1)}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="adv-body">
        {!cycleId && (
          <div className="advisory-card">
            <div className="label">No completed cycle to advise on.</div>
          </div>
        )}
        {cycleId && polled.loading && !report && !hadError && (
          <div className="advisory-card">
            <div className="label">Loading advisory…</div>
          </div>
        )}
        {hadError && !report && (
          <div className="advisory-card" style={{ color: 'var(--sell)' }}>
            Advisory unavailable: {polled.error?.message ?? 'unknown error'}
          </div>
        )}
        {cycleId && !polled.loading && !report && !hadError && (
          <div className="advisory-card">
            <div className="label">
              No advisory yet for this cycle (auto-triggered on cycle complete).
            </div>
          </div>
        )}

        {report && tab === 'overview' && (
          <div className="adv-overview">
            {/* Primary rec — D-09 renderMarkdown for portfolio_outlook */}
            <div className="adv-primary-rec">
              <div className="adv-rec-tag">PRIMARY RECOMMENDATION</div>
              <div className="adv-rec-headline">
                {outlook.headline ?? 'Portfolio Outlook'}
              </div>
              <div
                className="adv-rec-body"
                dangerouslySetInnerHTML={{ __html: outlookHtml }}
              />
            </div>

            {/* Summary stats — D-22 HOLDINGS AFFECTED relabel */}
            <div className="adv-summary-stats">
              <AdvStat
                label="PORTFOLIO"
                value={`$${(totalValue / 1000).toFixed(0)}K`}
                sub={`${totalHoldings} holdings`}
              />
              <AdvStat
                label="HOLDINGS AFFECTED"
                value={holdingsAffectedDisplay}
                sub="of portfolio"
              />
              <AdvStat
                label="SWARM VIEW"
                value={`${swarmDominant} ${swarmDominantPct}%`}
                sub="dominant signal"
                tone={swarmTone}
              />
              <AdvStat
                label="CONFIDENCE"
                value={confidenceLabel}
                sub={`avg ${(avgConfidence * 100).toFixed(0)}%`}
                tone={confidenceTone}
              />
            </div>

            {/* Quick holding view — D-10 single source */}
            <div className="adv-quick-holdings">
              <div className="label" style={{ marginBottom: 12 }}>
                SWARM VIEW ON YOUR HOLDINGS
              </div>
              {holdingAnalysis.map((h) => (
                <AdvHoldingRow key={h.ticker} h={h} totalValue={totalValue} />
              ))}
            </div>
          </div>
        )}

        {report && tab === 'holdings' && (
          <div className="adv-holdings-detail">
            {holdingAnalysis.map((h) => (
              <div key={h.ticker} className="adv-holding-card">
                <div className="adv-hc-head">
                  <div className="adv-hc-ticker">{h.ticker}</div>
                  <div className="adv-hc-value">
                    {/* STUB per D-08 + KR-41.6-01 — last/shares not on backend */}
                    <div className="adv-hc-val mono">{h.last ?? '—'}</div>
                    <div className="label">
                      {h.shares ?? '—'} sh · ${(h.value / 1000).toFixed(0)}K ·{' '}
                      {h.weight.toFixed(1)}%
                    </div>
                  </div>
                  <div className={`adv-hc-rec adv-rec-${h.recTone}`}>{h.rec}</div>
                  <div className="adv-hc-agents label">{h.agents} agents cited</div>
                </div>
                {/* Sentiment bar — STUBBED 0 per KR-41.6-01; bar centers on the midline */}
                <div className="adv-hc-sentiment">
                  <div className="adv-sentiment-bar">
                    <div
                      className="adv-sent-fill"
                      style={{
                        width: '0%',
                        background: 'var(--text-3)',
                        marginLeft: '50%',
                      }}
                    />
                    <div className="adv-sent-center" />
                  </div>
                  <div className="adv-sent-label">
                    <span>BEARISH</span>
                    <span className="mono" style={{ color: 'var(--text-3)' }}>
                      —
                    </span>
                    <span>BULLISH</span>
                  </div>
                </div>
                <div className="adv-hc-body">{h.rationale}</div>
                <div className="adv-hc-footer">
                  <div>
                    <span className="label">RISK</span>{' '}
                    <span className="adv-risk-text">{h.risk ?? '—'}</span>
                  </div>
                  <div>
                    <span className="label">UPSIDE</span>{' '}
                    <span className="adv-up-text">{h.upside ?? '—'}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {report && tab === 'risk' && (
          <div className="adv-risk-view">
            <div className="adv-risk-matrix" style={{ padding: 24 }}>
              <div className="label" style={{ marginBottom: 16 }}>
                RISK / OPPORTUNITY MATRIX · SEED-SPECIFIC
              </div>
              <div
                className="advisory-card"
                style={{
                  padding: 24,
                  color: 'var(--text-2)',
                  fontSize: 13,
                  lineHeight: 1.6,
                }}
              >
                Risk modeling lands in a future phase. Backend currently has no
                scenario or risk-matrix data source (KR-41.6-05).
              </div>
            </div>
          </div>
        )}

        {tab === 'isolation' && (
          <div className="adv-isolation">
            <div className="adv-iso-hero">
              <div className="adv-iso-arch">
                <div className="adv-iso-layer swarm">
                  <div className="adv-iso-layer-title">Swarm Layer</div>
                  <div className="adv-iso-layer-desc">
                    100 agents · 3 rounds · real market data
                  </div>
                  <div className="adv-iso-items">
                    <div className="adv-iso-item">✓ Sees: seed rumor</div>
                    <div className="adv-iso-item">
                      ✓ Sees: yfinance, FRED, news, filings
                    </div>
                    <div className="adv-iso-item adv-iso-no">
                      ✗ Never sees: your holdings
                    </div>
                    <div className="adv-iso-item adv-iso-no">
                      ✗ Never sees: your cost basis
                    </div>
                  </div>
                </div>
                <div className="adv-iso-arrow">↓ consensus only</div>
                <div className="adv-iso-layer orchestrator">
                  <div className="adv-iso-layer-title">Orchestrator Layer</div>
                  <div className="adv-iso-layer-desc">
                    Post-simulation synthesis only
                  </div>
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
                <p>
                  If agents knew your holdings, they would be susceptible to
                  position-confirmation bias — reasoning toward outcomes that benefit
                  your portfolio rather than the most accurate market analysis. The
                  isolation wall between the two layers prevents this.
                </p>
                <p>
                  The orchestrator reads only the consensus output — signals,
                  rationales, influence graph — never the raw agent prompts. Your
                  portfolio data is read once, locally, and never persisted to any
                  database or log.
                </p>
                <div className="adv-iso-audit">
                  <Icon name="doc" size={13} />
                  <span>
                    Full audit log available at{' '}
                    <span className="mono">~/.alphaswarm/advisory-audit.jsonl</span>
                  </span>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export function AdvStat({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: 'buy' | 'sell' | 'hold';
}) {
  return (
    <div className="adv-stat" data-tone={tone}>
      <div className="label">{label}</div>
      <div className="adv-stat-v">{value}</div>
      {sub && <div className="adv-stat-sub">{sub}</div>}
    </div>
  );
}

export function AdvHoldingRow({
  h,
  totalValue,
}: {
  h: HoldingAnalysis;
  totalValue: number;
}) {
  // Sentiment STUBBED (KR-41.6-01) — render midline bar.
  return (
    <div className="adv-qh-row">
      <div className="adv-qh-ticker">{h.ticker}</div>
      <div className="adv-qh-shares mono">{h.shares ?? '—'} sh</div>
      <div className="adv-qh-val mono">${(h.value / 1000).toFixed(0)}K</div>
      <div className="adv-qh-weight mono">
        {totalValue > 0 ? ((h.value / totalValue) * 100).toFixed(1) : '0.0'}%
      </div>
      <div className="adv-qh-sent-bar">
        <div className="adv-qs-neg" style={{ width: '0%' }} />
        <div className="adv-qs-mid" />
        <div className="adv-qs-pos" style={{ width: '0%' }} />
      </div>
      <div className={`adv-qh-signal mono sig-${h.swarmSignal.toLowerCase()}`}>
        {h.swarmSignal}
      </div>
      <div className={`adv-qh-rec adv-rec-${h.recTone}`}>{h.rec}</div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// ReportModalV2 rich-section helpers (folded into ./ReportModal.tsx per D-20).
// These render only when the corresponding parser returns non-null/non-empty
// data (heading-gated per codex HIGH-4).
// ──────────────────────────────────────────────────────────────────────
import type {
  ConvergenceData,
  InfluenceEntry,
  MomentEntry,
  FollowupEntry,
} from '../lib/advisoryParse';

export function ConvergenceFlow({ data }: { data: ConvergenceData[] }) {
  // Group rows by round — sum weights per signal per round so the same data
  // shape used by the parser also drives the bar segments.
  const byRound = useMemo(() => {
    const m = new Map<number, { buy: number; sell: number; hold: number }>();
    for (const row of data) {
      const cur = m.get(row.round) ?? { buy: 0, sell: 0, hold: 0 };
      const w = row.weight * 100; // parser returns 0..1
      if (row.signal === 'BUY') cur.buy += w;
      else if (row.signal === 'SELL') cur.sell += w;
      else if (row.signal === 'HOLD') cur.hold += w;
      m.set(row.round, cur);
    }
    return Array.from(m.entries())
      .sort((a, b) => a[0] - b[0])
      .map(([r, v]) => ({ r: `R${r}`, ...v }));
  }, [data]);

  // Use a ref so React's useMemo dep-tracker on `data` is honored without
  // shadowing the data prop usage below.
  const ignoredRef = useRef(byRound);
  ignoredRef.current = byRound;

  return (
    <div className="cv-flow">
      {byRound.map((rd) => (
        <div key={rd.r} className="cv-col">
          <div className="cv-bar">
            <div className="cv-seg buy" style={{ height: `${rd.buy}%` }}>
              <span className="cv-n">{Math.round(rd.buy)}</span>
            </div>
            <div className="cv-seg hold" style={{ height: `${rd.hold}%` }}>
              <span className="cv-n">{Math.round(rd.hold)}</span>
            </div>
            <div className="cv-seg sell" style={{ height: `${rd.sell}%` }}>
              <span className="cv-n">{Math.round(rd.sell)}</span>
            </div>
          </div>
          <div className="cv-r label">{rd.r}</div>
        </div>
      ))}
      <div className="cv-legend">
        <div>
          <span className="cv-dot buy" /> BUY
        </div>
        <div>
          <span className="cv-dot hold" /> HOLD
        </div>
        <div>
          <span className="cv-dot sell" /> SELL
        </div>
      </div>
    </div>
  );
}

export function InfluenceChart({ data }: { data: InfluenceEntry[] }) {
  const max = data.reduce((m, r) => Math.max(m, r.weight), 0) || 1;
  return (
    <div className="infl-chart">
      {data.map((r) => (
        <div key={r.agentId} className="infl-row">
          <span className="infl-id mono">{r.agentId}</span>
          <span className="infl-bracket label">—</span>
          <div className="infl-bar-wrap">
            <div className="infl-bar" style={{ width: `${(r.weight / max) * 100}%` }} />
          </div>
          <span className="infl-n mono">{r.weight.toFixed(2)}</span>
        </div>
      ))}
    </div>
  );
}

export function Moment({ moments }: { moments: MomentEntry[] }) {
  return (
    <div className="rv2-moments">
      {moments.map((m, i) => (
        <div key={i} className="rv2-moment">
          <div className="rv2-moment-t mono">R{m.round}</div>
          <div>
            <div className="rv2-moment-title">Round {m.round}</div>
            <div className="rv2-moment-body">{m.description}</div>
          </div>
        </div>
      ))}
    </div>
  );
}

export function Followup({ items }: { items: FollowupEntry[] }) {
  return (
    <div className="rv2-followups">
      {items.map((f, i) => (
        <div key={i} className="rv2-followup">
          <div className="rv2-followup-n">{String(i + 1).padStart(2, '0')}</div>
          <div>
            <div className="rv2-followup-title">{f.description}</div>
          </div>
        </div>
      ))}
    </div>
  );
}
