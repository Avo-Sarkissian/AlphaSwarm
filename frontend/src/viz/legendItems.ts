// Which encodings the graph currently shows; the Legend lists these and nothing
// else (docs/DECISIONS.md#adr-hero-graph).
import type { AgentSignal } from '../types';
import type { GraphLayout } from './layout';

/** What the edge layer draws right now. */
export type EdgeMode = 'none' | 'ribbons' | 'agents' | 'ego';

export type LegendKey =
  | 'buy'
  | 'sell'
  | 'hold'
  | 'failed'
  | 'pending'
  | 'size'
  | 'flip'
  | 'ribbon'
  | 'within'
  | 'agent-edge'
  | 'edge-weight'
  | 'ego-in'
  | 'ego-out'
  | 'hint';

export interface LegendItem {
  key: LegendKey;
  label: string;
}

export interface LegendInput {
  layout: GraphLayout;
  edgeMode: EdgeMode;
  /** Signals of the agents on screen; 'pending' = no decision yet this round. */
  signals: ReadonlySet<AgentSignal | 'pending'>;
  /** Node size encodes citations (at least one citation in the round on screen). */
  sized: boolean;
  /** Agent edges have different widths (weights differ). */
  weighted: boolean;
  /** At least one agent carries a flip marker. */
  flips: boolean;
  /** Citations inside one bracket, which ribbons do not draw. */
  withinCount: number;
  /** Citations exist but nothing draws them until an agent is focused. */
  hint: boolean;
}

export function legendItems(input: LegendInput): LegendItem[] {
  const items: LegendItem[] = [];
  const add = (key: LegendKey, label: string) => items.push({ key, label });
  if (input.signals.has('buy')) add('buy', 'Buy');
  if (input.signals.has('sell')) add('sell', 'Sell');
  if (input.signals.has('hold')) add('hold', 'Hold');
  if (input.signals.has('parse_error')) add('failed', 'Failed (parse error)');
  if (input.signals.has('pending')) add('pending', 'Thinking (no decision yet)');
  if (input.sized && input.layout !== 'grid') add('size', 'Size: peers citing the agent');
  if (input.flips) add('flip', 'Ring: flipped since the previous round (colour = previous signal)');
  if (input.edgeMode === 'ribbons') {
    add('ribbon', 'Ribbon: citations between brackets, cited → citing');
    if (input.withinCount > 0) {
      add('within', `${input.withinCount} citations inside a bracket (not drawn)`);
    }
  }
  if (input.edgeMode === 'agents') {
    add('agent-edge', 'Arrow: citation, cited → citing (colour = citer signal)');
    if (input.weighted) add('edge-weight', 'Width: citation weight');
  }
  if (input.edgeMode === 'ego') {
    add('ego-in', 'Peers it cited');
    add('ego-out', 'Peers citing it');
  }
  if (input.hint) add('hint', 'Hover or click an agent to see its citations');
  return items;
}
