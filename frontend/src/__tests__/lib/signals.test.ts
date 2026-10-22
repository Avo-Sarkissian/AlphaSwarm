import { describe, expect, it } from 'vitest';
import { signalClass, signalColor, signalLabel } from '../../lib/signals';

describe('signal display helpers', () => {
  it.each([
    [null, 'PENDING', 'sig-pending', 'var(--border-2)'],
    ['parse_error', 'FAILED', 'sig-parse_error', 'var(--text-3)'],
    ['hold', 'HOLD', 'sig-hold', 'var(--hold)'],
    ['buy', 'BUY', 'sig-buy', 'var(--buy)'],
    ['sell', 'SELL', 'sig-sell', 'var(--sell)'],
  ] as const)('%s → %s', (signal, label, cls, color) => {
    expect(signalLabel(signal)).toBe(label);
    expect(signalClass(signal)).toBe(cls);
    expect(signalColor(signal)).toBe(color);
  });
});
