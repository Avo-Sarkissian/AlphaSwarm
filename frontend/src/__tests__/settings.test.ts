// Tests for frontend/src/api/settings.ts (Task 18).
// Mocks global fetch; no DOM/React needed.
//
// Covers:
//   1. getSettings() parses masked config correctly.
//   2. putSettings() strips empty api_key from the request body.
//   3. putSettings() includes api_key when non-empty.
//   4. getEstimate() parses RunEstimate fields.
//   5. testConnection() serialises the role field.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  getSettings,
  putSettings,
  testConnection,
  getEstimate,
} from '../api/settings';

// ── mock helpers ──────────────────────────────────────────────────────────

function mockFetchOk(body: unknown) {
  return vi.fn().mockResolvedValue({
    ok: true,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(''),
  });
}

function mockFetchErr(status: number, body: unknown) {
  return vi.fn().mockResolvedValue({
    ok: false,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(''),
  });
}

// ── fixtures ───────────────────────────────────────────────────────────────

const MASKED_SETTINGS = {
  config: {
    orchestrator: {
      provider: 'ollama',
      model: 'qwen3.6:27b-nvfp4',
      base_url: null,
      api_key: { set: false, last4: null },
    },
    worker: {
      provider: 'anthropic',
      model: 'claude-3-5-sonnet-20241022',
      base_url: null,
      api_key: { set: true, last4: '1234' },
    },
    limits: {
      anthropic: {
        requests_per_min: 60,
        tokens_per_min: 100000,
        max_in_flight: 4,
      },
    },
    spend_cap_usd: '5.00',
    pricing_overrides: {},
  },
  mode: 'mixed',
  available_local_models: ['qwen3.6:27b-nvfp4', 'qwen3.6:35b-a3b-nvfp4'],
  known_api_models: ['claude-3-5-sonnet-20241022', 'claude-3-haiku-20240307'],
};

const ESTIMATE = {
  calls: 300,
  low_usd: '0.12',
  high_usd: '0.45',
  mode: 'cloud',
};

// ── tests ─────────────────────────────────────────────────────────────────

describe('getSettings()', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', mockFetchOk(MASKED_SETTINGS));
  });

  it('parses masked config with set=false', async () => {
    const result = await getSettings();
    expect(result.config.orchestrator.api_key.set).toBe(false);
    expect(result.config.orchestrator.api_key.last4).toBeNull();
  });

  it('parses masked config with set=true and last4', async () => {
    const result = await getSettings();
    expect(result.config.worker.api_key.set).toBe(true);
    expect(result.config.worker.api_key.last4).toBe('1234');
  });

  it('parses mode field', async () => {
    const result = await getSettings();
    expect(result.mode).toBe('mixed');
  });

  it('parses available_local_models', async () => {
    const result = await getSettings();
    expect(result.available_local_models).toContain('qwen3.6:27b-nvfp4');
  });
});

describe('putSettings()', () => {
  it('strips empty api_key from orchestrator when unchanged', async () => {
    const captured: RequestInit[] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((_url: string, init: RequestInit) => {
        captured.push(init);
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({ config: MASKED_SETTINGS.config, mode: 'mixed' }),
          text: () => Promise.resolve(''),
        });
      }),
    );

    await putSettings({
      orchestrator: {
        provider: 'ollama',
        model: 'qwen3.6:27b-nvfp4',
        base_url: null,
        api_key: '', // empty → should be omitted
      },
      worker: {
        provider: 'anthropic',
        model: 'claude-3-5-sonnet-20241022',
        base_url: null,
        api_key: 'sk-ant-test-key',
      },
    });

    expect(captured).toHaveLength(1);
    const body = JSON.parse(captured[0].body as string) as Record<
      string,
      unknown
    >;
    // orchestrator: api_key should be absent
    const orch = body['orchestrator'] as Record<string, unknown>;
    expect(orch).not.toHaveProperty('api_key');
  });

  it('includes api_key in worker when non-empty', async () => {
    const captured: RequestInit[] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((_url: string, init: RequestInit) => {
        captured.push(init);
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({ config: MASKED_SETTINGS.config, mode: 'cloud' }),
          text: () => Promise.resolve(''),
        });
      }),
    );

    await putSettings({
      orchestrator: {
        provider: 'ollama',
        model: 'qwen3.6:27b-nvfp4',
        base_url: null,
      },
      worker: {
        provider: 'anthropic',
        model: 'claude-3-haiku-20240307',
        base_url: null,
        api_key: 'sk-ant-real-key',
      },
    });

    const body = JSON.parse(captured[0].body as string) as Record<
      string,
      unknown
    >;
    const w = body['worker'] as Record<string, unknown>;
    expect(w['api_key']).toBe('sk-ant-real-key');
  });

  it('throws ApiError with status 409 when sim is running', async () => {
    vi.stubGlobal(
      'fetch',
      mockFetchErr(409, { detail: 'simulation is running' }),
    );
    await expect(
      putSettings({
        orchestrator: {
          provider: 'ollama',
          model: 'x',
          base_url: null,
        },
        worker: {
          provider: 'ollama',
          model: 'y',
          base_url: null,
        },
      }),
    ).rejects.toMatchObject({ status: 409 });
  });
});

describe('testConnection()', () => {
  it('sends role in body and parses ok=true', async () => {
    const captured: RequestInit[] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((_url: string, init: RequestInit) => {
        captured.push(init);
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ ok: true }),
          text: () => Promise.resolve(''),
        });
      }),
    );

    const result = await testConnection('orchestrator');
    expect(result.ok).toBe(true);
    const body = JSON.parse(captured[0].body as string) as Record<
      string,
      unknown
    >;
    expect(body['role']).toBe('orchestrator');
  });

  it('parses ok=false with error message', async () => {
    vi.stubGlobal(
      'fetch',
      mockFetchOk({ ok: false, error: 'connection refused' }),
    );
    const result = await testConnection('worker');
    expect(result.ok).toBe(false);
    expect(result.error).toBe('connection refused');
  });
});

describe('getEstimate()', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', mockFetchOk(ESTIMATE));
  });

  it('parses calls, low_usd, high_usd, mode', async () => {
    const result = await getEstimate();
    expect(result.calls).toBe(300);
    expect(result.low_usd).toBe('0.12');
    expect(result.high_usd).toBe('0.45');
    expect(result.mode).toBe('cloud');
  });
});
