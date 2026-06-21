// Inference / Models settings section — writable backend-owned config.
//
// Policy (D-23 / codex MEDIUM-8):
//   Model / provider / api_key values are BACKEND-owned.
//   They NEVER touch localStorage. Only UI-tweak keys (density / layout /
//   theme / hintVisibility) may be persisted by settings.tsx.
//
// Wiring:
//   • On mount: getSettings() populates form state from the backend config.
//   • Save: putSettings(...) → on success refresh from returned config.
//     409 → "stop the running simulation first"
//     400/422 → show validation detail from ApiError.body
//   • Test: testConnection(role) per-role inline ok/error.
//   • base_url input only shown when provider = openai_compatible.
//   • api_key password input shown for cloud providers; masked hint when key set.
//   • limits (rpm/tpm) and spend_cap shown for cloud providers.
import { useState, useEffect, useRef } from 'react';
import {
  getSettings,
  putSettings,
  testConnection,
  type ProviderType,
  type ProviderPreset,
  type RoleView,
  type SettingsView,
  type RolePut,
} from '../api/settings';
import { ApiError } from '../api/client';

// ── local form state ──────────────────────────────────────────────────────

interface RoleFormState {
  provider: ProviderType;
  model: string;
  base_url: string;
  /** Raw text; empty = keep stored key. */
  api_key: string;
}

function roleViewToForm(r: RoleView): RoleFormState {
  return {
    provider: r.provider,
    model: r.model,
    base_url: r.base_url ?? '',
    api_key: '',
  };
}

function formToRolePut(f: RoleFormState): RolePut {
  return {
    provider: f.provider,
    model: f.model,
    base_url:
      f.provider === 'openai_compatible' && f.base_url.trim()
        ? f.base_url.trim()
        : null,
    // Omit api_key when empty (backend keeps stored key).
    api_key: f.api_key.trim() || undefined,
  };
}

/**
 * Apply a provider preset to a role form.
 * Pre-fills provider, base_url, and — if the model field is empty — the first
 * preset model. The caller may freely edit any field after applying.
 */
export function applyPreset(
  form: RoleFormState,
  preset: ProviderPreset,
): RoleFormState {
  return {
    ...form,
    provider: preset.provider,
    base_url: preset.base_url ?? '',
    model: form.model.trim() === '' && preset.models.length > 0
      ? preset.models[0]!
      : form.model,
  };
}

// ── helpers ────────────────────────────────────────────────────────────────

function isCloudProvider(p: ProviderType): boolean {
  return p === 'openai_compatible' || p === 'anthropic';
}

function providerLabel(p: ProviderType): string {
  if (p === 'ollama') return 'Local (Ollama)';
  if (p === 'openai_compatible') return 'OpenAI-compatible';
  return 'Anthropic';
}

function extractErrorDetail(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 409) return 'Stop the running simulation first.';
    if (typeof e.body === 'object' && e.body !== null) {
      const b = e.body as Record<string, unknown>;
      if (typeof b['detail'] === 'string') return b['detail'];
      try {
        return JSON.stringify(b);
      } catch {
        /* fall through */
      }
    }
    return `Error ${e.status}`;
  }
  if (e instanceof Error) return e.message;
  return String(e);
}

// ── sub-component: per-role form ──────────────────────────────────────────

interface RoleFormProps {
  roleLabel: 'Orchestrator' | 'Worker';
  roleKey: 'orchestrator' | 'worker';
  form: RoleFormState;
  originalView: RoleView;
  availableLocalModels: string[];
  knownApiModels: string[];
  presets: ProviderPreset[];
  onChange: (patch: Partial<RoleFormState>) => void;
  onReplace: (next: RoleFormState) => void;
}

function RoleForm({
  roleLabel,
  roleKey,
  form,
  originalView,
  availableLocalModels,
  knownApiModels,
  presets,
  onChange,
  onReplace,
}: RoleFormProps) {
  const [testState, setTestState] = useState<
    'idle' | 'loading' | 'ok' | 'error'
  >('idle');
  const [testMsg, setTestMsg] = useState('');

  const isCloud = isCloudProvider(form.provider);
  // After a preset is applied its models become the datalist suggestions;
  // fall back to the standard lists when no preset is active.
  const [presetModels, setPresetModels] = useState<string[] | null>(null);
  const modelSuggestions =
    presetModels ??
    (form.provider === 'ollama' ? availableLocalModels : knownApiModels);
  const listId = `model-list-${roleKey}`;
  const keySet = originalView.api_key.set;
  const last4 = originalView.api_key.last4;

  async function handleTest() {
    setTestState('loading');
    setTestMsg('');
    try {
      const result = await testConnection(roleKey);
      if (result.ok) {
        setTestState('ok');
        setTestMsg('Connection OK');
      } else {
        setTestState('error');
        setTestMsg(result.error ?? 'Connection failed');
      }
    } catch (e: unknown) {
      setTestState('error');
      setTestMsg(extractErrorDetail(e));
    }
  }

  return (
    <div className="st-inf-role">
      <div
        className="st-inf-role-head"
        style={{
          fontWeight: 600,
          fontSize: 12,
          color: 'var(--text-2)',
          marginBottom: 10,
          textTransform: 'uppercase',
          letterSpacing: '0.08em',
        }}
      >
        {roleLabel}
      </div>

      {/* Preset picker — shortcut to populate provider + base_url + model */}
      {presets.length > 0 && (
        <div className="st-inf-row">
          <label className="st-inf-label">Preset</label>
          <select
            className="st-inf-select"
            defaultValue=""
            onChange={(e) => {
              const idx = e.target.value;
              if (idx === '') return;
              const preset = presets[Number(idx)];
              if (!preset) return;
              onReplace(applyPreset(form, preset));
              setPresetModels(preset.models);
              // Reset to "Custom" visually after applying so the user can
              // re-select the same preset again if they want.
              e.target.value = '';
            }}
            style={{
              flex: 1,
              padding: '6px 10px',
              background: 'var(--bg-3)',
              border: '1px solid var(--border)',
              color: 'var(--text-1)',
              fontSize: 12,
              borderRadius: 3,
              fontFamily: "'JetBrains Mono', monospace",
            }}
          >
            <option value="">— Custom —</option>
            {presets.map((p, i) => (
              <option key={i} value={i}>
                {p.label}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Provider select */}
      <div className="st-inf-row">
        <label className="st-inf-label">Provider</label>
        <select
          className="st-inf-select"
          value={form.provider}
          onChange={(e) =>
            onChange({ provider: e.target.value as ProviderType })
          }
          style={{
            flex: 1,
            padding: '6px 10px',
            background: 'var(--bg-3)',
            border: '1px solid var(--border)',
            color: 'var(--text-1)',
            fontSize: 12,
            borderRadius: 3,
            fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          <option value="ollama">{providerLabel('ollama')}</option>
          <option value="openai_compatible">
            {providerLabel('openai_compatible')}
          </option>
          <option value="anthropic">{providerLabel('anthropic')}</option>
        </select>
      </div>

      {/* Model */}
      <div className="st-inf-row">
        <label className="st-inf-label">Model</label>
        <input
          type="text"
          list={listId}
          className="st-inf-input"
          value={form.model}
          onChange={(e) => onChange({ model: e.target.value })}
          placeholder="model name"
          style={{
            flex: 1,
            padding: '6px 10px',
            background: 'var(--bg-3)',
            border: '1px solid var(--border)',
            color: 'var(--text-1)',
            fontSize: 12,
            borderRadius: 3,
            fontFamily: "'JetBrains Mono', monospace",
          }}
        />
        <datalist id={listId}>
          {modelSuggestions.map((m) => (
            <option key={m} value={m} />
          ))}
        </datalist>
      </div>

      {/* Base URL — only for openai_compatible */}
      {form.provider === 'openai_compatible' && (
        <div className="st-inf-row">
          <label className="st-inf-label">Base URL</label>
          <input
            type="text"
            className="st-inf-input"
            value={form.base_url}
            onChange={(e) => onChange({ base_url: e.target.value })}
            placeholder="https://..."
            style={{
              flex: 1,
              padding: '6px 10px',
              background: 'var(--bg-3)',
              border: '1px solid var(--border)',
              color: 'var(--text-1)',
              fontSize: 12,
              borderRadius: 3,
              fontFamily: "'JetBrains Mono', monospace",
            }}
          />
        </div>
      )}

      {/* API key — cloud providers only */}
      {isCloud && (
        <div className="st-inf-row">
          <label className="st-inf-label">API key</label>
          <input
            type="password"
            className="st-inf-input"
            value={form.api_key}
            onChange={(e) => onChange({ api_key: e.target.value })}
            placeholder={
              keySet
                ? `key set ••••${last4 ?? ''} — leave blank to keep`
                : 'enter API key'
            }
            style={{
              flex: 1,
              padding: '6px 10px',
              background: 'var(--bg-3)',
              border: '1px solid var(--border)',
              color: 'var(--text-1)',
              fontSize: 12,
              borderRadius: 3,
              fontFamily: "'JetBrains Mono', monospace",
            }}
          />
        </div>
      )}

      {/* Test connection */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          marginTop: 8,
        }}
      >
        <button
          className="btn ghost"
          style={{ fontSize: 11 }}
          disabled={testState === 'loading'}
          onClick={() => void handleTest()}
        >
          {testState === 'loading' ? 'Testing…' : 'Test connection'}
        </button>
        {testState !== 'idle' && testState !== 'loading' && (
          <span
            style={{
              fontSize: 11,
              color:
                testState === 'ok'
                  ? 'var(--accent-green, #4ade80)'
                  : 'var(--accent-red, #f87171)',
            }}
          >
            {testMsg}
          </span>
        )}
      </div>
    </div>
  );
}

// ── main component ────────────────────────────────────────────────────────

export function InferenceSettings() {
  const [view, setView] = useState<SettingsView | null>(null);
  const [orch, setOrch] = useState<RoleFormState | null>(null);
  const [worker, setWorker] = useState<RoleFormState | null>(null);
  const [spendCap, setSpendCap] = useState<string>('');

  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveOk, setSaveOk] = useState(false);
  const saveOkTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Clear saveOk timer on unmount to avoid setState-after-unmount.
  useEffect(() => {
    return () => {
      if (saveOkTimer.current !== null) clearTimeout(saveOkTimer.current);
    };
  }, []);

  // Load on mount
  useEffect(() => {
    let cancelled = false;
    setLoadError(null);
    getSettings()
      .then((s) => {
        if (cancelled) return;
        setView(s);
        setOrch(roleViewToForm(s.config.orchestrator));
        setWorker(roleViewToForm(s.config.worker));
        setSpendCap(s.config.spend_cap_usd ?? '');
      })
      .catch((e: unknown) => {
        if (!cancelled)
          setLoadError(extractErrorDetail(e));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleSave() {
    if (!orch || !worker) return;
    setSaving(true);
    setSaveError(null);
    setSaveOk(false);
    try {
      const result = await putSettings({
        orchestrator: formToRolePut(orch),
        worker: formToRolePut(worker),
        spend_cap_usd: spendCap.trim() || null,
      });
      // Refresh from returned config
      setView((prev) =>
        prev
          ? {
              ...prev,
              config: result.config,
              mode: result.mode,
            }
          : null,
      );
      // Re-seed form from returned config (resets api_key fields + updates masks)
      setOrch(roleViewToForm(result.config.orchestrator));
      setWorker(roleViewToForm(result.config.worker));
      setSaveOk(true);
      if (saveOkTimer.current !== null) clearTimeout(saveOkTimer.current);
      saveOkTimer.current = setTimeout(() => setSaveOk(false), 3000);
    } catch (e: unknown) {
      setSaveError(extractErrorDetail(e));
    } finally {
      setSaving(false);
    }
  }

  if (loadError) {
    return (
      <div
        style={{ color: 'var(--accent-red, #f87171)', fontSize: 12, padding: 8 }}
      >
        Failed to load inference settings: {loadError}
      </div>
    );
  }

  if (!view || !orch || !worker) {
    return (
      <div
        style={{ color: 'var(--text-3)', fontSize: 12, padding: 8 }}
      >
        Loading…
      </div>
    );
  }

  const anyCloud =
    isCloudProvider(orch.provider) || isCloudProvider(worker.provider);

  return (
    <div className="st-inf">
      <RoleForm
        roleLabel="Orchestrator"
        roleKey="orchestrator"
        form={orch}
        originalView={view.config.orchestrator}
        availableLocalModels={view.available_local_models}
        knownApiModels={view.known_api_models}
        presets={view.provider_presets ?? []}
        onChange={(patch) => setOrch((prev) => prev ? { ...prev, ...patch } : prev)}
        onReplace={(next) => setOrch(next)}
      />

      <div
        style={{
          borderTop: '1px solid var(--border)',
          margin: '14px 0',
        }}
      />

      <RoleForm
        roleLabel="Worker"
        roleKey="worker"
        form={worker}
        originalView={view.config.worker}
        availableLocalModels={view.available_local_models}
        knownApiModels={view.known_api_models}
        presets={view.provider_presets ?? []}
        onChange={(patch) => setWorker((prev) => prev ? { ...prev, ...patch } : prev)}
        onReplace={(next) => setWorker(next)}
      />

      {/* Spend cap — shown when either role is cloud */}
      {anyCloud && (
        <>
          <div style={{ borderTop: '1px solid var(--border)', margin: '14px 0' }} />
          <div className="st-inf-row">
            <label className="st-inf-label">Spend cap (USD)</label>
            <input
              type="number"
              min={0}
              step={0.01}
              className="st-inf-input"
              value={spendCap}
              onChange={(e) => setSpendCap(e.target.value)}
              placeholder="no cap"
              style={{
                width: 120,
                padding: '6px 10px',
                background: 'var(--bg-3)',
                border: '1px solid var(--border)',
                color: 'var(--text-1)',
                fontSize: 12,
                borderRadius: 3,
                fontFamily: "'JetBrains Mono', monospace",
              }}
            />
          </div>
        </>
      )}

      {/* Save bar */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          marginTop: 16,
        }}
      >
        <button
          className="btn"
          disabled={saving}
          onClick={() => void handleSave()}
          style={{ fontSize: 12 }}
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
        {saveOk && !saving && (
          <span style={{ fontSize: 11, color: 'var(--accent-green, #4ade80)' }}>
            Saved.
          </span>
        )}
        {saveError && (
          <span
            style={{
              fontSize: 11,
              color: 'var(--accent-red, #f87171)',
            }}
          >
            {saveError}
          </span>
        )}
      </div>
    </div>
  );
}
