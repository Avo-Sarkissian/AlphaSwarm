import { afterEach, describe, expect, it, vi } from 'vitest';
import { DEMO_UNAVAILABLE_CODE, apiFetch, apiPost, installRequestOverride, request } from '../../api/client';
import { stubFetch } from '../helpers/fetchStub';

afterEach(() => {
  installRequestOverride(null);
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe('request override', () => {
  it('answers every call in the browser when installed', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    const seen: Array<[string, string | undefined]> = [];
    installRequestOverride(async (path, init) => {
      seen.push([path, init.method]);
      return { answered: path };
    });
    expect(await apiFetch('/api/health')).toEqual({ answered: '/api/health' });
    expect(await apiPost('/api/replay/round/2', {})).toEqual({ answered: '/api/replay/round/2' });
    expect(seen).toEqual([
      ['/api/health', undefined],
      ['/api/replay/round/2', 'POST'],
    ]);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('never touches the network in a demo build without an override', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    vi.stubEnv('VITE_DEMO', '1');
    await expect(request('/api/holdings')).rejects.toMatchObject({ status: 0, code: DEMO_UNAVAILABLE_CODE });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('uses fetch as before in a live build', async () => {
    stubFetch([{ path: '/api/health', body: { status: 'ok' } }]);
    await expect(apiFetch('/api/health')).resolves.toEqual({ status: 'ok' });
  });
});
