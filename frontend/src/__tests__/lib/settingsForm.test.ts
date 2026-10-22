// Inference settings form helpers. These are the functions the Settings view
// imports from src/lib/settingsForm.ts; nothing is re-implemented here.
import { describe, expect, it } from 'vitest';
import { ApiError } from '../../api/client';
import type { ProviderPreset, RoleView } from '../../api/settings';
import {
  applyPreset,
  extractErrorDetail,
  formToRolePut,
  isCloudProvider,
  maskedKeyPlaceholder,
  providerLabel,
  roleViewToForm,
  type RoleFormState,
} from '../../lib/settingsForm';

const baseForm: RoleFormState = { provider: 'ollama', model: '', base_url: '', api_key: '' };

const OPENROUTER: ProviderPreset = {
  label: 'OpenRouter',
  provider: 'openai_compatible',
  base_url: 'https://openrouter.ai/api/v1',
  models: ['openrouter/auto', 'mistralai/mistral-7b-instruct'],
};

const ANTHROPIC: ProviderPreset = {
  label: 'Anthropic',
  provider: 'anthropic',
  base_url: null,
  models: ['claude-opus-4-5', 'claude-sonnet-4-5'],
};

/** What JSON.stringify puts on the wire (undefined keys are dropped). */
function toWireBody(value: unknown): Record<string, unknown> {
  return JSON.parse(JSON.stringify(value)) as Record<string, unknown>;
}

describe('roleViewToForm', () => {
  it('never pre-fills the api key and maps a null base_url to an empty field', () => {
    const view: RoleView = {
      provider: 'anthropic',
      model: 'claude-sonnet-4-5',
      base_url: null,
      api_key: { set: true, last4: '1234' },
    };
    expect(roleViewToForm(view)).toEqual({
      provider: 'anthropic',
      model: 'claude-sonnet-4-5',
      base_url: '',
      api_key: '',
    });
  });
});

describe('formToRolePut — api_key', () => {
  it.each(['', '   '])('omits api_key when the field is %j (keep the stored key)', (apiKey) => {
    const body = toWireBody(formToRolePut({ ...baseForm, provider: 'anthropic', api_key: apiKey }));
    expect(body).not.toHaveProperty('api_key');
  });

  it('sends a non-empty key, trimmed', () => {
    const put = formToRolePut({ ...baseForm, provider: 'anthropic', api_key: ' sk-test ' });
    expect(put.api_key).toBe('sk-test');
  });
});

describe('formToRolePut — base_url', () => {
  it('keeps a trimmed base_url for openai_compatible', () => {
    const put = formToRolePut({
      ...baseForm,
      provider: 'openai_compatible',
      base_url: ' https://api.example.com/v1 ',
    });
    expect(put.base_url).toBe('https://api.example.com/v1');
  });

  it.each([
    ['ollama', 'http://localhost:11434'],
    ['anthropic', 'https://should.be.ignored'],
    ['openai_compatible', '   '],
  ] as const)('sends null for %s with field %j', (provider, baseUrl) => {
    expect(formToRolePut({ ...baseForm, provider, base_url: baseUrl }).base_url).toBeNull();
  });
});

describe('applyPreset', () => {
  it('sets provider and base_url and pre-fills the first model into an empty field', () => {
    expect(applyPreset(baseForm, OPENROUTER)).toEqual({
      provider: 'openai_compatible',
      base_url: 'https://openrouter.ai/api/v1',
      model: 'openrouter/auto',
      api_key: '',
    });
  });

  it('treats a whitespace-only model as empty', () => {
    expect(applyPreset({ ...baseForm, model: '   ' }, OPENROUTER).model).toBe('openrouter/auto');
  });

  it('never overwrites a model the user typed', () => {
    expect(applyPreset({ ...baseForm, model: 'my-model' }, ANTHROPIC).model).toBe('my-model');
  });

  it('maps a null preset base_url to an empty field and keeps the typed key', () => {
    const next = applyPreset({ ...baseForm, api_key: 'sk-keep' }, ANTHROPIC);
    expect(next.base_url).toBe('');
    expect(next.api_key).toBe('sk-keep');
  });

  it('leaves the model alone when the preset lists no models', () => {
    expect(applyPreset(baseForm, { ...ANTHROPIC, models: [] }).model).toBe('');
  });
});

describe('isCloudProvider / providerLabel', () => {
  it('classifies providers', () => {
    expect(isCloudProvider('openai_compatible')).toBe(true);
    expect(isCloudProvider('anthropic')).toBe(true);
    expect(isCloudProvider('ollama')).toBe(false);
  });

  it('renders human-readable labels', () => {
    expect(providerLabel('ollama')).toBe('Local (Ollama)');
    expect(providerLabel('openai_compatible')).toBe('OpenAI-compatible');
    expect(providerLabel('anthropic')).toBe('Anthropic');
  });
});

describe('maskedKeyPlaceholder', () => {
  it.each([
    [true, '1234', 'key set ••••1234 — leave blank to keep'],
    [true, null, 'key set •••• — leave blank to keep'],
    [false, null, 'enter API key'],
  ] as const)('set=%s last4=%s', (keySet, last4, expected) => {
    expect(maskedKeyPlaceholder(keySet, last4)).toBe(expected);
  });
});

describe('extractErrorDetail', () => {
  it('maps any 409 to the stop-the-simulation message', () => {
    const body = { detail: { error: 'simulation_running', message: 'busy' } };
    expect(extractErrorDetail(new ApiError(409, body, '/api/settings'))).toBe(
      'Stop the running simulation first.',
    );
  });

  it('shows the envelope message', () => {
    const body = { detail: { error: 'validation_error', message: 'Request validation failed' } };
    expect(extractErrorDetail(new ApiError(422, body, '/api/settings'))).toBe(
      'Request validation failed',
    );
  });

  it('names the fields a 422 validation_error rejected', () => {
    const body = {
      detail: {
        error: 'validation_error',
        message: 'Settings validation failed',
        fields: [
          {
            loc: ['body', 'worker', 'model'],
            msg: 'Input should be a valid string',
            type: 'string_type',
          },
          {
            loc: ['body', 'orchestrator', 'provider'],
            msg: 'Input should be a valid enum',
            type: 'enum',
          },
        ],
      },
    };
    expect(extractErrorDetail(new ApiError(422, body, '/api/settings'))).toBe(
      'Settings validation failed (worker.model: Input should be a valid string; ' +
        'orchestrator.provider: Input should be a valid enum)',
    );
  });

  it('shows a plain string detail', () => {
    const err = new ApiError(422, { detail: 'invalid model name' }, '/api/settings');
    expect(extractErrorDetail(err)).toBe('invalid model name');
  });

  it('falls back to "Error <status>" for a non-object body', () => {
    expect(extractErrorDetail(new ApiError(500, 'internal error', '/api/settings'))).toBe(
      'Error 500',
    );
  });

  it('uses the message of a plain Error and stringifies anything else', () => {
    expect(extractErrorDetail(new Error('network down'))).toBe('network down');
    expect(extractErrorDetail(42)).toBe('42');
  });
});
