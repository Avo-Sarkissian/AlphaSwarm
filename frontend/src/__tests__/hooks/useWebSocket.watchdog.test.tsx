// @vitest-environment happy-dom
// Frame watchdog: stale after FRAME_STALE_MS without a frame, socket replaced at
// FRAME_RECONNECT_MS, never before the first open, and recovery on the next frame.
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FRAME_RECONNECT_MS, FRAME_STALE_MS, useWebSocket } from '../../hooks/useWebSocket';
import { FakeWebSocket } from '../helpers/fakeWebSocket';

const FRAME = JSON.stringify({ phase: 'idle', agent_states: {} });

beforeEach(() => {
  vi.useFakeTimers();
  FakeWebSocket.reset();
  vi.stubGlobal('WebSocket', FakeWebSocket);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('useWebSocket frame watchdog', () => {
  it('stays open while frames arrive every 200 ms', () => {
    const { result } = renderHook(() => useWebSocket());
    act(() => FakeWebSocket.latest().open());
    for (let i = 0; i < 50; i += 1) {
      act(() => {
        vi.advanceTimersByTime(200);
        FakeWebSocket.latest().message(FRAME);
      });
    }
    expect(result.current.status).toBe('open');
    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it('marks a silent open socket stale, then replaces it, then recovers', () => {
    const { result } = renderHook(() => useWebSocket());
    act(() => {
      FakeWebSocket.latest().open();
      FakeWebSocket.latest().message(FRAME);
    });

    act(() => {
      vi.advanceTimersByTime(FRAME_STALE_MS + 500);
    });
    expect(result.current.status).toBe('stale');
    expect(result.current.lastFrame).not.toBeNull();
    expect(FakeWebSocket.instances).toHaveLength(1);

    act(() => {
      vi.advanceTimersByTime(FRAME_RECONNECT_MS - FRAME_STALE_MS);
    });
    expect(FakeWebSocket.instances[0]?.closeCalls).toBe(1);
    expect(FakeWebSocket.instances[0]?.onclose).toBeNull();
    expect(FakeWebSocket.instances).toHaveLength(2);
    expect(result.current).toMatchObject({ status: 'closed', connected: false });

    act(() => {
      FakeWebSocket.latest().open();
      FakeWebSocket.latest().message(FRAME);
    });
    expect(result.current).toMatchObject({ status: 'open', connected: true });
  });

  it('does not force a reconnect before the first open', () => {
    const { result } = renderHook(() => useWebSocket());
    act(() => {
      vi.advanceTimersByTime(FRAME_RECONNECT_MS * 2);
    });
    expect(result.current.status).toBe('connecting');
    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it('reports closed after the server drops the socket', () => {
    const { result } = renderHook(() => useWebSocket());
    act(() => FakeWebSocket.latest().open());
    act(() => FakeWebSocket.latest().drop());
    expect(result.current).toMatchObject({ status: 'closed', connected: false });
  });
});
