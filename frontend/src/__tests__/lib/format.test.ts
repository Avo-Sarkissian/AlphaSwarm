import { describe, expect, it } from 'vitest';
import { formatDuration } from '../../lib/format';

describe('formatDuration', () => {
  it.each([
    [null, '—'],
    [undefined, '—'],
    [Number.NaN, '—'],
    [-1, '—'],
    [0, '0:00'],
    [65, '1:05'],
    [754.3, '12:34'],
    [3725, '1:02:05'],
  ] as const)('%s -> %s', (seconds, expected) => {
    expect(formatDuration(seconds)).toBe(expected);
  });
});
