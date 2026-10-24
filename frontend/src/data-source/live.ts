// Live data source: frames from the backend WebSocket, API answers over fetch
// (docs/DECISIONS.md#adr-ws-broadcaster). Retries forever with backoff (1 s,
// 2 s, 4 s, then 5 s); a watchdog marks the channel stale after FRAME_STALE_MS
// without a frame and replaces the socket at FRAME_RECONNECT_MS. The watchdog
// only watches a socket whose onopen fired; one still connecting is left to the
// browser's connect timeout and the onclose retry. Byte-identical frames (the
// broadcaster's keepalive) feed the watchdog but are not passed on.
import { request, type RequestOptions } from '../api/client';
import type { ConnectionStatus, DataSource } from './types';

export const FRAME_STALE_MS = 2000;
export const FRAME_RECONNECT_MS = 5000;
const WATCHDOG_TICK_MS = 500;
const BACKOFF_MS = [1000, 2000, 4000, 5000];

export function createLiveDataSource(wsPath = '/ws/state'): DataSource {
  return {
    kind: 'live',
    readOnly: false,
    subscribeFrames: (onFrame, onStatus) => subscribe(wsPath, onFrame, onStatus),
    fetchJson: <T>(path: string, init?: RequestOptions) => request<T>(path, init),
  };
}

function subscribe(
  path: string,
  onFrame: (raw: unknown) => void,
  onStatus: (s: ConnectionStatus) => void,
): () => void {
  let cancelled = false;
  let socket: WebSocket | null = null;
  let openSocket: WebSocket | null = null;
  let retry = 0;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let lastFrameAt = 0;
  let lastData: string | null = null;

  const detach = (s: WebSocket) => {
    s.onmessage = null;
    s.onopen = null;
    s.onerror = null;
    s.onclose = null;
  };

  const scheduleRetry = () => {
    if (cancelled) return;
    const delay = BACKOFF_MS[Math.min(retry, BACKOFF_MS.length - 1)] ?? 5000;
    retry += 1;
    timer = setTimeout(connect, delay);
  };

  function connect(): void {
    if (cancelled) return;
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    let s: WebSocket;
    try {
      s = new window.WebSocket(`${proto}//${window.location.host}${path}`);
    } catch {
      scheduleRetry();
      return;
    }
    socket = s;
    s.onopen = () => {
      if (cancelled) return;
      openSocket = s;
      lastFrameAt = Date.now();
      retry = 0;
      onStatus('open');
    };
    s.onmessage = (ev: MessageEvent) => {
      if (cancelled) return;
      lastFrameAt = Date.now();
      onStatus('open');
      const data = String(ev.data);
      if (data === lastData) return;
      let raw: unknown;
      try {
        raw = JSON.parse(data);
      } catch {
        return; // malformed frame: wait for the next one
      }
      lastData = data;
      onFrame(raw);
    };
    s.onerror = () => {
      // onclose follows; the retry happens there
    };
    s.onclose = () => {
      if (cancelled) return;
      detach(s);
      if (socket === s) socket = null;
      if (openSocket === s) openSocket = null;
      onStatus('closed');
      scheduleRetry();
    };
  }

  const watchdog = setInterval(() => {
    const s = socket;
    if (cancelled || s === null || openSocket !== s) return;
    const silentMs = Date.now() - lastFrameAt;
    if (silentMs >= FRAME_RECONNECT_MS) {
      detach(s);
      socket = null;
      openSocket = null;
      try {
        s.close();
      } catch {
        // already closing
      }
      onStatus('closed');
      connect();
    } else if (silentMs >= FRAME_STALE_MS) {
      onStatus('stale');
    }
  }, WATCHDOG_TICK_MS);

  connect();

  return () => {
    cancelled = true;
    clearInterval(watchdog);
    if (timer) clearTimeout(timer);
    const s = socket;
    if (s) {
      detach(s);
      try {
        s.close();
      } catch {
        // ignore
      }
    }
  };
}
