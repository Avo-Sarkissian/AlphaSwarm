// Pure helpers behind the Inference settings form (components/settings_inference.tsx).
// They hold no React state, so the tests import them directly.
//
// Policy: model / provider / api_key are backend-owned and never touch
// localStorage. An empty api_key field means "keep the stored key".
import { ApiError } from '../api/client';
import type { ProviderPreset, ProviderType, RolePut, RoleView } from '../api/settings';
import { fieldErrors, formatApiError } from './apiError';

export interface RoleFormState {
  provider: ProviderType;
  model: string;
  base_url: string;
  /** Raw text; empty = keep stored key. */
  api_key: string;
}

export function roleViewToForm(r: RoleView): RoleFormState {
  return {
    provider: r.provider,
    model: r.model,
    base_url: r.base_url ?? '',
    api_key: '',
  };
}

export function formToRolePut(f: RoleFormState): RolePut {
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

export function isCloudProvider(p: ProviderType): boolean {
  return p === 'openai_compatible' || p === 'anthropic';
}

export function providerLabel(p: ProviderType): string {
  if (p === 'ollama') return 'Local (Ollama)';
  if (p === 'openai_compatible') return 'OpenAI-compatible';
  return 'Anthropic';
}

/** API-key input placeholder: hints at the stored key without revealing it. */
export function maskedKeyPlaceholder(keySet: boolean, last4: string | null): string {
  return keySet ? `key set ••••${last4 ?? ''} — leave blank to keep` : 'enter API key';
}

// The shared formatter's text, plus the settings-specific 409 hint and the
// fields a 422 rejected (so the user knows what to fix).
export function extractErrorDetail(e: unknown): string {
  if (e instanceof ApiError && e.status === 409) return 'Stop the running simulation first.';
  const message = formatApiError(e);
  if (!(e instanceof ApiError)) return message;
  const fields = fieldErrors(e.body).map((f) => (f.loc ? `${f.loc}: ${f.msg}` : f.msg));
  return fields.length > 0 ? `${message} (${fields.join('; ')})` : message;
}
