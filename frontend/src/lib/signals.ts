// Display helpers for an agent's signal. null = pending (no decision yet this
// round); parse_error = the agent failed this round. Neither is HOLD
// (docs/DECISIONS.md#adr-streaming-state).
import type { AgentSignal } from '../types';

export function signalLabel(signal: AgentSignal | null): string {
  if (signal === null) return 'PENDING';
  if (signal === 'parse_error') return 'FAILED';
  return signal.toUpperCase();
}

export function signalColor(signal: AgentSignal | null): string {
  switch (signal) {
    case 'buy':
      return 'var(--buy)';
    case 'sell':
      return 'var(--sell)';
    case 'hold':
      return 'var(--hold)';
    case 'parse_error':
      return 'var(--text-3)';
    default:
      return 'var(--border-2)';
  }
}

/** CSS modifier for `.sig-*` chips: sig-buy | sig-sell | sig-hold | sig-parse_error | sig-pending. */
export function signalClass(signal: AgentSignal | null): string {
  return `sig-${signal ?? 'pending'}`;
}
