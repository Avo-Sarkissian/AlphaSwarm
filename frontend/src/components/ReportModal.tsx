// src/components/ReportModal.tsx
// Real-wired Report modal — Phase 41.2 D-04 wiring (POST/GET /api/report/{cycle_id})
// + Phase 41.6 D-20: lifted rich layout from AlphaSwarm-2 ReportModalV2.
//
// codex HIGH-4 policy: canonical markdown FIRST; rich subsections heading-gated;
//   missing sections OMITTED (not '—' placeholders). KR-41.6-12 documents this
//   policy. Charts (ConvergenceFlow, InfluenceChart) require structured data —
//   never infer from loose prose.
// gemini #G1: section parsers from lib/advisoryParse.ts, NOT inline.
//
// Trigger semantics: POST /api/report/{cycle_id}/generate triggers the report
// generator (202 on accept, 409 when another generation is in flight). GET
// returns the report (404 → null/pending; 500/503 propagate). The trigger fires
// once on mount; 409 is treated as "already in flight" (poll picks it up).
import { useState, useMemo, useEffect } from 'react';
import { Icon } from './icons';
import { useCurrentCycle } from '../hooks/useCurrentCycle';
import { usePolling } from '../hooks/usePolling';
import { reportFetch, reportGenerate, type ReportContent } from '../api/report';
import { ApiError } from '../api/client';
import { renderMarkdown } from '../lib/markdown';
import {
  parseConvergence,
  parseMoments,
  parseInfluences,
  parseDissent,
  parseFollowups,
} from '../lib/advisoryParse';
import { ConvergenceFlow, InfluenceChart, Moment, Followup } from './v2';

// Local extension over ReportContent — the backend always sets `cycle_id`,
// `content`, `generated_at`; we additionally tolerate a `report_markdown`
// alias if the wire field name shifts.
type ReportPayload = ReportContent & { report_markdown?: string };

export function ReportModal({ onClose }: { onClose: () => void }) {
  const { cycleId } = useCurrentCycle();

  // Trigger ONCE on mount when cycleId present; handle 409 "already in flight"
  // by skipping (poll picks up the in-progress synthesis). Other errors surface.
  const [triggerError, setTriggerError] = useState<string | null>(null);
  const [kicked, setKicked] = useState(false);
  useEffect(() => {
    if (!cycleId || kicked) return;
    setKicked(true);
    let cancelled = false;
    void reportGenerate(cycleId).catch((e: unknown) => {
      if (cancelled) return;
      if (e instanceof ApiError && e.status === 409) return; // already in flight — OK
      const msg = e instanceof Error ? e.message : String(e);
      setTriggerError(msg);
    });
    return () => {
      cancelled = true;
    };
  }, [cycleId, kicked]);

  const polled = usePolling<ReportPayload | null>({
    key: `report:${cycleId ?? 'none'}`,
    fetchFn: () => (cycleId ? reportFetch(cycleId) : Promise.resolve(null)),
    intervalMs: 3000,
    maxAttempts: 200,
  });
  const report = polled.data;
  const hadError = polled.error !== null || triggerError !== null;

  // Canonical markdown — pick whichever field the backend emitted.
  const canonicalMd = report?.content ?? report?.report_markdown ?? '';
  const canonicalHtml = useMemo(() => renderMarkdown(canonicalMd), [canonicalMd]);

  // Heading-gated subsection parses (codex HIGH-4): each returns null when its
  // heading is absent. Render ONLY when non-null.
  const convergence = useMemo(() => parseConvergence(canonicalMd), [canonicalMd]);
  const moments = useMemo(() => parseMoments(canonicalMd), [canonicalMd]);
  const dissent = useMemo(() => parseDissent(canonicalMd), [canonicalMd]);
  const influences = useMemo(() => parseInfluences(canonicalMd), [canonicalMd]);
  const followups = useMemo(() => parseFollowups(canonicalMd), [canonicalMd]);

  const dissentHtml = useMemo(
    () => (dissent ? renderMarkdown(dissent) : ''),
    [dissent],
  );

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal modal-big report-v2" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head rv2-head">
          <div className="rv2-head-left">
            <Icon name="doc" size={14} />
            <span
              style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 11,
                letterSpacing: '0.12em',
                textTransform: 'uppercase',
                color: 'var(--text-2)',
              }}
            >
              REPORT · {cycleId ?? 'no cycle'}
            </span>
          </div>
          <div className="rv2-head-right">
            <button className="btn ghost" onClick={onClose}>
              <Icon name="close" /> Close
            </button>
          </div>
        </div>

        <div className="modal-body no-pad report rv2-scroll">
          {!cycleId && (
            <div className="report-hero" style={{ padding: 24 }}>
              <div className="label">No completed cycle to report on.</div>
            </div>
          )}
          {cycleId && polled.loading && !report && !hadError && (
            <div className="report-hero" style={{ padding: 24 }}>
              <div className="label">Generating report…</div>
            </div>
          )}
          {hadError && !report && (
            <div className="report-hero" style={{ padding: 24, color: 'var(--sell)' }}>
              Report failed: {polled.error?.message ?? triggerError ?? 'unknown error'}
            </div>
          )}

          {report && (
            <>
              {/* Hero — minimal, derived from backend metadata only. The
                  AlphaSwarm-2 design's hero filler text is not preserved per
                  Pitfall #3; this hero shows the live cycle id + generated_at. */}
              <div className="rv2-hero" style={{ padding: 24 }}>
                <div className="rv2-kicker label">
                  CYCLE {report.cycle_id}
                  {report.generated_at && ` · ${report.generated_at}`}
                </div>
              </div>

              {/* Canonical markdown body — D-20 codex HIGH-4: ALWAYS renders FIRST */}
              {canonicalHtml && (
                <div
                  className="report-markdown report-canonical"
                  style={{ padding: 24 }}
                  dangerouslySetInnerHTML={{ __html: canonicalHtml }}
                />
              )}

              {/* Heading-gated rich subsections (KR-41.6-12).
                  OMITTED entirely when the matching ## H2 heading is absent. */}
              {convergence && (
                <section className="rv2-section">
                  <div className="rv2-section-head">
                    <h2>Convergence</h2>
                    <div className="label">ROUND-BY-ROUND SIGNAL DISTRIBUTION</div>
                  </div>
                  <ConvergenceFlow data={convergence} />
                </section>
              )}

              {moments && (
                <section className="rv2-section">
                  <div className="rv2-section-head">
                    <h2>Key moments</h2>
                  </div>
                  <Moment moments={moments} />
                </section>
              )}

              {dissent && (
                <section className="rv2-section">
                  <div className="rv2-section-head">
                    <h2>Dissent</h2>
                  </div>
                  <div
                    className="report-dissent"
                    dangerouslySetInnerHTML={{ __html: dissentHtml }}
                  />
                </section>
              )}

              {influences && (
                <section className="rv2-section">
                  <div className="rv2-section-head">
                    <h2>Influence topology</h2>
                    <div className="label">PERSISTED TO NEO4J</div>
                  </div>
                  <InfluenceChart data={influences} />
                </section>
              )}

              {followups && (
                <section className="rv2-section">
                  <div className="rv2-section-head">
                    <h2>Recommended follow-ups</h2>
                  </div>
                  <Followup items={followups} />
                </section>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
