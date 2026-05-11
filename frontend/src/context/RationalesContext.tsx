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
      // Dedupe by (agentId, round, text) so replay-mode frames (which re-emit
      // the FULL list every tick) don't oscillate, and a re-broadcast of a
      // drained entry doesn't double-count.
      const seen = new Set(prev.map((r) => `${r.agentId}|${r.round}|${r.text}`));
      const additions = frame.rationales.filter(
        (r) => !seen.has(`${r.agentId}|${r.round}|${r.text}`),
      );
      if (additions.length === 0) return prev;
      const next = [...prev, ...additions];
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
