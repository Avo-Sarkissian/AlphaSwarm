import { describe, expect, it } from 'vitest';
import { sparkBars } from '../../lib/spark';

describe('sparkBars', () => {
  it('is empty for no samples', () => expect(sparkBars([])).toEqual([]));
  it('draws flat minimum bars when everything is zero', () => expect(sparkBars([0, 0])).toEqual([2, 2]));
  it('scales to the window maximum', () => expect(sparkBars([0, 5, 10])).toEqual([2, 9, 16]));
  it('treats non-finite samples as zero', () => expect(sparkBars([Number.NaN, 10])).toEqual([2, 16]));
});
