// src/data.ts — only the BRACKETS constant per D-14.
// All mock data generators (PRNG, agent factory, bracket summary factory,
// the global window assignment) from AlphaSwarm-2/src/data.jsx are NOT lifted.
// Live data flows through useAgents()/useBrackets()/useRationales() contexts.
//
// Source: AlphaSwarm-2/src/data.jsx lines 3-14 (BRACKETS array literal only).

export interface BracketSpec {
  /** Stable bracket identifier; matches BracketKey from CONTRACT §2.1. */
  value: string;
  /** Human-readable label rendered in panels. */
  display: string;
  /** Target agent count per bracket (sums to 100 across all brackets). */
  count: number;
  /** Visualization radius for the bracket node in non-running states. */
  radius: number;
}

// Shared bracket-key normalizer — backend wire values are snake_case
// ('event_driven') while frontend BracketKey is PascalCase ('EventDriven').
// Normalize EITHER form to snake_case before comparing/looking up.
export const normalizeBracketKey = (k: unknown): string =>
  typeof k === 'string' ? k.replace(/([a-z])([A-Z])/g, '$1_$2').toLowerCase() : '';

export const BRACKETS: BracketSpec[] = [
  // v2 composition (2026-06-10) — mirrors DEFAULT_BRACKETS in config.py.
  { value: 'institutions', display: 'Institutions', count: 18, radius: 5  },
  { value: 'sell_side',    display: 'Sell-Side',    count: 10, radius: 6  },
  { value: 'event_driven', display: 'Event-Driven', count: 10, radius: 7  },
  { value: 'quants',       display: 'Quants',       count: 12, radius: 8  },
  { value: 'degens',       display: 'Degens',       count: 15, radius: 9  },
  { value: 'narrators',    display: 'Narrators',    count: 8,  radius: 10 },
  { value: 'algos',        display: 'Algos',        count: 8,  radius: 11 },
  { value: 'macro',        display: 'Macro',        count: 7,  radius: 12 },
  { value: 'shorts',       display: 'Shorts',       count: 7,  radius: 13 },
  { value: 'allocators',   display: 'Allocators',   count: 5,  radius: 14 },
];
