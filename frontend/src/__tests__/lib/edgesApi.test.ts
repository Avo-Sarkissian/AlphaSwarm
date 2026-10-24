// fetchEdges reads one round of citations; each citation is one edge of weight 1.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { fetchEdges } from '../../api/edges';
import { requestedUrls, stubFetch } from '../helpers/fetchStub';

const CYCLE = '00000000-0000-4000-8000-0000000000a1';
const URL_PATH = `/api/cycles/${CYCLE}/citations`;

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('fetchEdges', () => {
  it('reads one round of citations and keeps what each citer saw', async () => {
    const mock = stubFetch([
      {
        path: URL_PATH,
        body: {
          cycle_id: CYCLE,
          round_num: 2,
          citations: [{ source_id: 'quants_01', target_id: 'sell_side_01', cited_signal: 'sell' }],
        },
      },
    ]);
    const edges = await fetchEdges(CYCLE, 2);
    expect(requestedUrls(mock)).toEqual([`${URL_PATH}?round=2`]);
    expect(edges).toEqual([
      { source_id: 'quants_01', target_id: 'sell_side_01', weight: 1, cited_signal: 'sell' },
    ]);
  });

  it('drops an unknown cited signal', async () => {
    stubFetch([
      {
        path: URL_PATH,
        body: {
          cycle_id: CYCLE,
          round_num: 2,
          citations: [{ source_id: 'degens_02', target_id: 'macro_01', cited_signal: 'unknown' }],
        },
      },
    ]);
    expect(await fetchEdges(CYCLE, 2)).toEqual([
      { source_id: 'degens_02', target_id: 'macro_01', weight: 1 },
    ]);
  });

  it.each([404, 503])('treats HTTP %i as no edges', async (status) => {
    stubFetch([{ path: URL_PATH, status, body: { detail: { error: 'x', message: 'x' } } }]);
    await expect(fetchEdges(CYCLE, 2)).resolves.toEqual([]);
  });

  it('surfaces any other failure', async () => {
    stubFetch([
      { path: URL_PATH, status: 500, body: { detail: { error: 'internal_error', message: 'boom' } } },
    ]);
    await expect(fetchEdges(CYCLE, 2)).rejects.toThrow('boom');
  });
});
