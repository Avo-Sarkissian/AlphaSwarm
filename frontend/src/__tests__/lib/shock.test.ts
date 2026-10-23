import { describe, expect, it } from 'vitest';
import { SHOCK_MAX_CHARS, SHOCK_MIN_CHARS, shockLengthError, shockTargetRound } from '../../lib/shock';

describe('shockTargetRound', () => {
  it.each([
    [null, 3, true, 2],
    [0, 3, true, 2],
    [1, 3, true, 2],
    [2, 3, true, 3],
    [3, 3, true, null],
    [1, 2, true, 2],
    [2, 2, true, null],
    [1, 3, false, null],
  ] as const)('round %s of %s, window open %s -> %s', (round, numRounds, open, expected) => {
    expect(shockTargetRound(round, numRounds, open)).toBe(expected);
  });
});

describe('shockLengthError', () => {
  it('mirrors the backend limits', () => {
    expect([SHOCK_MIN_CHARS, SHOCK_MAX_CHARS]).toEqual([10, 1000]);
  });
  it('is silent for empty text', () => expect(shockLengthError('   ')).toBeNull());
  it('asks for at least 10 characters', () => expect(shockLengthError(' Fed cut ')).toMatch(/at least 10 characters/i));
  it('accepts 10..1000 characters', () => {
    expect(shockLengthError('x'.repeat(10))).toBeNull();
    expect(shockLengthError('x'.repeat(1000))).toBeNull();
  });
  it('rejects more than 1000', () => expect(shockLengthError('x'.repeat(1001))).toMatch(/at most 1000/i));
});
