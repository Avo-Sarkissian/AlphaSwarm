import { createContext, useContext, useMemo } from 'react';
import type { ReactNode } from 'react';
import type { StateFrame, TelemetrySlice } from '../types';

export interface TelemetryCtxValue {
  phase: string;
  running: boolean;
  telemetry: TelemetrySlice;
  ts: number;
}

const Ctx = createContext<TelemetryCtxValue | null>(null);

export function TelemetryProvider({
  frame,
  children,
}: {
  frame: StateFrame;
  children: ReactNode;
}) {
  const value = useMemo<TelemetryCtxValue>(
    () => ({
      phase: frame.phase,
      running: frame.running,
      telemetry: frame.telemetry,
      ts: frame.telemetry.ts,
    }),
    [frame.phase, frame.running, frame.telemetry],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useTelemetry(): TelemetryCtxValue {
  const v = useContext(Ctx);
  if (!v) throw new Error('useTelemetry outside provider');
  return v;
}
