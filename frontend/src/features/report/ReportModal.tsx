// src/components/ReportModal.tsx
// Report modal wired to POST/GET /api/report/{cycle_id}. Canonical markdown
// renders first; charts come from the backend's structured sections and
// markdown is never parsed.
//
// Trigger semantics: POST /api/report/{cycle_id}/generate starts the report job
// (202 on accept, 409 report_generation_in_progress when one already runs). The
// modal polls GET only while the backend answers 409 report_generation_in_progress;
// every other error ends the poll and its envelope message is shown.
import { useState, useMemo, useEffect } from 'react';
import { Icon } from '../../components/Icon';
import { useFrameMeta } from '../../context/FrameMetaContext';
import { useLatestCompletedCycle } from '../../hooks/useLatestCompletedCycle';
import { defaultCycleId } from '../../lib/defaultCycle';
import { usePolling } from '../../hooks/usePolling';
import { reportFetch, reportGenerate, reportPoll, type ReportContent } from '../../api/report';
import { ApiError } from '../../api/client';
import { errorMessage, parseErrorEnvelope } from '../../lib/apiError';
import { shouldKeepPolling } from '../../lib/reportPolling';
import { renderMarkdown } from '../../lib/markdown';
import { ConvergenceFlow, InfluenceChart } from './ReportCharts';

// Local extension over ReportContent — the backend always sets `cycle_id`,
// `content`, `generated_at`; we additionally tolerate a `report_markdown`
// alias if the wire field name shifts.
type ReportPayload = ReportContent & { report_markdown?: string };

function isReportRunning(e: unknown): boolean {
  return (
    e instanceof ApiError &&
    shouldKeepPolling({ status: e.status, code: parseErrorEnvelope(e.body).code })
  );
}

export function ReportModal({
  cycleId: cycleIdProp,
  onClose,
}: {
  /** Explicit cycle to report on (e.g. picked in CycleBrowser). Defaults to defaultCycleId(). */
  cycleId?: string | null;
  onClose: () => void;
}) {
  const meta = useFrameMeta();
  const { cycleId: latestCompleted, loading: latestLoading } = useLatestCompletedCycle();
  const cycleId = cycleIdProp ?? defaultCycleId(meta, latestCompleted);
  // No cycle yet only means "none completed" once the lookup has answered.
  const findingCycle = cycleId === null && latestLoading;

  // UX contract: the modal NEVER auto-kicks generation. On open, GET the report:
  //   - 200 -> show it
  //   - 404 -> render an explicit "no report yet" state with a Generate button
  //   - 409 report_generation_in_progress -> a job already runs: start polling
  //   - anything else -> surface the backend's message
  // Only after the user clicks Generate do we POST /api/report/{cycleId}/generate,
  // and only once the POST is accepted do we start polling. (Previously the modal
  // POSTed on mount, silently spawning a 25-50 min synthesis that the user did
  // not request.)
  const [triggerError, setTriggerError] = useState<string | null>(null);
  const [generationKicked, setGenerationKicked] = useState(false);
  const [triggerPending, setTriggerPending] = useState(false);

  // ── Probe phase: one-shot fetch on mount, never via usePolling ─────────
  // reportFetch returns null on 404 (no report yet). usePolling would
  // misinterpret a 1-attempt cap as "polling timed out" — drop polling for
  // the probe and use a plain useEffect instead.
  const [probeState, setProbeState] = useState<{
    loading: boolean;
    data: ReportPayload | null;
    error: Error | null;
  }>({ loading: true, data: null, error: null });

  useEffect(() => {
    if (!cycleId) {
      setProbeState({ loading: false, data: null, error: null });
      return;
    }
    let cancelled = false;
    setProbeState({ loading: true, data: null, error: null });
    reportFetch(cycleId)
      .then((data) => {
        if (!cancelled) setProbeState({ loading: false, data, error: null });
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        if (isReportRunning(e)) {
          // A report job for this cycle is already running (auto-report or another tab).
          setGenerationKicked(true);
          setProbeState({ loading: false, data: null, error: null });
          return;
        }
        setProbeState({
          loading: false,
          data: null,
          error: e instanceof Error ? e : new Error(String(e)),
        });
      });
    return () => {
      cancelled = true;
    };
  }, [cycleId]);

  // ── Generation-phase polling (active once a report job is known to be running)
  const polled = usePolling<ReportPayload | null>({
    key: `report-gen:${cycleId ?? 'none'}:${generationKicked ? 'on' : 'off'}`,
    fetchFn: () =>
      cycleId && generationKicked ? reportPoll(cycleId) : Promise.resolve(null),
    intervalMs: 3000,
    maxAttempts: generationKicked ? 1200 : 0, // 0 = disabled until kicked
  });

  // Effective report = probe data (if found on open) OR polled data (post-kick).
  const report = probeState.data ?? polled.data;
  const isMissing = !probeState.loading && probeState.data === null && !generationKicked;
  const probeError = probeState.error;
  const fetchError = generationKicked ? polled.error : null;
  const hadError =
    triggerError !== null ||
    probeError !== null ||
    fetchError !== null;

  // Poll only after the POST is accepted, so a fast GET can never see 404.
  const handleGenerate = () => {
    if (!cycleId || generationKicked || triggerPending) return;
    setTriggerError(null);
    setTriggerPending(true);
    reportGenerate(cycleId)
      .then(() => setGenerationKicked(true))
      .catch((e: unknown) => {
        if (isReportRunning(e)) {
          setGenerationKicked(true);
          return;
        }
        setTriggerError(errorMessage(e));
      })
      .finally(() => setTriggerPending(false));
  };

  // Canonical markdown — pick whichever field the backend emitted.
  const canonicalMd = report?.content ?? report?.report_markdown ?? '';
  const canonicalHtml = useMemo(() => renderMarkdown(canonicalMd), [canonicalMd]);

  // Structured sections from the backend; null for legacy reports. The
  // markdown already contains the narrative, so only the charts are added.
  const sections = report?.sections ?? null;

  return (
    <>
      <div className="modal-head rpt-head">
        <div className="rpt-head-left">
          <Icon name="doc" size={14} />
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
              letterSpacing: '0.12em',
              textTransform: 'uppercase',
              color: 'var(--text-2)',
            }}
          >
            REPORT · {cycleId ?? 'no cycle'}
          </span>
        </div>
        <div className="rpt-head-right">
          <button className="btn ghost" onClick={onClose}>
            <Icon name="close" /> Close
          </button>
        </div>
      </div>

      <div className="modal-body no-pad report rpt-scroll">
        {findingCycle && (
          <div className="report-hero" style={{ padding: 24 }}>
            <div className="label">Finding the latest completed cycle…</div>
          </div>
        )}
        {!cycleId && !findingCycle && (
          <div className="report-hero" style={{ padding: 24 }}>
            <div className="label">No completed cycle to report on.</div>
          </div>
        )}
        {/* Initial probe in flight (one shot) before we know if a report exists. */}
        {cycleId && !generationKicked && probeState.loading && !report && !hadError && (
          <div className="report-hero" style={{ padding: 24 }}>
            <div className="label">Checking for existing report…</div>
          </div>
        )}
        {/* No report yet — explicit empty state with Generate button. */}
        {cycleId && isMissing && !report && !generationKicked && (
          <div className="report-hero" style={{ padding: 24, display: 'flex', flexDirection: 'column', gap: 14, alignItems: 'flex-start' }}>
            <div style={{ color: 'var(--text)', fontSize: 14, fontWeight: 600 }}>
              No report exists for this cycle yet.
            </div>
            <div style={{ color: 'var(--text-2)', fontSize: 13, lineHeight: 1.6, maxWidth: 640 }}>
              Reports generate automatically after every completed run (after the
              advisory when holdings are loaded).
              If auto-generation has not started yet — or you want a fresh pass —
              use the manual button below as a fallback / regenerate path.
              Generation is one orchestrator call after the model loads. Leave this
              modal open and the report appears here when ready.
            </div>
            <button
              className="btn"
              onClick={handleGenerate}
              disabled={triggerPending}
              style={{ marginTop: 4 }}
            >
              <Icon name="bolt" size={12} /> Generate report
            </button>
          </div>
        )}
        {/* Generation in flight (user clicked the button). */}
        {cycleId && generationKicked && polled.loading && !report && !hadError && (
          <div className="report-hero" style={{ padding: 24 }}>
            <div className="label" style={{ marginBottom: 8 }}>
              Generating report…
            </div>
            <div style={{ color: 'var(--text-2)', fontSize: 13, lineHeight: 1.6 }}>
              Collecting the simulation data and writing the narrative (one
              orchestrator call). The modal refreshes automatically when ready.
            </div>
          </div>
        )}
        {hadError && !report && (
          <div className="report-hero" style={{ padding: 24, color: 'var(--sell)' }}>
            Report failed:{' '}
            {probeError ? errorMessage(probeError) : fetchError ? errorMessage(fetchError) : triggerError ?? 'unknown error'}
          </div>
        )}

        {report && (
          <>
            {/* Hero — minimal, derived from backend metadata only: the
                live cycle id + generated_at, no design filler text. */}
            <div className="rpt-hero" style={{ padding: 24 }}>
              <div className="rpt-kicker label">
                CYCLE {report.cycle_id}
                {report.generated_at && ` · ${report.generated_at}`}
              </div>
            </div>

            {/* Canonical markdown body: always renders first */}
            {canonicalHtml && (
              <div
                className="report-markdown report-canonical"
                style={{ padding: 24 }}
                dangerouslySetInnerHTML={{ __html: canonicalHtml }}
              />
            )}

            {sections && sections.convergence.length > 0 && (
              <section className="rpt-section" data-testid="report-convergence-chart">
                <div className="rpt-section-head">
                  <h2>Convergence</h2>
                  <div className="label">ROUND-BY-ROUND SIGNAL DISTRIBUTION</div>
                </div>
                <ConvergenceFlow rows={sections.convergence} />
              </section>
            )}

            {sections && sections.influence.length > 0 && (
              <section className="rpt-section" data-testid="report-influence-chart">
                <div className="rpt-section-head">
                  <h2>Influence topology</h2>
                  <div className="label">MOST-CITED AGENTS · FINAL ROUND</div>
                </div>
                <InfluenceChart rows={sections.influence} />
              </section>
            )}
          </>
        )}
      </div>
    </>
  );
}
