// Test helper: an AgentView for an id like 'sell_side_03'.
// The bracket comes from bracketOf (wire snake_case key).
import { bracketOf, bracketSpec } from '../../data';
import type { AgentSignal, AgentView } from '../../types';

export function makeAgent(id: string, signal: AgentSignal | null = 'hold', confidence = 0.5): AgentView {
  return {
    id,
    bracket: bracketOf(id),
    bracketDisplay: bracketSpec(bracketOf(id))?.display ?? 'Unknown',
    signal,
    confidence,
    flipped: 0,
    roundLastSpoke: null,
    thinking: signal === null,
  };
}
