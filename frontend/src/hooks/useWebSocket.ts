import { useEffect, useRef, useState } from 'react';
import { adaptSnapshot } from '../adapter/frame';
import type { StateFrame } from '../types';

// Connect to /ws/state. Parses JSON in try/catch; 3-retry exponential backoff
// after initial (1s, 2s, 4s = 4 total attempts) before reconnectFailed=true.
export interface UseWebSocketResult {
  connected: boolean;
  lastFrame: StateFrame | null;
  lastRaw: unknown;
  reconnectFailed: boolean;
}

const MAX_RETRIES = 3;
const BACKOFF_MS = [1000, 2000, 4000];

export function useWebSocket(path: string = '/ws/state'): UseWebSocketResult {
  const [connected, setConnected] = useState<boolean>(false);
  const [lastFrame, setLastFrame] = useState<StateFrame | null>(null);
  const [lastRaw, setLastRaw] = useState<unknown>(null);
  const [reconnectFailed, setReconnectFailed] = useState<boolean>(false);

  const wsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef<number>(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const cancelledRef = useRef<boolean>(false);

  useEffect(() => {
    cancelledRef.current = false;

    const connect = () => {
      if (cancelledRef.current) return;

      // NR-1 FIX: connect to FastAPI directly (absolute origin), NOT to whatever
      // host happens to be serving the SPA (e.g. Vite dev server on :5173).
      // Default 'ws://localhost:8000' keeps local-first dev working without env setup.
      const base = (import.meta.env.VITE_BACKEND_WS as string | undefined) || 'ws://localhost:8000';
      const url = `${base}${path}`;
      let ws: WebSocket;
      try {
        ws = new window.WebSocket(url);
      } catch {
        scheduleRetry();
        return;
      }
      wsRef.current = ws;

      ws.onopen = () => {
        if (cancelledRef.current) return;
        setConnected(true);
        setReconnectFailed(false);
        retryRef.current = 0;
      };

      ws.onmessage = (ev: MessageEvent) => {
        if (cancelledRef.current) return;
        try {
          const raw = JSON.parse(String(ev.data));
          setLastRaw(raw);
          setLastFrame(adaptSnapshot(raw));
        } catch {
          // swallow: malformed frame, wait for next
        }
      };

      ws.onerror = () => {
        // onclose will follow; handle retry there
      };

      ws.onclose = () => {
        if (cancelledRef.current) return;
        setConnected(false);
        ws.onmessage = null;
        ws.onopen = null;
        ws.onerror = null;
        ws.onclose = null;
        scheduleRetry();
      };
    };

    const scheduleRetry = () => {
      if (cancelledRef.current) return;
      if (retryRef.current >= MAX_RETRIES) {
        setReconnectFailed(true);
        return;
      }
      const delay = BACKOFF_MS[retryRef.current] ?? 4000;
      retryRef.current += 1;
      timerRef.current = setTimeout(connect, delay);
    };

    connect();

    return () => {
      cancelledRef.current = true;
      if (timerRef.current) clearTimeout(timerRef.current);
      const ws = wsRef.current;
      if (ws) {
        ws.onmessage = null;
        ws.onopen = null;
        ws.onerror = null;
        ws.onclose = null;
        try {
          ws.close();
        } catch {
          // ignore
        }
      }
    };
  }, [path]);

  return { connected, lastFrame, lastRaw, reconnectFailed };
}
