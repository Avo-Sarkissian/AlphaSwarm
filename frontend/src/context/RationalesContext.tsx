import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import type { RationaleView, StateFrame } from '../types';

const MAX_RATIONALES = 50;

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
  const [accumulated, setAccumulated] = useState<RationaleView[]>([]);

  useEffect(() => {
    if (frame.phase === 'idle') {
      setAccumulated((prev) => (prev.length === 0 ? prev : []));
      return;
    }
    if (frame.rationales.length === 0) return;
    setAccumulated((prev) => {
      const next = [...prev, ...frame.rationales];
      return next.length > MAX_RATIONALES ? next.slice(-MAX_RATIONALES) : next;
    });
  }, [frame.rationales, frame.phase]);

  const value = useMemo<RationalesCtxValue>(
    () => ({ rationales: accumulated }),
    [accumulated],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useRationales(): RationalesCtxValue {
  const v = useContext(Ctx);
  if (!v) throw new Error('useRationales outside provider');
  return v;
}
