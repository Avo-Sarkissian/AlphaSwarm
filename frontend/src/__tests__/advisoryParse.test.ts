// Wire-contract tests for AGENT_ID_RE — the citation-count heuristic must
// match real backend agent IDs (`{bracket}_{NN}` snake_case over the v2
// taxonomy) and must NOT match v1-era or design-era grammars.

import { describe, expect, it } from 'vitest';
import {
  AGENT_ID_RE,
  countAgentCitations,
  countAgentCitationsAgainst,
} from '../lib/advisoryParse';

// AGENT_ID_RE carries the /g flag (stateful lastIndex), so use String.match()
// against a fresh string per assertion instead of RegExp.test().
const matches = (text: string): string[] => text.match(AGENT_ID_RE) ?? [];

describe('AGENT_ID_RE — v2 agent ID grammar', () => {
  it.each(['institutions_01', 'sell_side_12', 'event_driven_05'])(
    'matches v2 id %s',
    (id) => {
      expect(matches(`cited by ${id} in round 2`)).toEqual([id]);
    },
  );

  it.each(['quants-01', 'Q-03', 'suits_03'])(
    'does NOT match non-v2 id %s',
    (id) => {
      expect(matches(`cited by ${id} in round 2`)).toEqual([]);
    },
  );

  it('extracts multiple distinct ids from prose', () => {
    expect(
      matches('macro_02 agrees with shorts_06; narrators_08 amplifies'),
    ).toEqual(['macro_02', 'shorts_06', 'narrators_08']);
  });
});

describe('countAgentCitations', () => {
  it('counts unique agents only', () => {
    expect(
      countAgentCitations('quants_01 cited quants_01 and macro_02'),
    ).toBe(2);
  });

  it('returns 0 for empty or citation-free text', () => {
    expect(countAgentCitations('')).toBe(0);
    expect(countAgentCitations('no agents here, only Q-03 and suits_03')).toBe(0);
  });
});

describe('countAgentCitationsAgainst', () => {
  it('keeps only ids present in the live agent set', () => {
    const liveIds = new Set(['quants_01', 'macro_02']);
    expect(
      countAgentCitationsAgainst('quants_01, macro_02 and degens_99', liveIds),
    ).toBe(2); // degens_99 matches the regex but is not live
  });
});
