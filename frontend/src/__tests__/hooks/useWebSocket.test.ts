// @vitest-environment happy-dom
// useWebSocket reconnect policy: retry after 1 s, 2 s, 4 s, then every 5 s, forever;
// the delay resets after a successful open; unmount stops every timer and socket.
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useWebSocket } from '../../hooks/useWebSocket';
import { FakeWebSocket } from '../helpers/fakeWebSocket';

beforeEach(() => {
  vi.useFakeTimers();
  FakeWebSocket.reset();
  vi.stubGlobal('WebSocket', FakeWebSocket);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function advance(ms: number): void {
  act(() => {
    vi.advanceTimersByTime(ms);
  });
}

describe('useWebSocket — connection', () => {
  it('connects to /ws/state on the page host', () => {
    renderHook(() => useWebSocket());
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(FakeWebSocket.latest().url).toBe(`ws://${window.location.host}/ws/state`);
  });

  it('reports connected after open and adapts each frame', () => {
    const { result } = renderHook(() => useWebSocket());
    act(() => FakeWebSocket.latest().open());
    expect(result.current.connected).toBe(true);
    act(() => FakeWebSocket.latest().message(JSON.stringify({ phase: 'round_2', round_num: 2 })));
    expect(result.current.lastFrame?.phase).toBe('round_2');
  });

  it('ignores a malformed frame and keeps the previous one', () => {
    const { result } = renderHook(() => useWebSocket());
    act(() => FakeWebSocket.latest().open());
    act(() => FakeWebSocket.latest().message(JSON.stringify({ phase: 'round_1' })));
    act(() => FakeWebSocket.latest().message('{not json'));
    expect(result.current.lastFrame?.phase).toBe('round_1');
  });
});

describe('useWebSocket — reconnect backoff', () => {
  it('retries after 1 s, 2 s, 4 s, then every 5 s', () => {
    renderHook(() => useWebSocket());
    for (const [i, delay] of [1000, 2000, 4000, 5000, 5000].entries()) {
      act(() => FakeWebSocket.latest().drop());
      advance(delay - 1);
      expect(FakeWebSocket.instances).toHaveLength(i + 1);
      advance(1);
      expect(FakeWebSocket.instances).toHaveLength(i + 2);
    }
  });

  it('reports disconnected while reconnecting and never gives up', () => {
    const { result } = renderHook(() => useWebSocket());
    act(() => FakeWebSocket.latest().open());
    act(() => FakeWebSocket.latest().drop());
    expect(result.current.connected).toBe(false);
    expect(result.current.status).toBe('closed');
  });

  it('resets the delay to 1 s after a successful open', () => {
    renderHook(() => useWebSocket());
    act(() => FakeWebSocket.latest().drop());
    advance(1000);
    act(() => FakeWebSocket.latest().drop());
    advance(2000);
    act(() => FakeWebSocket.latest().open());
    act(() => FakeWebSocket.latest().drop());
    advance(999);
    expect(FakeWebSocket.instances).toHaveLength(3);
    advance(1);
    expect(FakeWebSocket.instances).toHaveLength(4);
  });

  it('keeps the last frame while disconnected', () => {
    const { result } = renderHook(() => useWebSocket());
    act(() => FakeWebSocket.latest().open());
    act(() => FakeWebSocket.latest().message(JSON.stringify({ phase: 'round_3' })));
    act(() => FakeWebSocket.latest().drop());
    expect(result.current.lastFrame?.phase).toBe('round_3');
  });

  it('retries when the WebSocket constructor throws', () => {
    FakeWebSocket.throwOnConstruct = true;
    renderHook(() => useWebSocket());
    expect(FakeWebSocket.instances).toHaveLength(0);
    FakeWebSocket.throwOnConstruct = false;
    advance(1000);
    expect(FakeWebSocket.instances).toHaveLength(1);
  });
});

describe('useWebSocket — unmount', () => {
  it('closes the socket and never reconnects', () => {
    const { unmount } = renderHook(() => useWebSocket());
    const ws = FakeWebSocket.latest();
    act(() => ws.open());
    unmount();
    expect(ws.closeCalls).toBe(1);
    expect(ws.onclose).toBeNull();
    advance(60_000);
    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it('cancels a pending retry', () => {
    const { unmount } = renderHook(() => useWebSocket());
    act(() => FakeWebSocket.latest().drop());
    unmount();
    advance(60_000);
    expect(FakeWebSocket.instances).toHaveLength(1);
  });
});
