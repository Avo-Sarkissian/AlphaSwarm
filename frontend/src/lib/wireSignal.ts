// A backend signal string narrowed to the wire union; anything else (for
// example a citation's "unknown") becomes undefined.
import type { WireSignal } from '../types';

const WIRE_SIGNALS: ReadonlySet<string> = new Set(['buy', 'sell', 'hold', 'parse_error']);

export function toWireSignal(value: string | null | undefined): WireSignal | undefined {
  const lowered = value?.toLowerCase();
  return lowered !== undefined && WIRE_SIGNALS.has(lowered) ? (lowered as WireSignal) : undefined;
}
