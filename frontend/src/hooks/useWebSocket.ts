// Frames from the page's data source (the backend WebSocket, or the static
// demo), adapted into the view StateFrame. Each new frame reuses the unchanged
// parts of the previous one (adapter structural sharing).
import { useEffect, useRef, useState } from 'react';
import { adaptSnapshot } from '../adapter/frame';
import { getDataSource, type ConnectionStatus, type DataSource } from '../data-source';
import type { StateFrame } from '../types';

export type { ConnectionStatus } from '../data-source';
export { FRAME_RECONNECT_MS, FRAME_STALE_MS } from '../data-source/live';

export interface UseWebSocketResult {
  connected: boolean;
  status: ConnectionStatus;
  lastFrame: StateFrame | null;
}

export function useWebSocket(source: DataSource = getDataSource()): UseWebSocketResult {
  const [status, setStatus] = useState<ConnectionStatus>('connecting');
  const [lastFrame, setLastFrame] = useState<StateFrame | null>(null);
  const previous = useRef<StateFrame | null>(null);

  useEffect(() => {
    previous.current = null;
    return source.subscribeFrames((raw) => {
      let next: StateFrame;
      try {
        next = adaptSnapshot(raw, previous.current);
      } catch {
        return; // a frame the adapter rejects: wait for the next one
      }
      previous.current = next;
      setLastFrame(next);
    }, setStatus);
  }, [source]);

  return { connected: status === 'open' || status === 'stale', status, lastFrame };
}
