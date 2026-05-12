// Rationale feed context — backend now ships the full sliding-window
// deque (maxlen=50) on every WS frame as `rationale_entries` (see ITEM 4
// of quick task 260512-jqn / state.py `_rationale_window`). The frontend
// no longer needs the accumulator + dedup it used to keep alive between
// drain ticks (commits 643f93a, 6dd2665 — now redundant).
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
    () => ({ rationales: frame.rationales ?? [] }),
    [frame.rationales],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useRationales(): RationalesCtxValue {
  const v = useContext(Ctx);
  if (!v) throw new Error('useRationales outside provider');
  return v;
}
