// Settings API client — GET/PUT /api/settings, POST /api/settings/test,
// GET /api/settings/estimate, GET /api/health (inference_mode + spent_usd).
//
// Policy (D-23 / codex MEDIUM-8): model/provider/key are BACKEND-owned and
// NEVER written to localStorage. This module only talks to the API.
//
// On PUT, api_key is a raw string per role; omit it (leave undefined) when
// the caller wants to keep the stored key — an empty string is treated as
// "omit" by putSettings() and stripped from the request body.
import { apiFetch, apiPost, request } from './client';

/** A cloud provider test can take up to its own 120 s request timeout. */
const CONNECTION_TEST_TIMEOUT_MS = 180_000;

// ── types ─────────────────────────────────────────────────────────────────

export type ProviderType = 'ollama' | 'openai_compatible' | 'anthropic';

/** GET response: api_key is always masked (never a raw string). */
export interface MaskedKey {
  set: boolean;
  last4: string | null;
}

/** Per-role view returned by GET /api/settings. */
export interface RoleView {
  provider: ProviderType;
  model: string;
  base_url: string | null;
  api_key: MaskedKey;
}

/** One entry in the provider_presets list returned by GET /api/settings. */
export interface ProviderPreset {
  label: string;
  provider: ProviderType;
  base_url: string | null;
  models: string[];
}

/** Full response from GET /api/settings. */
export interface SettingsView {
  config: {
    orchestrator: RoleView;
    worker: RoleView;
    limits: Record<
      string,
      {
        requests_per_min: number | null;
        tokens_per_min: number | null;
        max_in_flight: number;
      }
    >;
    spend_cap_usd: string | null;
    pricing_overrides: Record<
      string,
      { input_per_mtok: string; output_per_mtok: string }
    >;
    /** Cloud-advisory opt-in (backend default false; absent in older backends). */
    allow_cloud_advisory?: boolean;
  };
  mode: 'local' | 'cloud' | 'mixed';
  available_local_models: string[];
  known_api_models: string[];
  /** Convenience presets for popular inference providers. */
  provider_presets: ProviderPreset[];
}

/** PUT body: api_key is a raw string, or omit to keep stored key. */
export interface RolePut {
  provider: ProviderType;
  model: string;
  base_url: string | null;
  /** Omit or leave undefined to keep the currently stored key. */
  api_key?: string;
}

export interface SettingsPutBody {
  orchestrator: RolePut;
  worker: RolePut;
  limits?: SettingsView['config']['limits'];
  spend_cap_usd?: string | null;
  pricing_overrides?: SettingsView['config']['pricing_overrides'];
  /** Omit to keep the stored opt-in. */
  allow_cloud_advisory?: boolean;
}

/** GET /api/settings/estimate response. */
export interface RunEstimate {
  calls: number;
  low_usd: string;
  high_usd: string;
  mode: 'local' | 'cloud' | 'mixed';
}

/** POST /api/settings/test response. */
export interface TestResult {
  ok: boolean;
  error?: string;
}

/** Extra fields on GET /api/health added by the inference layer. */
export interface HealthWithInference {
  inference_mode: 'local' | 'cloud' | 'mixed';
  spent_usd: number | null;
  /** Package version from importlib.metadata (GET /api/health). */
  version?: string;
  [key: string]: unknown;
}

// ── helpers ────────────────────────────────────────────────────────────────

/**
 * Strip empty api_key from a RolePut before sending.
 * Spec: "empty/omitted → backend keeps the stored key."
 */
function sanitiseRolePut(role: RolePut): RolePut {
  if (!role.api_key) {
    const { api_key: _omit, ...rest } = role;
    void _omit; // explicitly suppress noUnusedLocals
    return rest;
  }
  return role;
}

// ── API functions ──────────────────────────────────────────────────────────

/** GET /api/settings — returns masked config + mode + model lists. */
export function getSettings(): Promise<SettingsView> {
  return apiFetch<SettingsView>('/api/settings');
}

/**
 * PUT /api/settings — update orchestrator/worker config.
 * Empty api_key strings are stripped (backend keeps stored key).
 * Throws ApiError with status 409 when a sim is running.
 */
export function putSettings(
  body: SettingsPutBody,
): Promise<{ config: SettingsView['config']; mode: SettingsView['mode'] }> {
  const sanitised: SettingsPutBody = {
    ...body,
    orchestrator: sanitiseRolePut(body.orchestrator),
    worker: sanitiseRolePut(body.worker),
  };
  return request('/api/settings', {
    method: 'PUT',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(sanitised),
  });
}

/** POST /api/settings/test — test stored connection for a role. Connection failures come back in the result; throws ApiError 409 simulation_running during a run. */
export function testConnection(
  role: 'orchestrator' | 'worker',
): Promise<TestResult> {
  return apiPost<TestResult>('/api/settings/test', { role }, { timeoutMs: CONNECTION_TEST_TIMEOUT_MS });
}

/** GET /api/settings/estimate — cost estimate for the next run. */
export function getEstimate(): Promise<RunEstimate> {
  return apiFetch<RunEstimate>('/api/settings/estimate');
}

/** GET /api/health — typed to include inference_mode + spent_usd. */
export function getHealth(): Promise<HealthWithInference> {
  return apiFetch<HealthWithInference>('/api/health');
}
