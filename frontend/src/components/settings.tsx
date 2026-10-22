// Settings — full-screen takeover.
//
// Ported from AlphaSwarm-2/src/settings.jsx per D-03; .jsx → .tsx per codex HIGH-1.
//
// D-23 persistence policy:
//   • UI tweaks (density / layout / theme / hintVisibility) persist to
//     localStorage via normalizeSettingsUiState (codex MEDIUM-8).
//   • Backend-owned values never touch localStorage. Read-only rows show the
//     backend's live value or say where the value is configured (KR-41.6-06).
//   • Privacy copy, the version and the live slot counts come from the backend
//     (GET /api/settings, GET /api/health, the WebSocket frame), never from
//     constants (docs/DECISIONS.md#adr-local-first-inference).
import { useEffect, useState } from 'react';
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
import {
  normalizeSettingsUiState,
  type SettingsUiState,
} from '../lib/settingsState';
import { InferenceSettings } from './settings_inference';

const SETTINGS_KEY = 'as_settings_ui_v1';

export function Settings({ onClose }: { onClose: () => void }) {
  // Read + normalize on mount — defensive against stale storage that may carry
  // backend keys from a future code path that accidentally merged them in.
  const [uiState, setUiState] = useState<SettingsUiState>(() => {
    if (typeof window === 'undefined') return {};
    try {
      const raw = localStorage.getItem(SETTINGS_KEY);
      return normalizeSettingsUiState(raw ? JSON.parse(raw) : {});
    } catch {
      return {};
    }
  });
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

  // On change: normalize before write — defense-in-depth even if a future code
  // path accidentally tries to merge backend keys into uiState.
  function persist(patch: Partial<SettingsUiState>) {
    const next: SettingsUiState = { ...uiState, ...patch };
    const safe = normalizeSettingsUiState(next);
    setUiState(safe);
    try {
      localStorage.setItem(SETTINGS_KEY, JSON.stringify(safe));
    } catch {
      // storage quota / SecurityError — silently ignore (UI tweaks are non-essential)
    }
  }

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
              {/* UI tweak — density (persisted) */}
              <SettingGroup
                title="Display density"
                desc="Controls panel padding and font scale. Persists to localStorage."
              >
                <div className="st-seg">
                  {(['compact', 'cozy', 'spacious'] as const).map((d) => (
                    <button
                      key={d}
                      data-active={uiState.density === d}
                      onClick={() => persist({ density: d })}
                    >
                      {d}
                    </button>
                  ))}
                </div>
              </SettingGroup>

              {/* UI tweak — layout (persisted) */}
              <SettingGroup
                title="Layout"
                desc="Choose grid or rows for panels. Persists to localStorage."
              >
                <div className="st-seg">
                  {(['grid', 'rows'] as const).map((l) => (
                    <button
                      key={l}
                      data-active={uiState.layout === l}
                      onClick={() => persist({ layout: l })}
                    >
                      {l}
                    </button>
                  ))}
                </div>
              </SettingGroup>

              {/* UI tweak — theme (persisted) */}
              <SettingGroup
                title="Theme"
                desc="Choose dark or light. Persists to localStorage."
              >
                <div className="st-seg">
                  {(['dark', 'light'] as const).map((t) => (
                    <button
                      key={t}
                      data-active={uiState.theme === t}
                      onClick={() => persist({ theme: t })}
                    >
                      {t}
                    </button>
                  ))}
                </div>
              </SettingGroup>

              {/* UI tweak — hint visibility (persisted) */}
              <SettingGroup
                title="First-run hints"
                desc="Show or hide the on-canvas tip banner. Persists to localStorage."
              >
                <div className="st-seg">
                  <button
                    data-active={uiState.hintVisibility === true}
                    onClick={() => persist({ hintVisibility: true })}
                  >
                    show
                  </button>
                  <button
                    data-active={uiState.hintVisibility === false}
                    onClick={() => persist({ hintVisibility: false })}
                  >
                    hide
                  </button>
                </div>
              </SettingGroup>

              {/* Backend-touching: memory threshold — read-only, KR-41.6-06 */}
              <BackendRow
                label="Memory ceiling"
                value="90 %"
                desc="Inference pauses when RAM usage crosses this threshold. Configured in src/alphaswarm/config.py — Coming in v6.x as a runtime setting."
              />
              {/* Live from the memory governor (governor_metrics in every frame) */}
              <LiveRow
                label="Concurrent inference slots"
                value={`${telemetry.slotsUsed} in use / ${telemetry.slotsMax} allowed now`}
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
              desc="Cloud API keys are entered in Settings → Model and stored in .secrets/inference.json, an owner-only file (mode 0600) that the API never returns. yfinance prices and RSS headlines need no keys."
            >
              <LiveRow label="Key file" value=".secrets/inference.json" />
              <LiveRow label="Roles using a cloud API" value={cloudRolesSummary(privacy)} />
            </SettingGroup>
          )}

          {section === 'storage' && (
            <SettingGroup
              title="Storage"
              desc="Cycles, decisions and influence edges are stored in the local Neo4j database (Docker, loopback only). Reports and advisories are written as owner-only files."
            >
              <LiveRow label="Graph database" value="Neo4j on 127.0.0.1:7687" />
              <LiveRow label="Reports" value="reports/{cycle_id}_report.md" />
              <LiveRow label="Advisories" value="advisory/{cycle_id}_advisory.json" />
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
  fontFamily: "'JetBrains Mono', monospace",
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
