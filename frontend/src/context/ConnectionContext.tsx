import { createContext, useContext, useMemo } from 'react';
import type { ReactNode } from 'react';
import type { ConnectionStatus } from '../hooks/useWebSocket';
import type { StateFrame } from '../types';

export interface ConnectionCtxValue {
  connected: boolean;
  status: ConnectionStatus;
  lastFrame: StateFrame | null;
}

const Ctx = createContext<ConnectionCtxValue | null>(null);

export function ConnectionProvider({
  connected,
  status,
  lastFrame,
  children,
}: {
  connected: boolean;
  status: ConnectionStatus;
  lastFrame: StateFrame | null;
  children: ReactNode;
}) {
  const value = useMemo<ConnectionCtxValue>(
    () => ({ connected, status, lastFrame }),
    [connected, status, lastFrame],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useConnection(): ConnectionCtxValue {
  const v = useContext(Ctx);
  if (!v) throw new Error('useConnection outside provider');
  return v;
}
