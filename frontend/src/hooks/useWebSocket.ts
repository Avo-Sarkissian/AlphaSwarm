import { useEffect, useRef, useState } from 'react';
import { adaptSnapshot } from '../adapter/frame';
import type { StateFrame } from '../types';

/**
 * connecting: no socket has opened yet.  open: frames are arriving.
 * stale: the socket is open but no frame for FRAME_STALE_MS.
 * closed: the socket closed or was replaced; reconnecting.
 */
export type ConnectionStatus = 'connecting' | 'open' | 'stale' | 'closed';

/** The broadcaster sends ~5 frames/s (docs/DECISIONS.md#adr-ws-broadcaster). */
export const FRAME_STALE_MS = 2000;
export const FRAME_RECONNECT_MS = 5000;
const WATCHDOG_TICK_MS = 500;
const BACKOFF_MS = [1000, 2000, 4000, 5000];

export interface UseWebSocketResult {
  connected: boolean;
  status: ConnectionStatus;
  lastFrame: StateFrame | null;
}

// Connect to /ws/state and retry forever with backoff (1 s, 2 s, 4 s, then 5 s).
// A watchdog marks the channel stale after FRAME_STALE_MS without a frame and
// replaces the socket at FRAME_RECONNECT_MS, so a half-dead socket (sleep/wake,
// proxy stall) cannot freeze the dashboard on old data. The watchdog only
// watches a socket that has opened; a socket still connecting is left to the
// browser's own connect timeout and the onclose retry.
export function useWebSocket(path: string = '/ws/state'): UseWebSocketResult {
  const [connected, setConnected] = useState<boolean>(false);
  const [status, setStatus] = useState<ConnectionStatus>('connecting');
  const [lastFrame, setLastFrame] = useState<StateFrame | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const openWsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef<number>(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const cancelledRef = useRef<boolean>(false);
  const lastFrameAtRef = useRef<number>(0);
  const lastDataRef = useRef<string | null>(null);

  useEffect(() => {
    cancelledRef.current = false;

    const detach = (ws: WebSocket) => {
      ws.onmessage = null;
      ws.onopen = null;
      ws.onerror = null;
      ws.onclose = null;
    };

    const scheduleRetry = () => {
      if (cancelledRef.current) return;
      const delay = BACKOFF_MS[Math.min(retryRef.current, BACKOFF_MS.length - 1)];
      retryRef.current += 1;
      timerRef.current = setTimeout(connect, delay);
    };

    const connect = () => {
      if (cancelledRef.current) return;
      const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const url = `${proto}//${window.location.host}${path}`;
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
        openWsRef.current = ws;
        lastFrameAtRef.current = Date.now();
        setConnected(true);
        setStatus('open');
        retryRef.current = 0;
      };

      ws.onmessage = (ev: MessageEvent) => {
        if (cancelledRef.current) return;
        lastFrameAtRef.current = Date.now();
        setStatus('open');
        const data = String(ev.data);
        // A byte-identical frame (a keepalive with nothing new) still feeds the
        // watchdog above but costs no parse and no render
        // (docs/DECISIONS.md#adr-ws-broadcaster).
        if (data === lastDataRef.current) return;
        try {
          const raw: unknown = JSON.parse(data);
          lastDataRef.current = data;
          setLastFrame((prev) => adaptSnapshot(raw, prev));
        } catch {
          // malformed frame: wait for the next one
        }
      };

      ws.onerror = () => {
        // onclose follows; the retry happens there
      };

      ws.onclose = () => {
        if (cancelledRef.current) return;
        detach(ws);
        if (wsRef.current === ws) wsRef.current = null;
        if (openWsRef.current === ws) openWsRef.current = null;
        setConnected(false);
        setStatus('closed');
        scheduleRetry();
      };
    };

    const watchdog = setInterval(() => {
      const ws = wsRef.current;
      if (cancelledRef.current || ws === null || openWsRef.current !== ws) return;
      const silentMs = Date.now() - lastFrameAtRef.current;
      if (silentMs >= FRAME_RECONNECT_MS) {
        detach(ws);
        wsRef.current = null;
        openWsRef.current = null;
        try {
          ws.close();
        } catch {
          // already closing
        }
        setConnected(false);
        setStatus('closed');
        connect();
      } else if (silentMs >= FRAME_STALE_MS) {
        setStatus('stale');
      }
    }, WATCHDOG_TICK_MS);

    connect();

    return () => {
      cancelledRef.current = true;
      clearInterval(watchdog);
      if (timerRef.current) clearTimeout(timerRef.current);
      const ws = wsRef.current;
      if (ws) {
        detach(ws);
        try {
          ws.close();
        } catch {
          // ignore
        }
      }
    };
  }, [path]);

  return { connected, status, lastFrame };
}
