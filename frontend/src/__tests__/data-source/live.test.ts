// @vitest-environment happy-dom
// The live data source owns the socket loop that used to live in useWebSocket.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ConnectionStatus } from '../../data-source';
import { FRAME_RECONNECT_MS, FRAME_STALE_MS, createLiveDataSource } from '../../data-source/live';
import { FakeWebSocket } from '../helpers/fakeWebSocket';
import { stubFetch } from '../helpers/fetchStub';

function subscribe() {
  const frames: unknown[] = [];
  const statuses: ConnectionStatus[] = [];
  const stop = createLiveDataSource().subscribeFrames((raw) => frames.push(raw), (s) => statuses.push(s));
  return { frames, statuses, stop };
}

beforeEach(() => {
  vi.useFakeTimers();
  FakeWebSocket.reset();
  vi.stubGlobal('WebSocket', FakeWebSocket);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('live data source', () => {
  it('connects to /ws/state and passes parsed frames on', () => {
    const { frames, statuses, stop } = subscribe();
    const socket = FakeWebSocket.latest();
    expect(socket.url).toBe(`ws://${window.location.host}/ws/state`);
    socket.open();
    socket.message('{"round_num": 1}');
    socket.message('not json');
    expect(frames).toEqual([{ round_num: 1 }]);
    expect(statuses.at(-1)).toBe('open');
    stop();
  });

  it('skips identical frames but stays open while they keep coming', () => {
    const { frames, statuses, stop } = subscribe();
    FakeWebSocket.latest().open();
    for (let second = 0; second < 4; second += 1) {
      FakeWebSocket.latest().message('{"round_num": 2}');
      vi.advanceTimersByTime(1000);
    }
    expect(frames).toHaveLength(1);
    expect(statuses).not.toContain('stale');
    stop();
  });

  it('marks a silent channel stale, then replaces the socket', () => {
    const { statuses, stop } = subscribe();
    FakeWebSocket.latest().open();
    vi.advanceTimersByTime(FRAME_STALE_MS + 500);
    expect(statuses.at(-1)).toBe('stale');
    vi.advanceTimersByTime(FRAME_RECONNECT_MS);
    expect(FakeWebSocket.instances).toHaveLength(2);
    expect(FakeWebSocket.instances[0]?.closeCalls).toBe(1);
    stop();
  });

  it('never replaces a socket that has not opened yet', () => {
    const { statuses, stop } = subscribe();
    vi.advanceTimersByTime(FRAME_RECONNECT_MS * 2);
    expect(statuses).toEqual([]);
    expect(FakeWebSocket.instances).toHaveLength(1);
    stop();
  });

  it('retries after a close with backoff', () => {
    const { statuses, stop } = subscribe();
    FakeWebSocket.latest().drop();
    expect(statuses.at(-1)).toBe('closed');
    vi.advanceTimersByTime(999);
    expect(FakeWebSocket.instances).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(FakeWebSocket.instances).toHaveLength(2);
    stop();
  });

  it('stops retrying once unsubscribed', () => {
    const { stop } = subscribe();
    const first = FakeWebSocket.latest();
    stop();
    first.drop();
    vi.advanceTimersByTime(10_000);
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(first.closeCalls).toBe(1);
  });

  it('fetches JSON through request()', async () => {
    vi.useRealTimers();
    stubFetch([{ path: '/api/health', body: { status: 'ok' } }]);
    await expect(createLiveDataSource().fetchJson<{ status: string }>('/api/health')).resolves.toEqual({ status: 'ok' });
  });
});
