// v2 components — Signal Wire (CSS scroll), Data Sources (full takeover),
// Advisory V2, Model Status, plus the ReportModalV2 rich-section helpers
// (ConvergenceFlow, InfluenceChart, Moment, Followup, AdvStat, AdvHoldingRow).
//
// Ported from AlphaSwarm-2/src/v2.jsx (801 LOC) per D-03 (CDN-globals → ES
// modules) and renamed .jsx → .tsx per codex HIGH-1 — body uses generic
// usePolling<T>, typed AdvisoryV2 props, optional `as` casts.
//
// Wiring map (Plan 41.6-03):
//   • SignalWire / DataSourcesTakeover — the live data_source_audit slice
//     only; there are no mocks (docs/DECISIONS.md#kr-41-1-02).
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
import { useState, useMemo, useRef } from 'react';
import { getHealth } from '../api/settings';
import { Icon } from './icons';
import { useTelemetry } from '../context/TelemetryContext';
import { useConnection } from '../context/ConnectionContext';
import { useAgents } from '../context/AgentsContext';
import { useFrameMeta } from '../context/FrameMetaContext';
import { useLatestCompletedCycle } from '../hooks/useLatestCompletedCycle';
import { useRounds } from '../hooks/useRounds';
import { defaultCycleId } from '../lib/defaultCycle';
import { usePolling } from '../hooks/usePolling';
import { useDataSourceAudit } from '../hooks/useDataSourceAudit';
import { usePrivacyFacts } from '../hooks/usePrivacyFacts';
import { advisoryLine, dataSourcesNote } from '../lib/privacyCopy';
import { advisoryFetch, type AdvisoryContent } from '../api/advisory';
import { renderMarkdown } from '../lib/markdown';
import { AdvisoryDisclaimer } from '../features/advisory/AdvisoryDisclaimer';
import {
  parseOutlook,
  extractTickerSection,
  extractField,
  countAgentCitationsAgainst, // gemini #G2 — strict intersection (NOT bare countAgentCitations)
} from '../lib/advisoryParse';
import { recentFor, summarizeAudit } from '../lib/dataSources';

// One ticker item: a provider call with its subject in the agent slot.
interface WireItem {
  agent: string;
  source: string;
  query: string;
  result: string;
  used: boolean;
}

// Labels and colors for the providers that exist (alphaswarm.ingestion).
const SOURCE_LABEL: Record<string, string> = { yfinance: 'YAHOO', rss: 'RSS' };
const SOURCE_COLOR: Record<string, string> = { yfinance: '#f5a524', rss: '#5be7b8' };

// Pull the subject of a provider call out of the audit `query` string so
// the ticker shows e.g. AAPL / MSFT / NVDA in the agent slot instead of
// repeating the source name. Mirrors the two query shapes in
// alphaswarm/ingestion/{yfinance,rss}_provider.py:
//   "AAPL OHLCV"     → "AAPL"
//   "headlines:AAPL" → "AAPL"
function extractSubject(query: string, source: string): string {
  const after = query.includes(':') ? query.slice(query.indexOf(':') + 1) : query;
  const head = after.trim().split(/\s+/)[0] ?? '';
  return head ? head.toUpperCase() : (SOURCE_LABEL[source] ?? source.toUpperCase());
}

// Drop the subject token from the query so the post-arrow `sw-q` slot
// doesn't echo what's already in the agent slot. "AAPL OHLCV" → "OHLCV";
// "headlines:AAPL" → "headlines".
function stripSubject(query: string): string {
  if (query.includes(':')) return query.slice(0, query.indexOf(':'));
  const parts = query.trim().split(/\s+/);
  return parts.length > 1 ? parts.slice(1).join(' ') : query;
}

// Round-robin entries across distinct sources so consecutive ticker items
// alternate yfinance / rss / fred / … instead of all-yfinance-then-all-rss
// (which made news-heavy seeds read as a wall of green RSS). Recency
// within a source is preserved — only the cross-source ORDERING changes.
// Insertion order of the Map drives the round-robin order, so the source
// that appeared first in the chronological audit anchors the rotation.
function interleaveBySource<T extends { source: string }>(entries: T[]): T[] {
  const groups = new Map<string, T[]>();
  for (const e of entries) {
    const arr = groups.get(e.source);
    if (arr) arr.push(e);
    else groups.set(e.source, [e]);
  }
  const queues = Array.from(groups.values());
  const result: T[] = [];
  let added = true;
  while (added) {
    added = false;
    for (const q of queues) {
      const next = q.shift();
      if (next !== undefined) {
        result.push(next);
        added = true;
      }
    }
  }
  return result;
}

// ──────────────────────────────────────────────────────────────────────
// SIGNAL WIRE — continuous CSS-scroll ticker over the live provider-call
// audit (useDataSourceAudit, the frame's data_source_audit slice). There is
// no mock fallback: before the first call it says so (docs/DECISIONS.md#kr-41-1-02).
// ──────────────────────────────────────────────────────────────────────
export function SignalWire({ onInspect }: { onInspect?: () => void }) {
  const { running } = useTelemetry();
  const liveAudit = useDataSourceAudit();
  // The audit has no requesting-agent field, so the call subject (ticker or
  // entity) fills the agent slot. Duplicated (not triplicated) so the CSS
  // keyframe translateX(0 → -50%) lands on a copy boundary and loops seamlessly.
  const items = useMemo<WireItem[]>(() => {
    const mapped = liveAudit.map((e) => ({
      agent: extractSubject(e.query, e.source),
      source: e.source,
      query: stripSubject(e.query),
      result: e.result,
      used: e.used,
    }));
    const interleaved = interleaveBySource(mapped);
    return [...interleaved, ...interleaved];
  }, [liveAudit]);

  if (liveAudit.length === 0) {
    return (
      <div className="signal-wire signal-wire-placeholder">
        <span className="label">WIRE · waiting for the first provider call…</span>
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
        <div className="sw-scroll-inner">
          {items.map((e, i) => {
            const color = SOURCE_COLOR[e.source] ?? 'var(--accent)';
            return (
              <div key={i} className="sw-event" data-unused={!e.used}>
                <span className="sw-agent">{e.agent}</span>
                <span className="sw-sep" style={{ color }}>
                  →
                </span>
                <span className="sw-src" style={{ color }}>
                  {SOURCE_LABEL[e.source] ?? e.source}
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
// Now live: polls GET /api/health at 10s intervals for inference_mode and
// spent_usd. Until health answers it says "Checking…", and "Mode unknown" when
// the request fails, never a guessed "Local". inference_mode looks at providers
// only, so an Ollama cloud model still reads as Local here while Settings, which
// applies the advisory's off-machine rule, says local + cloud.
// ──────────────────────────────────────────────────────────────────────
export function ModelStatus() {
  const tel = useTelemetry();
  const conn = useConnection();
  const running = conn.lastFrame !== null && tel.running;
  const phase = tel.phase;
  const tps = tel.telemetry.tps ?? 0;
  const slots = tel.telemetry.slotsUsed ?? 0;
  // Round and depth come from the frame (roundNum, num_rounds), never from the phase string.
  const roundNum = conn.lastFrame?.roundNum ?? null;
  const { numRounds } = useRounds();

  // Live inference mode from /api/health — poll every 10 s.
  const { data: healthData, error: healthError } = usePolling({
    key: 'health-inference-mode',
    fetchFn: getHealth,
    intervalMs: 10_000,
  });
  const inferenceMode = healthData?.inference_mode ?? null;
  const spentUsd = healthData?.spent_usd ?? null;

  // Derive a human-readable mode label from the inference_mode field.
  function modeLabel(mode: 'local' | 'cloud' | 'mixed' | null): string {
    if (mode === 'local') return 'Local';
    if (mode === 'cloud') return 'Cloud';
    if (mode === 'mixed') return 'Mixed';
    return healthError !== null ? 'Mode unknown' : 'Checking…';
  }

  const ops = [
    `${
      phase === 'complete'
        ? 'complete'
        : phase === 'idle'
          ? 'idle'
          : roundNum != null && roundNum >= 1
            ? `round ${roundNum}/${numRounds}`
            : phase // 'seeding' / pre-round frames have no round yet
    }`,
    `${slots} slots`,
    `${tps.toFixed(1)} t/s`,
  ];

  const modeParts = [modeLabel(inferenceMode)];
  if (spentUsd !== null && spentUsd > 0) {
    modeParts.push(`$${spentUsd.toFixed(2)}`);
  }

  return (
    <div className="model-status" data-running={running}>
      <div className="ms-model">
        <span className="ms-dot" data-running={running} />
        <span className="mono ms-name">{modeParts.join(' · ')}</span>
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
// DATA SOURCES — full-screen takeover summarizing the live provider-call
// audit per source, with that source's recent calls (docs/DECISIONS.md#kr-41-1-02).
// ──────────────────────────────────────────────────────────────────────
export function DataSourcesTakeover({ onClose }: { onClose: () => void }) {
  const audit = useDataSourceAudit();
  const summaries = useMemo(() => summarizeAudit(audit), [audit]);
  const [selected, setSelected] = useState<string | null>(null);
  const active = selected ?? summaries[0]?.source ?? null;
  const recent = useMemo(() => (active ? recentFor(audit, active) : []), [audit, active]);
  const totals = useMemo(
    () =>
      summaries.reduce(
        (t, s) => ({ calls: t.calls + s.calls, errors: t.errors + s.errors, cached: t.cached + s.cached, cited: t.cited + s.cited }),
        { calls: 0, errors: 0, cached: 0, cited: 0 },
      ),
    [summaries],
  );

  return (
    <div className="ds-takeover">
      <div className="ds-head">
        <div className="ds-head-left">
          <button className="btn ghost-btn" onClick={onClose} aria-label="Close data sources">
            <Icon name="close" />
          </button>
          <div className="ds-head-title">Data Sources</div>
          <div className="label" style={{ color: 'var(--text-3)' }}>
            LAST {audit.length} PROVIDER CALLS
          </div>
        </div>
        <div className="ds-head-stats">
          <DsStat label="CALLS" value={String(totals.calls)} />
          <DsStat label="ERRORS" value={String(totals.errors)} tone={totals.errors > 0 ? 'sell' : 'ok'} />
          <DsStat label="CACHED" value={String(totals.cached)} />
          <DsStat label="FED TO AGENTS" value={String(totals.cited)} />
        </div>
      </div>

      <div className="ds-body">
        {summaries.length === 0 ? (
          <div className="ds-empty">
            No provider calls yet. Market prices and headlines are fetched while the swarm is seeding.
          </div>
        ) : (
          <>
            <div className="ds-left">
              <div className="ds-source-list">
                {summaries.map((s) => (
                  <button
                    key={s.source}
                    className="ds-source-row"
                    data-active={active === s.source}
                    onClick={() => setSelected(s.source)}
                  >
                    <div className="ds-src-top">
                      <div className="ds-src-name">
                        <span className="ds-src-dot" style={{ background: SOURCE_COLOR[s.source] ?? 'var(--accent)' }} />
                        <span>{SOURCE_LABEL[s.source] ?? s.source}</span>
                      </div>
                      <span className={`ds-src-calls mono ${s.errors > 0 ? 'err' : ''}`}>{s.calls}</span>
                    </div>
                    <div className="ds-src-meta">
                      <span>{s.cached} cached</span>
                      {s.errors > 0 && <span className="ds-err-badge">{s.errors} err</span>}
                      <span>{s.cited} fed to agents</span>
                    </div>
                  </button>
                ))}
              </div>
            </div>

            <div className="ds-detail-pane">
              <div className="label" style={{ marginBottom: 10 }}>
                RECENT CALLS · {active ? (SOURCE_LABEL[active] ?? active) : ''}
              </div>
              <div className="ds-recent-table">
                <div className="ds-recent-head">
                  <span className="label">TIME</span>
                  <span className="label">QUERY</span>
                  <span className="label">RESULT</span>
                  <span className="label">FED TO AGENTS</span>
                </div>
                {recent.map((r, i) => (
                  <div key={`${r.ts}-${i}`} className="ds-recent-row-v2">
                    <span className="mono">{new Date(r.ts * 1000).toLocaleTimeString()}</span>
                    <span className="mono ds-q-text">{r.query}</span>
                    <span className="mono ds-r-text">{r.result}</span>
                    <span className={`ds-cited-badge ${r.used ? 'yes' : 'no'}`}>{r.used ? 'YES' : 'NO'}</span>
                  </div>
                ))}
              </div>
            </div>
          </>
        )}
      </div>
      <DataSourcesPrivacyNote />
    </div>
  );
}

function DataSourcesPrivacyNote() {
  const [privacy] = usePrivacyFacts();
  return (
    <div className="ds-privacy-note">
      <Icon name="lock" size={12} />
      <span>{dataSourcesNote(privacy)}</span>
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
  const meta = useFrameMeta();
  const { numRounds } = useRounds();
  const { cycleId: latestCompleted, loading: latestLoading } = useLatestCompletedCycle();
  const cycleId = defaultCycleId(meta, latestCompleted);
  // No cycle yet only means "none completed" once the lookup has answered.
  const findingCycle = cycleId === null && latestLoading;
  const { agents: liveAgents } = useAgents();
  const liveAgentIds = useMemo(
    () => new Set(liveAgents.map((a) => a.id)),
    [liveAgents],
  ); // gemini #G2 — used for strict citation intersection
  const [tab, setTab] = useState<'overview' | 'holdings' | 'risk' | 'isolation'>(
    'overview',
  );
  const [privacy] = usePrivacyFacts();

  // codex HIGH-3: GET-only polling. No POST trigger — synthesis is
  // auto-fired by SimulationManager.on_complete (per quick task 260507-19f).
  // 404 → null (pending); 500 → polled.error (D-19 surfaces).
  // Cap = 1200 attempts × 3000ms = 60min. Realistic on M1 Max where
  // post-run narrative generation (~12-25min) + worker→orchestrator swap
  // (~30-90s) + advisory synthesis (~2-5min) can exceed the prior 10min cap.
  // See debug session ws-agent-states-not-emitted-mid-sim (symptom 2 UX).
  const polled = usePolling<AdvisoryContent | null>({
    key: `advisory:${cycleId ?? 'none'}`,
    enabled: cycleId !== null,
    fetchFn: () => (cycleId ? advisoryFetch(cycleId) : Promise.resolve(null)),
    intervalMs: 3000,
    maxAttempts: 1200,
    stopWhenData: true, // report is immutable once generated — stop the 3s loop
  });
  const report = polled.data as AdvisoryReportPayload | null;
  const hadError = polled.error !== null;
  // Cap hit: usePolling's timeout error has this exact message (docs/DECISIONS.md#p41-6-d-19).
  const isExhausted =
    polled.error !== null && /polling timed out/i.test(polled.error.message);

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

      <AdvisoryDisclaimer />

      <div className="adv-body">
        {findingCycle && (
          <div className="advisory-card">
            <div className="label">Finding the latest completed cycle…</div>
          </div>
        )}
        {!cycleId && !findingCycle && (
          <div className="advisory-card">
            <div className="label">No completed cycle to advise on.</div>
          </div>
        )}
        {cycleId && polled.loading && !report && !hadError && (
          <div className="advisory-card">
            <div className="label" style={{ marginBottom: 8 }}>
              Generating advisory…{polled.attempt > 0 ? ` (poll #${polled.attempt})` : ''}
            </div>
            <div style={{ color: 'var(--text-2)', fontSize: 13, lineHeight: 1.6 }}>
              The orchestrator is running post-run narrative generation, swapping
              from worker → orchestrator model, then synthesizing your portfolio
              advisory. Total wall-clock on M1 Max is ~25–50 min — leave this
              tab open and the report will appear here automatically when ready.
            </div>
          </div>
        )}
        {cycleId && isExhausted && !report && (
          <div className="advisory-card">
            <div className="label" style={{ marginBottom: 8 }}>
              Advisory not yet generated
            </div>
            <div style={{ color: 'var(--text-2)', fontSize: 13, lineHeight: 1.6 }}>
              Synthesis can take 25–50 min on M1 Max (post-run narrative + worker→orchestrator
              model swap + advisory pass). Check back later — backend auto-fires on cycle complete.
            </div>
          </div>
        )}
        {cycleId && hadError && !isExhausted && !report && (
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

        {report && tab === 'holdings' && holdingAnalysis.length === 0 && (
          <div className="advisory-card">
            <div className="label" style={{ marginBottom: 8 }}>
              No per-holding signals returned by the orchestrator.
            </div>
            <div className="adv-rec-body" style={{ color: 'var(--text-3)' }}>
              The advisory synthesis emitted an empty <code>items[]</code> array.
              After ITEM 6 of 260512-jqn, the prompt instructs the orchestrator
              to emit one entry per holding (HOLD@0.2-0.4 placeholder if no
              strong signal), so a re-trigger should populate this view.
            </div>
          </div>
        )}
        {report && tab === 'holdings' && holdingAnalysis.length > 0 && (
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
                    100 agents · {numRounds} rounds · real market data
                  </div>
                  <div className="adv-iso-items">
                    <div className="adv-iso-item">✓ Sees: seed rumor</div>
                    <div className="adv-iso-item">
                      ✓ Sees: yfinance prices and RSS headlines (Round 1)
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
                    <div className="adv-iso-item">✓ Reads: your held tickers, one entry per ticker</div>
                    <div className="adv-iso-item adv-iso-no">✗ Never sent: quantities or cost basis</div>
                    <div className="adv-iso-item">{advisoryLine(privacy)}</div>
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
                  holdings are read from your local CSV and never written to Neo4j,
                  the live stream or the logs; the advisory result, including the
                  cost-basis exposure, is saved under advisory/ as an owner-only file.
                </p>
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
