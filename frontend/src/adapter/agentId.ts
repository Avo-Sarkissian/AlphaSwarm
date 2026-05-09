import type { BracketKey } from '../types';

// Prefix map derived from design JSX (states.jsx line 81):
//   Q->Quants, D->Degens, S->Sovereigns, M->Macro, U->Suits,
//   I->Insiders, A->Agents, X->Doom-Posters, P->Policy Wonks, W->Whales
const PREFIX: Record<string, BracketKey> = {
  Q: 'Quants',
  D: 'Degens',
  S: 'Sovereigns',
  M: 'Macro',
  U: 'Suits',
  I: 'Insiders',
  A: 'Agents',
  X: 'DoomPosters',
  W: 'Whales',
  P: 'PolicyWonks',
};

export function agentIdToBracket(id: string): BracketKey {
  const k = id?.[0]?.toUpperCase() ?? '';
  return PREFIX[k] ?? 'Quants';
}
