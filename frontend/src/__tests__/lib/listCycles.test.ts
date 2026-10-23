import { afterEach, describe, expect, it, vi } from 'vitest';
import { listCycles } from '../../api/replay';
import { requestedUrls, stubFetch } from '../helpers/fetchStub';

afterEach(() => vi.unstubAllGlobals());

describe('listCycles', () => {
  it('URL-encodes the cursor and maps next_before', async () => {
    const mock = stubFetch([
      { path: '/api/replay/cycles', body: { cycles: [], next_before: '2026-10-02T00:00:00.000000000+00:00' } },
    ]);
    const page = await listCycles({ before: '2026-10-03T12:00:00.123456789+00:00' });
    expect(requestedUrls(mock)).toEqual([
      '/api/replay/cycles?limit=20&before=2026-10-03T12%3A00%3A00.123456789%2B00%3A00',
    ]);
    expect(page).toEqual({ cycles: [], nextBefore: '2026-10-02T00:00:00.000000000+00:00' });
  });
});
