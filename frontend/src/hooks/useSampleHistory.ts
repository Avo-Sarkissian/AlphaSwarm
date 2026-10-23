import { useEffect, useRef, useState } from 'react';
import { RingBuffer } from '../lib/ringBuffer';

/** Last `capacity` values, one sample whenever `value` or `sampleKey` (e.g. the frame ts) changes. */
export function useSampleHistory(value: number, sampleKey: unknown, capacity = 30): number[] {
  const bufRef = useRef<RingBuffer<number> | null>(null);
  if (bufRef.current === null) bufRef.current = new RingBuffer<number>(capacity);
  const [samples, setSamples] = useState<number[]>([]);

  useEffect(() => {
    const buf = bufRef.current;
    if (buf === null) return;
    buf.push(value);
    setSamples(buf.toArray());
  }, [value, sampleKey]);

  return samples;
}
