import { beforeEach, describe, expect, it, vi } from 'vitest';
import { adaptSnapshot } from '../../adapter/frame';

beforeEach(() => {
  vi.spyOn(console, 'warn').mockImplementation(() => {});
});

describe('adapter bracket identity is wire snake_case', () => {
  it('maps agent ids to registry keys and display names', () => {
    const frame = adaptSnapshot({
      phase: 'round_1',
      agent_states: {
        sell_side_03: { signal: 'buy', confidence: 0.8 },
        event_driven_05: { signal: null, confidence: 0 },
        whales_01: { signal: 'hold', confidence: 0.5 },
      },
    });
    const byId = Object.fromEntries(frame.agents.map((a) => [a.id, a]));
    expect(byId['sell_side_03']).toMatchObject({ bracket: 'sell_side', bracketDisplay: 'Sell-Side' });
    expect(byId['event_driven_05']).toMatchObject({ bracket: 'event_driven', bracketDisplay: 'Event-Driven' });
    expect(byId['whales_01']).toMatchObject({ bracket: 'unknown', bracketDisplay: 'Unknown' });
  });

  it('keeps bracket summary keys as wire keys', () => {
    const summary = { buy_count: 0, sell_count: 0, hold_count: 0, total: 0, avg_confidence: 0, avg_sentiment: 0 };
    const frame = adaptSnapshot({
      bracket_summaries: [
        { ...summary, bracket: 'sell_side', display_name: 'Sell-Side' },
        { ...summary, bracket: 'suits', display_name: 'Suits' },
      ],
    });
    expect(frame.bracketSummaries.map((b) => b.bracket)).toEqual(['sell_side', 'unknown']);
  });
});
