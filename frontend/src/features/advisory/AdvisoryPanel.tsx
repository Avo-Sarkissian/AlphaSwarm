// Advisory panel: full-screen portfolio analysis for the cycle on screen.
import { useState, useMemo } from 'react';
import { Icon } from '../../components/Icon';
import { useAgents } from '../../context/AgentsContext';
import { useFrameMeta } from '../../context/FrameMetaContext';
import { useLatestCompletedCycle } from '../../hooks/useLatestCompletedCycle';
import { useRounds } from '../../hooks/useRounds';
import { defaultCycleId } from '../../lib/defaultCycle';
import { usePolling } from '../../hooks/usePolling';
import { usePrivacyFacts } from '../../hooks/usePrivacyFacts';
import { advisoryLine } from '../../lib/privacyCopy';
import { advisoryFetch, type AdvisoryContent, type AdvisoryReportPayload } from '../../api/advisory';
import { renderMarkdown } from '../../lib/markdown';
import { AdvisoryDisclaimer } from './AdvisoryDisclaimer';
import { parseOutlook, countAgentCitationsAgainst } from '../../lib/advisoryParse';
import { isPlaceholder, overviewStats, recLabel } from '../../lib/advisoryView';
import { AdvHoldingRow, AdvStat, type HoldingAnalysis } from './AdvisoryParts';

// Derive what the backend supports and stub the rest (docs/DECISIONS.md#p41-6-d-08);
// portfolio_outlook through renderMarkdown (docs/DECISIONS.md#p41-6-d-09); four
// tabs (docs/DECISIONS.md#p41-6-d-10); "HOLDINGS AFFECTED" read from
// affected_holdings/total_holdings (docs/DECISIONS.md#p41-6-d-22); citation
// counts intersect with live agent ids. No advisory POST trigger: the backend
// fires the synthesis on the final round.

export function AdvisoryPanel({ onClose }: { onClose: () => void }) {
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
  ); // used for the strict citation intersection
  const [tab, setTab] = useState<'overview' | 'holdings' | 'risk' | 'isolation'>(
    'overview',
  );
  const [privacy] = usePrivacyFacts();

  // GET-only polling. No POST trigger — synthesis is auto-fired by
  // SimulationManager.on_complete.
  // 404 → null (pending); 500 → polled.error (docs/DECISIONS.md#p41-6-d-19).
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

  // Derive-or-stub (docs/DECISIONS.md#p41-6-d-08): build the holdingAnalysis array
  const holdingAnalysis = useMemo<HoldingAnalysis[]>(() => {
    if (!report?.items) return [];
    const totalExposure = report.items.reduce(
      (sum, item) => sum + Number(item.position_exposure || 0),
      0,
    );
    return report.items.map((item) => {
      const value = Number(item.position_exposure || 0);
      const weight = totalExposure > 0 ? (value / totalExposure) * 100 : 0;
      return {
        ticker: item.ticker,
        swarmSignal: item.consensus_signal,
        recTone: item.consensus_signal.toLowerCase() as 'buy' | 'sell' | 'hold',
        rec: recLabel(item.consensus_signal),
        rationale: item.rationale_summary,
        value,
        weight,
        // Strict intersection with live ids (docs/DECISIONS.md#kr-41-6-10)
        agents: countAgentCitationsAgainst(item.rationale_summary, liveAgentIds),
        // Stubbed (docs/DECISIONS.md#p41-6-d-08, docs/DECISIONS.md#kr-41-6-01):
        shares: null,
        basis: null,
        last: null,
        sentiment: 0,
        // Written per item by the orchestrator; null when it gave none.
        risk: item.risk ?? null,
        upside: item.upside ?? null,
        placeholder: isPlaceholder(item),
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
  // Display `${affected}/${total}` directly from the backend (docs/DECISIONS.md#p41-6-d-22).
  const holdingsAffectedDisplay = `${affectedHoldings}/${totalHoldings}`;

  // Backend stats over conviction items only: placeholders never skew them.
  const overview = useMemo(() => (report ? overviewStats(report) : null), [report]);
  const avgConfidence = overview?.avgConfidence ?? null;
  const confidenceLabel =
    avgConfidence === null
      ? '—'
      : avgConfidence > 0.7
        ? 'HIGH'
        : avgConfidence > 0.4
          ? 'MED'
          : 'LOW';
  const confidenceTone: 'buy' | 'sell' | 'hold' =
    avgConfidence !== null && avgConfidence > 0.7
      ? 'buy'
      : avgConfidence !== null && avgConfidence > 0.4
        ? 'hold'
        : 'sell';
  const swarmDominant = overview?.dominant ?? null;
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
            {/* Primary rec — renderMarkdown for portfolio_outlook (docs/DECISIONS.md#p41-6-d-09) */}
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

            {/* Summary stats — HOLDINGS AFFECTED (docs/DECISIONS.md#p41-6-d-22) */}
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
                value={swarmDominant ? `${swarmDominant} ${overview?.dominantPct ?? 0}%` : '—'}
                sub={`dominant of ${overview?.convictionCount ?? 0} conviction items`}
                tone={swarmTone}
              />
              <AdvStat
                label="CONFIDENCE"
                value={confidenceLabel}
                sub={
                  avgConfidence === null
                    ? 'no conviction items'
                    : `avg ${(avgConfidence * 100).toFixed(0)}%`
                }
                tone={confidenceTone}
              />
            </div>

            {/* Quick holding view — one source of items (docs/DECISIONS.md#p41-6-d-10) */}
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
              The prompt instructs the orchestrator
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
                  <div className="adv-hc-ticker">
                    {h.ticker}
                    {h.placeholder && (
                      <span
                        className="adv-placeholder-tag label"
                        title="No strong swarm view this cycle; shown as HOLD placeholder"
                      >
                        PLACEHOLDER
                      </span>
                    )}
                  </div>
                  <div className="adv-hc-value">
                    {/* Stubbed: last/shares are not on the backend (docs/DECISIONS.md#kr-41-6-01) */}
                    <div className="adv-hc-val mono">{h.last ?? '—'}</div>
                    <div className="label">
                      {h.shares ?? '—'} sh · ${(h.value / 1000).toFixed(0)}K ·{' '}
                      {h.weight.toFixed(1)}%
                    </div>
                  </div>
                  <div className={`adv-hc-rec adv-rec-${h.recTone}`}>{h.rec}</div>
                  <div className="adv-hc-agents label">{h.agents} agents cited</div>
                </div>
                {/* Sentiment bar — stubbed at 0 (docs/DECISIONS.md#kr-41-6-01); centred on the midline */}
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
                scenario or risk-matrix data source.
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
