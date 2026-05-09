import { createContext, useContext, useMemo } from 'react';
import type { ReactNode } from 'react';
import type { BracketSummaryView, StateFrame } from '../types';

export interface BracketCtxValue {
  brackets: BracketSummaryView[];
}

const Ctx = createContext<BracketCtxValue | null>(null);

export function BracketProvider({
  frame,
  children,
}: {
  frame: StateFrame;
  children: ReactNode;
}) {
  const value = useMemo<BracketCtxValue>(
    () => ({ brackets: frame.bracketSummaries }),
    [frame.bracketSummaries],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useBrackets(): BracketCtxValue {
  const v = useContext(Ctx);
  if (!v) throw new Error('useBrackets outside provider');
  return v;
}
