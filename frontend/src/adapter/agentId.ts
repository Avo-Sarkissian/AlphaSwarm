import type { BracketKey } from '../types';

// Backend agent IDs are `{bracket}_{NN}` snake_case (e.g. 'sell_side_03',
// 'event_driven_05'). Strip the trailing index and map the full bracket
// value (the old first-char prefix table misclassified multi-word brackets).
const BRACKET_VALUE: Record<string, BracketKey> = {
  institutions: 'Institutions',
  sell_side: 'SellSide',
  event_driven: 'EventDriven',
  quants: 'Quants',
  degens: 'Degens',
  narrators: 'Narrators',
  algos: 'Algos',
  macro: 'Macro',
  shorts: 'Shorts',
  allocators: 'Allocators',
};

export function agentIdToBracket(id: string): BracketKey {
  const bracket = (id ?? '').replace(/_\d+$/, '').toLowerCase();
  return BRACKET_VALUE[bracket] ?? 'Quants';
}
