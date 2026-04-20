import { createContext, useContext, useMemo } from 'react';
import type { ReactNode } from 'react';
import type { RationaleView, StateFrame } from '../types';

export interface RationalesCtxValue {
  rationales: RationaleView[];
}

const Ctx = createContext<RationalesCtxValue | null>(null);

export function RationalesProvider({
  frame,
  children,
}: {
  frame: StateFrame;
  children: ReactNode;
}) {
  const value = useMemo<RationalesCtxValue>(
    () => ({ rationales: frame.rationales }),
    [frame.rationales],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useRationales(): RationalesCtxValue {
  const v = useContext(Ctx);
  if (!v) throw new Error('useRationales outside provider');
  return v;
}
