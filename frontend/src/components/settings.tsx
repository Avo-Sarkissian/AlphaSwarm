// Settings — full-screen takeover.
//
// Ported from AlphaSwarm-2/src/settings.jsx (300 LOC) per D-03 and renamed
// .jsx → .tsx per codex HIGH-1 (uses `as const` allowlist + typed normalize helper).
//
// D-23 persistence policy:
//   • UI tweaks (density / layout / theme / hintVisibility) persist to
//     localStorage via normalizeSettingsUiState (codex MEDIUM-8 — drops any
//     backend keys nested in the persisted JSON object).
//   • Backend-touching keys (model / inferenceSlots / memoryThreshold /
//     agentCount / bracketWeights / keysTomlPath) render as read-only with
//     "Coming in v6.x" inline note (KR-41.6-06). They never touch localStorage.
import { useState } from 'react';
import {
  normalizeSettingsUiState,
  type SettingsUiState,
} from '../lib/settingsState';

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
    { k: 'keys' as const, label: 'Data keys' },
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
            <div className="label">ALPHASWARM v0.7.2</div>
            <div
              className="mono"
              style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 4 }}
            >
              local only
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
              {/* Backend-touching: inference slots — read-only, KR-41.6-06 */}
              <BackendRow
                label="Concurrent inference slots"
                value="8"
                desc="How many agents can be thinking at once. Configured at backend startup — Coming in v6.x."
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
              title="Active model"
              desc="All agents share one Ollama model. Configured in src/alphaswarm/config.py."
            >
              <BackendRow
                label="Model"
                value="qwen3:8b"
                desc="Worker model — Phase 41.4 locked qwen3:8b. Coming in v6.x as a runtime setting."
              />
              <BackendRow
                label="Orchestrator model"
                value="qwen3.6:27b (think=OFF)"
                desc="Synthesis model — Phase 41.4 locked. Coming in v6.x."
              />
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
              title="Data source credentials"
              desc="API keys for live data sources. Stored in keys.toml — never leaves your machine."
            >
              <BackendRow
                label="Keys file path"
                value="~/.alphaswarm/keys.toml"
                desc="Edit the file directly. Runtime UI editor coming in v6.x."
              />
            </SettingGroup>
          )}

          {section === 'storage' && (
            <SettingGroup
              title="Cycle archive"
              desc="Every cycle is saved locally as a reproducible JSONL trace."
            >
              <BackendRow
                label="Storage directory"
                value="~/.alphaswarm/cycles"
                desc="Configured at backend startup. Runtime UI controls coming in v6.x."
              />
            </SettingGroup>
          )}

          {section === 'privacy' && (
            <SettingGroup
              title="Local-first guarantees"
              desc="AlphaSwarm runs entirely on your machine. Inference is local; data-source HTTP calls go to public APIs only."
            >
              <div className="st-privacy">
                <div className="st-privacy-row yes">
                  <span className="st-check">✓</span>
                  <div>
                    <div className="st-privacy-title">Inference stays local</div>
                    <div className="st-privacy-desc">
                      All LLM calls go through Ollama on localhost. Prompts and
                      rationales never leave your machine.
                    </div>
                  </div>
                </div>
                <div className="st-privacy-row yes">
                  <span className="st-check">✓</span>
                  <div>
                    <div className="st-privacy-title">No telemetry</div>
                    <div className="st-privacy-desc">
                      AlphaSwarm makes zero outbound calls for analytics, crash
                      reporting, or anything else.
                    </div>
                  </div>
                </div>
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
    <div
      className="settings-row settings-row-locked"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '10px 0',
        borderBottom: '1px solid var(--border)',
      }}
    >
      <label style={{ minWidth: 220, color: 'var(--text-2)', fontSize: 12 }}>
        {label}
      </label>
      <input
        type="text"
        value={value}
        disabled
        readOnly
        style={{
          flex: 1,
          padding: '6px 10px',
          background: 'var(--bg-3)',
          border: '1px solid var(--border)',
          color: 'var(--text-3)',
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: 11,
          borderRadius: 3,
        }}
      />
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
