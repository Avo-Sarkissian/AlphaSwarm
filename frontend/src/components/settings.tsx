// Settings — full-screen takeover.
//
// Ported from AlphaSwarm-2/src/settings.jsx per D-03; .jsx → .tsx per codex HIGH-1.
//
// D-23 persistence policy:
//   • Nothing in Settings is stored in the browser: the UI tweaks had no effect
//     and were removed (docs/DECISIONS.md#p41-6-d-23).
//   • Backend-owned values never touch localStorage. Read-only rows show the
//     backend's live value or say where the value is configured (KR-41.6-06).
//   • Privacy copy, the version and the live slot counts come from the backend
//     (GET /api/settings, GET /api/health, the WebSocket frame), never from
//     constants (docs/DECISIONS.md#adr-local-first-inference).
//   • Paths and addresses the backend reads from its environment, which this
//     page cannot see, show their default and name the variable that changes it.
import { useEffect, useId, useState } from 'react';
import { getHealth } from '../api/settings';
import { useTelemetry } from '../context/TelemetryContext';
import { usePrivacyFacts } from '../hooks/usePrivacyFacts';
import {
  MARKET_DATA_LINE,
  cloudRolesSummary,
  modeLabel,
  privacyLines,
  privacyMode,
} from '../lib/privacyCopy';
import type { TelemetrySlice } from '../types';
import { InferenceSettings } from './settings_inference';

// Until the memory governor first reports, the frame carries an idle placeholder
// with 0 slots (docs/DECISIONS.md#p999-3-d-01). Nothing reports in cloud mode,
// where the rate limiter replaces the governor, so 0 is not a real allowance.
function slotsValue(telemetry: TelemetrySlice): string {
  if (telemetry.governorState === null || telemetry.governorState === 'idle') {
    return 'not reported yet (the memory governor reports during a local run)';
  }
  return `${telemetry.slotsUsed} in use / ${telemetry.slotsMax} allowed now`;
}

export function Settings({ onClose }: { onClose: () => void }) {
  const [section, setSection] = useState<
    'runtime' | 'model' | 'brackets' | 'keys' | 'storage' | 'privacy'
  >('runtime');
  const [privacy, setPrivacyFromSettings] = usePrivacyFacts();
  const { telemetry } = useTelemetry();
  const [version, setVersion] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getHealth()
      .then((health) => {
        if (!cancelled && typeof health.version === 'string') setVersion(health.version);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  const sections = [
    { k: 'runtime' as const, label: 'Runtime' },
    { k: 'model' as const, label: 'Model' },
    { k: 'brackets' as const, label: 'Brackets' },
    { k: 'keys' as const, label: 'API keys' },
    { k: 'storage' as const, label: 'Storage' },
    { k: 'privacy' as const, label: 'Privacy' },
  ];

  return (
    <div className="st-takeover">
      <div className="st-head">
        <div className="st-head-left">
          <span className="label" style={{ color: 'var(--text-3)' }}>
            CONFIGURATION
          </span>
          <span className="st-title">Settings</span>
        </div>
        <div className="st-head-right">
          <button className="btn ghost" onClick={onClose}>
            Close
          </button>
        </div>
      </div>

      <div className="st-body">
        <div className="st-nav">
          {sections.map((x) => (
            <button
              key={x.k}
              className="st-nav-btn"
              data-active={section === x.k}
              onClick={() => setSection(x.k)}
            >
              {x.label}
            </button>
          ))}
          <div className="st-nav-foot">
            <div className="label">{version ? `ALPHASWARM ${version}` : 'ALPHASWARM'}</div>
            <div
              className="mono"
              style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 4 }}
            >
              {modeLabel(privacyMode(privacy))}
            </div>
          </div>
        </div>

        <div className="st-content">
          {section === 'runtime' && (
            <>
              {/* Backend-touching: memory threshold — read-only, KR-41.6-06 */}
              <BackendRow
                label="Memory ceiling"
                value="90 %"
                desc="Inference pauses when RAM usage crosses this threshold. Configured in src/alphaswarm/config.py — Coming in v6.x as a runtime setting."
              />
              {/* Live from the memory governor (governor_metrics in every frame) */}
              <LiveRow
                label="Concurrent inference slots"
                value={slotsValue(telemetry)}
                desc="Live from the memory governor; the allowance shrinks under memory pressure."
              />
              {/* Backend-touching: agent count — read-only, KR-41.6-06 */}
              <BackendRow
                label="Agent population"
                value="100"
                desc="Total number of personas per cycle. Configured at backend startup — Coming in v6.x."
              />
            </>
          )}

          {section === 'model' && (
            <SettingGroup
              title="Inference / Models"
              desc="Provider, model, and API key for orchestrator and worker roles. Changes take effect on the next simulation run. Settings are backend-owned — never stored in localStorage."
            >
              <InferenceSettings onSaved={setPrivacyFromSettings} />
            </SettingGroup>
          )}

          {section === 'brackets' && (
            <SettingGroup
              title="Bracket composition"
              desc="Distribution of personas across the 10 brackets. Configured at backend startup."
            >
              <BackendRow
                label="Bracket weights"
                value="locked at backend startup"
                desc="Coming in v6.x as a runtime setting."
              />
            </SettingGroup>
          )}

          {section === 'keys' && (
            <SettingGroup
              title="API keys"
              desc="Cloud API keys are entered in Settings → Model and stored in the inference config file, an owner-only file (mode 0600) that the API never returns. yfinance prices and RSS headlines need no keys."
            >
              <DefaultRow
                label="Key file"
                value=".secrets/inference.json"
                envVar="ALPHASWARM_INFERENCE_CONFIG_PATH"
              />
              <LiveRow label="Roles using a cloud API" value={cloudRolesSummary(privacy)} />
            </SettingGroup>
          )}

          {section === 'storage' && (
            <SettingGroup
              title="Storage"
              desc="Cycles, decisions and influence edges are stored in Neo4j; reports and advisories are written as owner-only files, and only the newest advisories are kept (ALPHASWARM_ADVISORY_KEEP_LAST, default 20). The values below are the defaults: the backend reads overrides from its environment (.env), which this page cannot see."
            >
              <DefaultRow
                label="Graph database"
                value="bolt://localhost:7687"
                envVar="ALPHASWARM_NEO4J__URI"
              />
              <DefaultRow
                label="Reports"
                value="reports/{cycle_id}_report.md"
                envVar="ALPHASWARM_REPORTS_DIR"
              />
              <DefaultRow
                label="Advisories"
                value="advisory/{cycle_id}_advisory.json"
                envVar="ALPHASWARM_ADVISORY_DIR"
              />
            </SettingGroup>
          )}

          {section === 'privacy' && (
            <SettingGroup
              title="Where your data goes"
              desc="Generated from your current inference settings (Settings → Model)."
            >
              <div className="st-privacy">
                {privacyLines(privacy).map((line) => (
                  <PrivacyRow key={line.text} text={line.text} offMachine={line.offMachine} />
                ))}
                <PrivacyRow text={MARKET_DATA_LINE} offMachine />
                <PrivacyRow
                  text="No telemetry: AlphaSwarm makes no outbound calls for analytics or crash reporting."
                  offMachine={false}
                />
              </div>
            </SettingGroup>
          )}
        </div>
      </div>
    </div>
  );
}

function SettingGroup({
  title,
  desc,
  children,
}: {
  title: string;
  desc?: string;
  children: React.ReactNode;
}) {
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

function PrivacyRow({ text, offMachine }: { text: string; offMachine: boolean }) {
  return (
    <div className={`st-privacy-row ${offMachine ? 'off' : 'yes'}`}>
      <span className="st-check">{offMachine ? '↗' : '✓'}</span>
      <div className="st-privacy-desc">{text}</div>
    </div>
  );
}

const ROW_STYLE = {
  display: 'flex',
  alignItems: 'center',
  gap: 12,
  padding: '10px 0',
  borderBottom: '1px solid var(--border)',
} as const;

const VALUE_STYLE = {
  flex: 1,
  padding: '6px 10px',
  background: 'var(--bg-3)',
  border: '1px solid var(--border)',
  color: 'var(--text-3)',
  fontFamily: 'var(--font-mono)',
  fontSize: 11,
  borderRadius: 3,
} as const;

// Read-only row showing a real backend value (no "coming soon" badge).
function LiveRow({ label, value, desc }: { label: string; value: string; desc?: string }) {
  return (
    <div className="settings-row" style={ROW_STYLE} title={desc}>
      <label style={{ minWidth: 220, color: 'var(--text-2)', fontSize: 12 }}>{label}</label>
      <input type="text" value={value} disabled readOnly style={VALUE_STYLE} />
    </div>
  );
}

// Read-only row for a value the backend reads from its environment: the default,
// plus the variable that overrides it.
function DefaultRow({ label, value, envVar }: { label: string; value: string; envVar: string }) {
  const id = useId();
  return (
    <label htmlFor={id} className="settings-row" style={ROW_STYLE}>
      <span style={{ minWidth: 220, color: 'var(--text-2)', fontSize: 12 }}>{label}</span>
      <input
        id={id}
        aria-label={label}
        type="text"
        value={value}
        disabled
        readOnly
        style={VALUE_STYLE}
      />
      <span className="settings-note mono" style={{ whiteSpace: 'nowrap' }}>
        default · {envVar}
      </span>
    </label>
  );
}

// Read-only row for backend-touching settings — KR-41.6-06.
function BackendRow({
  label,
  value,
  desc,
}: {
  label: string;
  value: string;
  desc?: string;
}) {
  return (
    <div className="settings-row settings-row-locked" style={ROW_STYLE}>
      <label style={{ minWidth: 220, color: 'var(--text-2)', fontSize: 12 }}>
        {label}
      </label>
      <input type="text" value={value} disabled readOnly style={VALUE_STYLE} />
      <span
        className="settings-note"
        style={{
          fontSize: 10,
          color: 'var(--accent)',
          padding: '2px 6px',
          border: '1px solid var(--accent)',
          borderRadius: 3,
          letterSpacing: '0.04em',
        }}
        title={desc}
      >
        Coming in v6.x
      </span>
    </div>
  );
}
