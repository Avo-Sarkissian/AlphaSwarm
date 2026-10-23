// @vitest-environment happy-dom
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FRAME_STALE_MS, useWebSocket } from '../../hooks/useWebSocket';
import liveFrame from '../fixtures/ws_snapshot.json';
import { FakeWebSocket } from '../helpers/fakeWebSocket';

const LIVE = JSON.stringify(liveFrame);

function withMemory(percent: number): string {
  const raw = structuredClone(liveFrame) as unknown as { governor_metrics: { memory_percent: number } };
  raw.governor_metrics.memory_percent = percent;
  return JSON.stringify(raw);
}

function openSocket() {
  const hook = renderHook(() => useWebSocket());
  act(() => FakeWebSocket.latest().open());
  return hook;
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date('2026-10-05T12:00:00Z'));
  FakeWebSocket.reset();
  vi.stubGlobal('WebSocket', FakeWebSocket);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('useWebSocket frame sharing', () => {
  it('keeps the same frame object for a byte-identical frame', () => {
    const { result } = openSocket();
    act(() => FakeWebSocket.latest().message(LIVE));
    const first = result.current.lastFrame;
    expect(first).not.toBeNull();
    act(() => FakeWebSocket.latest().message(LIVE));
    expect(result.current.lastFrame).toBe(first);
  });

  it('identical keepalive frames keep the channel open', () => {
    const { result } = openSocket();
    for (let i = 0; i < 10; i += 1) {
      act(() => {
        vi.advanceTimersByTime(1000);
        FakeWebSocket.latest().message(LIVE);
      });
    }
    expect(result.current.status).toBe('open');
    act(() => {
      vi.advanceTimersByTime(FRAME_STALE_MS + 500);
    });
    expect(result.current.status).toBe('stale');
  });

  it('shares unchanged slices when only telemetry changed', () => {
    const { result } = openSocket();
    act(() => FakeWebSocket.latest().message(withMemory(41)));
    const first = result.current.lastFrame;
    act(() => FakeWebSocket.latest().message(withMemory(42)));
    const second = result.current.lastFrame;
    expect(second).not.toBe(first);
    expect(second?.telemetry).not.toBe(first?.telemetry);
    expect(second?.agents).toBe(first?.agents);
    expect(second?.rationales).toBe(first?.rationales);
  });

  it('does not expose lastRaw', () => {
    const { result } = openSocket();
    expect(Object.keys(result.current).sort()).toEqual(['connected', 'lastFrame', 'status']);
  });
});
