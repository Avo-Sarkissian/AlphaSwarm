// Frame identity and versioning: which cycle is on screen, in which mode, at
// which round, and how far its influence edges have been written. Every value is
// a primitive, so consumers re-render only when one of them changes, not on
// every 5 Hz frame.
import { createContext, useContext, useMemo } from 'react';
import type { ReactNode } from 'react';
import type { FrameMode, StateFrame } from '../types';

export interface FrameMeta {
  mode: FrameMode;
  phase: string;
  cycleId: string | null;
  numRounds: number;
  roundNum: number | null;
  edgesVersion: number;
  schemaVersion: number;
}

const Ctx = createContext<FrameMeta | null>(null);

export function FrameMetaProvider({
  frame,
  children,
}: {
  frame: StateFrame;
  children: ReactNode;
}) {
  const { mode, phase, cycleId, numRounds, roundNum, edgesVersion, schemaVersion } = frame;
  const value = useMemo<FrameMeta>(
    () => ({ mode, phase, cycleId, numRounds, roundNum, edgesVersion, schemaVersion }),
    [mode, phase, cycleId, numRounds, roundNum, edgesVersion, schemaVersion],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useFrameMeta(): FrameMeta {
  const v = useContext(Ctx);
  if (!v) throw new Error('useFrameMeta outside provider');
  return v;
}
