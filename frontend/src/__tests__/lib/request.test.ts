import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, DEFAULT_TIMEOUT_MS, request } from '../../api/client';
import { askAgent } from '../../api/interview';
import { putSettings, testConnection } from '../../api/settings';
import { errorMessage, formatApiError, isBackendUnreachable } from '../../lib/apiError';
import { stubFetch } from '../helpers/fetchStub';

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

/** fetch that never answers but honours its AbortSignal, like a stalled server. */
function hangingFetch() {
  const mock = vi.fn(
    (_input: RequestInfo | URL, init?: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () =>
          reject(new DOMException('The operation was aborted.', 'AbortError')),
        );
      }),
  );
  vi.stubGlobal('fetch', mock);
  return mock;
}

async function rejectsWithin(promise: Promise<unknown>, quietMs: number, totalMs: number) {
  let rejected = false;
  const settled = promise.catch(() => {
    rejected = true;
  });
  await vi.advanceTimersByTimeAsync(quietMs);
  const earlyReject = rejected;
  await vi.advanceTimersByTimeAsync(totalMs - quietMs);
  await settled;
  return { earlyReject, rejected };
}

describe('request()', () => {
  it('returns parsed JSON on 2xx', async () => {
    stubFetch([{ path: '/api/thing', body: { ok: true } }]);
    await expect(request<{ ok: boolean }>('/api/thing')).resolves.toEqual({ ok: true });
  });

  it('turns the error envelope into a readable message and code', async () => {
    stubFetch([
      {
        path: '/api/thing',
        status: 409,
        body: { detail: { error: 'shock_window_closed', message: 'The shock window has closed' } },
      },
    ]);
    const err = await request('/api/thing').catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 409, code: 'shock_window_closed', message: 'The shock window has closed' });
  });

  it('times out after the default with code "timeout"', async () => {
    vi.useFakeTimers();
    hangingFetch();
    const pending = request('/api/slow');
    const assertion = expect(pending).rejects.toMatchObject({ status: 0, code: 'timeout' });
    await vi.advanceTimersByTimeAsync(DEFAULT_TIMEOUT_MS);
    await assertion;
  });

  it('honours a per-call timeout longer than the default', async () => {
    vi.useFakeTimers();
    hangingFetch();
    const outcome = await rejectsWithin(request('/api/slow', { timeoutMs: 600_000 }), DEFAULT_TIMEOUT_MS + 1_000, 601_000);
    expect(outcome).toEqual({ earlyReject: false, rejected: true });
  });

  it('rethrows a caller abort untouched', async () => {
    hangingFetch();
    const controller = new AbortController();
    const pending = request('/api/slow', { signal: controller.signal });
    controller.abort();
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' });
  });

  it('reports a transport failure as code "network_error"', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    await expect(request('/api/thing')).rejects.toMatchObject({ status: 0, code: 'network_error' });
  });
});

describe('formatApiError on transport failures', () => {
  it('shows the readable timeout text instead of "Request failed (HTTP 0)"', async () => {
    vi.useFakeTimers();
    hangingFetch();
    const pending = request('/api/slow').catch((e: unknown) => e);
    await vi.advanceTimersByTimeAsync(DEFAULT_TIMEOUT_MS);
    expect(formatApiError(await pending)).toBe('No response from /api/slow after 30 s');
  });

  it('shows the reachability hint when the backend is down', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    const err = await request('/api/thing').catch((e: unknown) => e);
    expect(formatApiError(err)).toBe('Cannot reach the backend. Is it running on port 8000?');
  });
});

describe('errorMessage on transport failures', () => {
  it('shows the readable timeout text instead of "HTTP 0"', async () => {
    vi.useFakeTimers();
    hangingFetch();
    const pending = request('/api/report/c1').catch((e: unknown) => e);
    await vi.advanceTimersByTimeAsync(DEFAULT_TIMEOUT_MS);
    expect(errorMessage(await pending)).toBe('No response from /api/report/c1 after 30 s');
  });

  it('shows the reachability hint when the backend is down', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    const err = await request('/api/report/c1').catch((e: unknown) => e);
    expect(errorMessage(err)).toBe('Cannot reach the backend. Is it running on port 8000?');
  });
});

describe('isBackendUnreachable on transport failures', () => {
  it('is true for a network failure, so the run gate shows the reachability hint', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    const err = await request('/api/settings/estimate').catch((e: unknown) => e);
    expect(isBackendUnreachable(err)).toBe(true);
  });

  it('is false for a timeout: the backend answered the connection but not the request', async () => {
    vi.useFakeTimers();
    hangingFetch();
    const pending = request('/api/slow').catch((e: unknown) => e);
    await vi.advanceTimersByTimeAsync(DEFAULT_TIMEOUT_MS);
    expect(isBackendUnreachable(await pending)).toBe(false);
  });
});

describe('call sites that are slow by design', () => {
  it('testConnection allows 180 s', async () => {
    vi.useFakeTimers();
    hangingFetch();
    expect(await rejectsWithin(testConnection('worker'), 170_000, 181_000)).toEqual({ earlyReject: false, rejected: true });
  });

  it('askAgent allows 10 minutes', async () => {
    vi.useFakeTimers();
    hangingFetch();
    expect(await rejectsWithin(askAgent('quants_01', 'What drove your signal?'), 590_000, 601_000)).toEqual({
      earlyReject: false,
      rejected: true,
    });
  });

  it('putSettings sends a PUT with a JSON body and an abort signal', async () => {
    const mock = stubFetch([{ method: 'PUT', path: '/api/settings', body: { config: {}, mode: 'local' } }]);
    await putSettings({
      orchestrator: { provider: 'ollama', model: 'alphaswarm-orchestrator', base_url: null },
      worker: { provider: 'ollama', model: 'alphaswarm-worker', base_url: null },
    });
    const init = mock.mock.calls[0]?.[1];
    expect(init?.method).toBe('PUT');
    expect(init?.signal).toBeInstanceOf(AbortSignal);
    expect(JSON.parse(String(init?.body))).toMatchObject({ worker: { model: 'alphaswarm-worker' } });
  });
});
