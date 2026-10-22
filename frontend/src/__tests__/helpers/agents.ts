// Test helper: an AgentView for an id like 'sell_side_03'. The bracket comes
// from agentIdToBracket, so this stays valid if BracketKey changes.
import { agentIdToBracket } from '../../adapter/agentId';
import type { AgentSignal, AgentView } from '../../types';

export function makeAgent(id: string, signal: AgentSignal | null = 'hold', confidence = 0.5): AgentView {
  return {
    id,
    bracket: agentIdToBracket(id),
    bracketDisplay: id.replace(/_\d+$/, ''),
    signal,
    confidence,
    flipped: 0,
    roundLastSpoke: null,
    thinking: signal === null,
  };
}
