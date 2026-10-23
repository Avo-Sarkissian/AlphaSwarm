// Inference / Models settings section — writable backend-owned config.
//
// Policy (docs/DECISIONS.md#p41-6-d-23):
//   Model / provider / api_key values are BACKEND-owned.
//   They NEVER touch localStorage; nothing in Settings is stored in the browser.
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
import { getSettings, putSettings, type SettingsView } from '../../api/settings';
import {
  extractErrorDetail,
  formToRolePut,
  isCloudProvider,
  roleViewToForm,
  type RoleFormState,
} from '../../lib/settingsForm';
import { advisoryOptInHelp, isOffMachine, roleFactsOf } from '../../lib/privacyCopy';
import { RoleForm } from './RoleForm';

// ── main component ────────────────────────────────────────────────────────

interface InferenceSettingsProps {
  /** Called with the settings a save stored, so the privacy copy can follow them. */
  onSaved?: (view: SettingsView) => void;
}

export function InferenceSettings({ onSaved }: InferenceSettingsProps) {
  const [view, setView] = useState<SettingsView | null>(null);
  const [orch, setOrch] = useState<RoleFormState | null>(null);
  const [worker, setWorker] = useState<RoleFormState | null>(null);
  const [spendCap, setSpendCap] = useState<string>('');
  const [allowCloudAdvisory, setAllowCloudAdvisory] = useState<boolean>(false);

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
        setAllowCloudAdvisory(s.config.allow_cloud_advisory === true);
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
    if (!view || !orch || !worker) return;
    setSaving(true);
    setSaveError(null);
    setSaveOk(false);
    try {
      const result = await putSettings({
        orchestrator: formToRolePut(orch),
        worker: formToRolePut(worker),
        spend_cap_usd: spendCap.trim() || null,
        allow_cloud_advisory: allowCloudAdvisory,
      });
      // Refresh from returned config
      const saved: SettingsView = { ...view, config: result.config, mode: result.mode };
      setView(saved);
      onSaved?.(saved);
      // Re-seed form from returned config (resets api_key fields + updates masks)
      setOrch(roleViewToForm(result.config.orchestrator));
      setWorker(roleViewToForm(result.config.worker));
      setAllowCloudAdvisory(result.config.allow_cloud_advisory === true);
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
  // The orchestrator Save would store: formToRolePut drops base_url for every
  // provider but openai_compatible, so a URL left in the form is not used.
  const orchFacts = roleFactsOf(formToRolePut(orch));
  // Shown for an off-machine orchestrator, and whenever the opt-in is ticked or
  // stored, so one left over from a cloud orchestrator can be seen and cleared.
  const showOptIn =
    isOffMachine(orchFacts) || allowCloudAdvisory || view.config.allow_cloud_advisory === true;

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

      {/* Cloud-advisory opt-in: shown whenever the orchestrator is off this machine
          (a cloud provider, an Ollama cloud model or a remote Ollama server), the
          same rule the backend's advisory gate applies, or the opt-in is on
          (docs/DECISIONS.md#adr-advisory-pipeline) */}
      {showOptIn && (
        <>
          <div style={{ borderTop: '1px solid var(--border)', margin: '14px 0' }} />
          <div className="st-inf-row">
            <label className="st-inf-label" htmlFor="allow-cloud-advisory">
              Allow cloud advisory
            </label>
            <input
              id="allow-cloud-advisory"
              type="checkbox"
              checked={allowCloudAdvisory}
              onChange={(e) => setAllowCloudAdvisory(e.target.checked)}
            />
          </div>
          <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 4 }}>
            {advisoryOptInHelp(orchFacts)}
          </div>
        </>
      )}

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
              className="st-inf-input st-inf-field st-inf-field-narrow"
              value={spendCap}
              onChange={(e) => setSpendCap(e.target.value)}
              placeholder="no cap"
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
