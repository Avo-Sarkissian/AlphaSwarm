// @vitest-environment happy-dom
import { renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { useSampleHistory } from '../../hooks/useSampleHistory';

describe('useSampleHistory', () => {
  it('records one sample per frame and keeps the newest N', () => {
    const { result, rerender } = renderHook(({ v, k }: { v: number; k: number }) => useSampleHistory(v, k, 3), {
      initialProps: { v: 1, k: 1 },
    });
    rerender({ v: 2, k: 2 });
    rerender({ v: 3, k: 3 });
    rerender({ v: 4, k: 4 });
    expect(result.current).toEqual([2, 3, 4]);

    rerender({ v: 4, k: 4 });
    expect(result.current).toEqual([2, 3, 4]);
  });
});
