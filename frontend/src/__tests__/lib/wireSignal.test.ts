import { describe, expect, it } from 'vitest';
import { toWireSignal } from '../../lib/wireSignal';

describe('toWireSignal', () => {
  it.each([
    ['buy', 'buy'],
    ['SELL', 'sell'],
    ['hold', 'hold'],
    ['parse_error', 'parse_error'],
  ])('keeps %s', (raw, expected) => {
    expect(toWireSignal(raw)).toBe(expected);
  });

  it.each(['unknown', '', 'neutral', null, undefined])('drops %s', (raw) => {
    expect(toWireSignal(raw)).toBeUndefined();
  });
});
