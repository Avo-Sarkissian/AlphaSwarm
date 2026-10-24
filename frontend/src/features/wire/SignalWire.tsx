// Signal Wire: scrolling ticker of the live data-source audit.
import { useMemo } from 'react';
import { Icon } from '../../components/Icon';
import { useTelemetry } from '../../context/TelemetryContext';
import { useDataSourceAudit } from '../../hooks/useDataSourceAudit';
import { SOURCE_COLOR, SOURCE_LABEL, extractSubject, interleaveBySource, stripSubject } from './wireFormat';

// One ticker item: a provider call with its subject in the agent slot.
interface WireItem {
  agent: string;
  source: string;
  query: string;
  result: string;
  used: boolean;
}

// Continuous CSS-scroll ticker over the live provider-call
// audit (useDataSourceAudit, the frame's data_source_audit slice). There is
// no mock fallback: before the first call it says so (docs/DECISIONS.md#kr-41-1-02).
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
        <span className="label u-accent">
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
