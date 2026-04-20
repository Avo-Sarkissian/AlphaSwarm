import { createContext, useContext, useMemo } from 'react';
import type { ReactNode } from 'react';
import type { StateFrame } from '../types';

export interface ConnectionCtxValue {
  connected: boolean;
  reconnectFailed: boolean;
  lastFrame: StateFrame | null;
}

const Ctx = createContext<ConnectionCtxValue | null>(null);

export function ConnectionProvider({
  connected,
  reconnectFailed,
  lastFrame,
  children,
}: {
  connected: boolean;
  reconnectFailed: boolean;
  lastFrame: StateFrame | null;
  children: ReactNode;
}) {
  const value = useMemo<ConnectionCtxValue>(
    () => ({ connected, reconnectFailed, lastFrame }),
    [connected, reconnectFailed, lastFrame],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useConnection(): ConnectionCtxValue {
  const v = useContext(Ctx);
  if (!v) throw new Error('useConnection outside provider');
  return v;
}
