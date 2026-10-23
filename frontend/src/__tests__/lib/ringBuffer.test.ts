import { describe, expect, it } from 'vitest';
import { RingBuffer } from '../../lib/ringBuffer';

describe('RingBuffer', () => {
  it('keeps insertion order up to capacity', () => {
    const buf = new RingBuffer<number>(3);
    buf.push(1);
    buf.push(2);
    expect(buf.toArray()).toEqual([1, 2]);
    expect(buf.size).toBe(2);
  });

  it('drops the oldest item when full', () => {
    const buf = new RingBuffer<number>(3);
    for (const n of [1, 2, 3, 4, 5]) buf.push(n);
    expect(buf.toArray()).toEqual([3, 4, 5]);
    expect(buf.size).toBe(3);
  });

  it.each([0, -1, 2.5])('rejects capacity %s', (capacity) => {
    expect(() => new RingBuffer<number>(capacity)).toThrow(RangeError);
  });
});
