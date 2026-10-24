import { afterEach, describe, expect, it, vi } from 'vitest';
import { replaySeek } from '../../api/replay';
import { stubFetch } from '../helpers/fetchStub';

afterEach(() => vi.unstubAllGlobals());

describe('replaySeek', () => {
  it('POSTs the round', async () => {
    const mock = stubFetch([{ method: 'POST', path: '/api/replay/round/3', body: { status: 'ok', round_num: 3 } }]);
    expect(await replaySeek(3)).toEqual({ status: 'ok', round_num: 3 });
    expect(mock.mock.calls[0]?.[1]?.method).toBe('POST');
  });
});
