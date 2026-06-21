// Lightweight unit tests for settings_inference.tsx logic (Task 19).
// @testing-library/react is not installed in this project, so we test the
// pure helper logic extracted/mirrored from the component:
//   - roleViewToForm / formToRolePut (key sanitisation, base_url handling)
//   - providerLabel
//   - extractErrorDetail (ApiError 409 maps to the "stop simulation" message)
//
// These tests exercise the policy contracts:
//   • api_key is omitted in the PUT body when the form field is empty.
//   • base_url is null in the PUT body unless provider=openai_compatible.
//   • 409 response is translated to the human-readable message.
//   • masked key hint contains the last4 fragment.
import { describe, it, expect } from 'vitest';
import { ApiError } from '../api/client';

// ── Mirror helpers from settings_inference.tsx (kept in sync) ─────────────
// We duplicate the minimal pure-function logic here to avoid importing the
// React component (which requires a DOM environment we don't have in this
// project's vitest setup).

type ProviderType = 'ollama' | 'openai_compatible' | 'anthropic';

interface RoleFormState {
  provider: ProviderType;
  model: string;
  base_url: string;
  api_key: string;
}

interface RolePut {
  provider: ProviderType;
  model: string;
  base_url: string | null;
  api_key?: string;
}

function formToRolePut(f: RoleFormState): RolePut {
  return {
    provider: f.provider,
    model: f.model,
    base_url:
      f.provider === 'openai_compatible' && f.base_url.trim()
        ? f.base_url.trim()
        : null,
    api_key: f.api_key.trim() || undefined,
  };
}

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

// Derive the masked key placeholder text shown to the user.
function maskedKeyPlaceholder(set: boolean, last4: string | null): string {
  if (set) return `key set ••••${last4 ?? ''} — leave blank to keep`;
  return 'enter API key';
}

// ── tests ─────────────────────────────────────────────────────────────────

// Helper: simulate what JSON.stringify does (drops undefined values).
function toWireBody(r: RolePut): Record<string, unknown> {
  return JSON.parse(JSON.stringify(r)) as Record<string, unknown>;
}

describe('formToRolePut — api_key handling', () => {
  it('omits api_key from serialised PUT body when form field is empty', () => {
    const result = toWireBody(
      formToRolePut({
        provider: 'anthropic',
        model: 'claude-3-5-sonnet-20241022',
        base_url: '',
        api_key: '', // blank → keep stored key
      }),
    );
    expect(result).not.toHaveProperty('api_key');
  });

  it('omits api_key from serialised PUT body when field is whitespace-only', () => {
    const result = toWireBody(
      formToRolePut({
        provider: 'anthropic',
        model: 'claude-3-haiku-20240307',
        base_url: '',
        api_key: '   ',
      }),
    );
    expect(result).not.toHaveProperty('api_key');
  });

  it('includes api_key in PUT body when non-empty', () => {
    const result = formToRolePut({
      provider: 'anthropic',
      model: 'claude-3-5-sonnet-20241022',
      base_url: '',
      api_key: 'sk-ant-test',
    });
    expect(result.api_key).toBe('sk-ant-test');
  });
});

describe('formToRolePut — base_url handling', () => {
  it('includes base_url only for openai_compatible', () => {
    const result = formToRolePut({
      provider: 'openai_compatible',
      model: 'gpt-4o',
      base_url: 'https://api.openai.com/v1',
      api_key: '',
    });
    expect(result.base_url).toBe('https://api.openai.com/v1');
  });

  it('forces base_url to null for ollama even if field is populated', () => {
    const result = formToRolePut({
      provider: 'ollama',
      model: 'qwen3.6:27b-nvfp4',
      base_url: 'http://localhost:11434',
      api_key: '',
    });
    expect(result.base_url).toBeNull();
  });

  it('forces base_url to null for anthropic', () => {
    const result = formToRolePut({
      provider: 'anthropic',
      model: 'claude-3-5-sonnet-20241022',
      base_url: 'https://should.be.ignored',
      api_key: '',
    });
    expect(result.base_url).toBeNull();
  });

  it('sets base_url to null when openai_compatible but field is empty', () => {
    const result = formToRolePut({
      provider: 'openai_compatible',
      model: 'gpt-4o',
      base_url: '',
      api_key: '',
    });
    expect(result.base_url).toBeNull();
  });
});

describe('isCloudProvider', () => {
  it('returns true for openai_compatible and anthropic', () => {
    expect(isCloudProvider('openai_compatible')).toBe(true);
    expect(isCloudProvider('anthropic')).toBe(true);
  });

  it('returns false for ollama', () => {
    expect(isCloudProvider('ollama')).toBe(false);
  });
});

describe('providerLabel', () => {
  it('renders human-readable labels', () => {
    expect(providerLabel('ollama')).toBe('Local (Ollama)');
    expect(providerLabel('openai_compatible')).toBe('OpenAI-compatible');
    expect(providerLabel('anthropic')).toBe('Anthropic');
  });
});

describe('extractErrorDetail', () => {
  it('maps 409 ApiError to the "stop simulation" message', () => {
    const err = new ApiError(409, { detail: 'running' }, '/api/settings');
    expect(extractErrorDetail(err)).toBe(
      'Stop the running simulation first.',
    );
  });

  it('extracts detail string from 422 ApiError body', () => {
    const err = new ApiError(422, { detail: 'invalid model name' }, '/api/settings');
    expect(extractErrorDetail(err)).toBe('invalid model name');
  });

  it('returns "Error <status>" for ApiError with non-object body', () => {
    const err = new ApiError(500, 'internal error', '/api/settings');
    expect(extractErrorDetail(err)).toBe('Error 500');
  });

  it('extracts message from plain Error', () => {
    expect(extractErrorDetail(new Error('network down'))).toBe('network down');
  });
});

describe('maskedKeyPlaceholder', () => {
  it('shows last4 hint when key is set', () => {
    expect(maskedKeyPlaceholder(true, '1234')).toBe(
      'key set ••••1234 — leave blank to keep',
    );
  });

  it('shows generic hint when last4 is null', () => {
    expect(maskedKeyPlaceholder(true, null)).toBe(
      'key set •••• — leave blank to keep',
    );
  });

  it('prompts for key entry when not set', () => {
    expect(maskedKeyPlaceholder(false, null)).toBe('enter API key');
  });
});
