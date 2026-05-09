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

export const BRACKETS: BracketSpec[] = [
  { value: 'quants',       display: 'Quants',       count: 10, radius: 5  },
  { value: 'degens',       display: 'Degens',       count: 20, radius: 6  },
  { value: 'sovereigns',   display: 'Sovereigns',   count: 10, radius: 7  },
  { value: 'macro',        display: 'Macro',        count: 10, radius: 8  },
  { value: 'suits',        display: 'Suits',        count: 10, radius: 9  },
  { value: 'insiders',     display: 'Insiders',     count: 10, radius: 10 },
  { value: 'agents',       display: 'Agents',       count: 15, radius: 11 },
  { value: 'doom_posters', display: 'Doom-Posters', count: 5,  radius: 12 },
  { value: 'policy_wonks', display: 'Policy Wonks', count: 5,  radius: 13 },
  { value: 'whales',       display: 'Whales',       count: 5,  radius: 14 },
];
