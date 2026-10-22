import { describe, expect, it } from 'vitest';
import { SEED_MAX_LENGTH, SEED_MIN_LENGTH, seedProblem } from '../../lib/seed';

describe('seedProblem (mirrors backend SeedText: stripped length 10..2000)', () => {
  it('asks for a seed when empty or blank', () => {
    expect(seedProblem('')).toBe('Enter a seed rumor first.');
    expect(seedProblem('   \n ')).toBe('Enter a seed rumor first.');
  });

  it('rejects a seed shorter than the backend minimum after trimming', () => {
    expect(SEED_MIN_LENGTH).toBe(10);
    expect(seedProblem('  ZZZT up  ')).toBe('The seed needs at least 10 characters.');
  });

  it('rejects a seed longer than the backend maximum', () => {
    expect(SEED_MAX_LENGTH).toBe(2000);
    expect(seedProblem('x'.repeat(2001))).toBe('The seed can have at most 2000 characters.');
  });

  it('accepts a normal rumor', () => {
    expect(
      seedProblem('ZZZT Holdings is in late-stage talks to acquire QQQX Robotics for $4.2B in cash.'),
    ).toBeNull();
  });
});
