import { useCallback, useEffect, useRef, useState } from 'react';
import { CYCLE_PAGE_SIZE, listCycles, type CycleItem } from '../api/replay';
import { formatApiError } from '../lib/apiError';
import { mergeCycles } from '../lib/cycles';

export interface CyclePagesState {
  cycles: CycleItem[] | null; // null while the first page loads
  error: string | null;
  hasMore: boolean;
  loadingMore: boolean;
  loadMore: () => void;
}

/** Complete cycles, newest first, fetched page by page (shared by History and the replay picker). */
export function useCyclePages(pageSize: number = CYCLE_PAGE_SIZE): CyclePagesState {
  const [cycles, setCycles] = useState<CycleItem[] | null>(null);
  const [nextBefore, setNextBefore] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const mounted = useRef(true);
  const inFlight = useRef(false);

  useEffect(() => {
    mounted.current = true;
    listCycles({ limit: pageSize })
      .then((page) => {
        if (!mounted.current) return;
        setCycles(page.cycles);
        setNextBefore(page.nextBefore);
      })
      .catch((e: unknown) => {
        if (!mounted.current) return;
        setError(formatApiError(e));
        setCycles([]);
      });
    return () => {
      mounted.current = false;
    };
  }, [pageSize]);

  const loadMore = useCallback(() => {
    if (nextBefore === null || inFlight.current) return;
    inFlight.current = true;
    setLoadingMore(true);
    listCycles({ limit: pageSize, before: nextBefore })
      .then((page) => {
        if (!mounted.current) return;
        setCycles((prev) => mergeCycles(prev ?? [], page.cycles));
        setNextBefore(page.nextBefore);
        setError(null);
      })
      .catch((e: unknown) => {
        if (mounted.current) setError(formatApiError(e));
      })
      .finally(() => {
        inFlight.current = false;
        if (mounted.current) setLoadingMore(false);
      });
  }, [nextBefore, pageSize]);

  return { cycles, error, hasMore: nextBefore !== null, loadingMore, loadMore };
}
