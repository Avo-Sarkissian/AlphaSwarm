// One inference role's provider, model, base URL, key and connection test.
import { useState } from 'react';
import { testConnection, type ProviderPreset, type ProviderType, type RoleView } from '../../api/settings';
import {
  applyPreset,
  extractErrorDetail,
  isCloudProvider,
  maskedKeyPlaceholder,
  providerLabel,
  type RoleFormState,
} from '../../lib/settingsForm';

export interface RoleFormProps {
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

export function RoleForm({
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
      <div className="st-inf-role-head">
        {roleLabel}
      </div>

      {/* Preset picker — shortcut to populate provider + base_url + model */}
      {presets.length > 0 && (
        <div className="st-inf-row">
          <label className="st-inf-label">Preset</label>
          <select
            className="st-inf-select st-inf-field"
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
          className="st-inf-select st-inf-field"
          value={form.provider}
          onChange={(e) =>
            onChange({ provider: e.target.value as ProviderType })
          }
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
          className="st-inf-input st-inf-field"
          value={form.model}
          onChange={(e) => onChange({ model: e.target.value })}
          placeholder="model name"
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
            className="st-inf-input st-inf-field"
            value={form.base_url}
            onChange={(e) => onChange({ base_url: e.target.value })}
            placeholder="https://..."
          />
        </div>
      )}

      {/* API key — cloud providers only */}
      {isCloud && (
        <div className="st-inf-row">
          <label className="st-inf-label">API key</label>
          <input
            type="password"
            className="st-inf-input st-inf-field"
            value={form.api_key}
            onChange={(e) => onChange({ api_key: e.target.value })}
            placeholder={maskedKeyPlaceholder(keySet, last4)}
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
