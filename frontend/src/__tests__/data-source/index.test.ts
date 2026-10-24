// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { apiFetch } from '../../api/client';
import { getDataSource, resetDataSourceForTests } from '../../data-source';
import fixture from '../fixtures/cycle_export.json';
import { requestedUrls, stubFetch } from '../helpers/fetchStub';

afterEach(() => {
  resetDataSourceForTests();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe('getDataSource', () => {
  it('uses the live backend by default', () => {
    expect([getDataSource().kind, getDataSource().readOnly]).toEqual(['live', false]);
    expect(getDataSource()).toBe(getDataSource());
  });

  it('replays the recorded cycle in a demo build and answers API calls in the browser', async () => {
    vi.stubEnv('VITE_DEMO', '1');
    const mock = stubFetch([
      { path: '/demo/index.json', body: { cycle_id: 'demo-cycle' } },
      { path: '/demo/demo-cycle.json', body: fixture },
    ]);
    const source = getDataSource();
    expect([source.kind, source.readOnly]).toEqual(['demo', true]);
    const health = await apiFetch<{ status: string }>('/api/health');
    expect(health.status).toBe('ok');
    expect(requestedUrls(mock)).toEqual(['/demo/index.json', '/demo/demo-cycle.json']);
  });
});
