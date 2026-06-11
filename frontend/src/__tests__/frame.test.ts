// Wire-contract tests for adaptSnapshot() — the #1 frontend failure mode is
// adapter drift against the backend snapshot shape.
//
// The canned snapshot below EXACTLY mirrors what the backend emits:
// dataclasses.asdict(StateSnapshot) from src/alphaswarm/state.py, serialized
// by src/alphaswarm/web/broadcaster.py:snapshot_to_json(). SignalType and
// SimulationPhase are str-Enums, so wire values are lowercase strings
// ('buy'/'sell'/'hold'/'parse_error', 'idle'/'seeding'/'round_1'/.../'replay').
// signal=null means the agent is still thinking (dispatch window placeholder).
// If the backend shape changes, THIS FILE must change with it — deliberately.

import { describe, expect, it } from 'vitest';
import { adaptSnapshot } from '../adapter/frame';

/** Mirrors json.loads(snapshot_to_json(state_store)) mid-round_2. */
const WIRE_SNAPSHOT = {
  phase: 'round_2',
  round_num: 2,
  agent_count: 100,
  agent_states: {
    // signal=null → agent still thinking (set_phase round-entry placeholder)
    sell_side_03: { signal: null, confidence: 0.0 },
    institutions_01: { signal: 'buy', confidence: 0.82 },
    event_driven_05: { signal: 'sell', confidence: 0.4 },
    degens_07: { signal: 'parse_error', confidence: 0.0 },
    macro_02: { signal: 'hold', confidence: 0.55 },
  },
  elapsed_seconds: 123.45,
  governor_metrics: {
    current_slots: 16,
    active_count: 12,
    pressure_level: 'green',
    memory_percent: 61.2,
    governor_state: 'normal',
    timestamp: 98765.4,
  },
  tps: 42.7,
  rationale_entries: [
    {
      agent_id: 'quants_01',
      signal: 'buy',
      rationale: 'Momentum + volume confirm the rumor priced in',
      round_num: 1,
    },
    {
      agent_id: 'shorts_02',
      signal: 'sell',
      rationale: 'Crowded long, fade the cascade',
      round_num: 2,
    },
  ],
  bracket_summaries: [
    {
      bracket: 'sell_side',
      display_name: 'Sell-Side',
      buy_count: 4,
      sell_count: 3,
      hold_count: 3,
      total: 10,
      avg_confidence: 0.61,
      avg_sentiment: 0.1,
    },
    {
      bracket: 'event_driven',
      display_name: 'Event-Driven',
      buy_count: 5,
      sell_count: 2,
      hold_count: 3,
      total: 10,
      avg_confidence: 0.55,
      avg_sentiment: -0.2,
    },
  ],
  data_source_audit: [
    {
      ts: 1765432100.5,
      source: 'yfinance',
      query: 'AAPL 1d OHLCV',
      result: 'ok',
      used: true,
    },
  ],
};

describe('adaptSnapshot — wire contract', () => {
  it('passes phase/round through and derives running', () => {
    const frame = adaptSnapshot(WIRE_SNAPSHOT);
    expect(frame.phase).toBe('round_2');
    expect(frame.roundNum).toBe(2);
    expect(frame.running).toBe(true);
  });

  it.each([
    ['idle', false],
    ['seeding', true],
    ['round_1', true],
    ['round_2', true],
    ['round_3', true],
    ['complete', false],
    ['replay', true],
  ])('accepts backend phase %s (running=%s)', (phase, running) => {
    const frame = adaptSnapshot({ ...WIRE_SNAPSHOT, phase });
    expect(frame.phase).toBe(phase);
    expect(frame.running).toBe(running);
  });

  it('maps signal=null to thinking=true with neutral hold visual', () => {
    const frame = adaptSnapshot(WIRE_SNAPSHOT);
    const thinking = frame.agents.find((a) => a.id === 'sell_side_03');
    expect(thinking).toBeDefined();
    expect(thinking!.thinking).toBe(true);
    expect(thinking!.signal).toBe('hold'); // neutral fallback while thinking

    const decided = frame.agents.find((a) => a.id === 'institutions_01');
    expect(decided!.thinking).toBe(false);
    expect(decided!.signal).toBe('buy');
    expect(decided!.confidence).toBe(0.82);
  });

  it('preserves parse_error as a distinct signal (not coerced to hold)', () => {
    const frame = adaptSnapshot(WIRE_SNAPSHOT);
    const broken = frame.agents.find((a) => a.id === 'degens_07');
    expect(broken!.signal).toBe('parse_error');
    expect(broken!.thinking).toBe(false);
  });

  it('maps multi-word bracket agent IDs to the right BracketKey', () => {
    const frame = adaptSnapshot(WIRE_SNAPSHOT);
    const byId = Object.fromEntries(frame.agents.map((a) => [a.id, a]));
    expect(byId.sell_side_03.bracket).toBe('SellSide');
    expect(byId.sell_side_03.bracketDisplay).toBe('Sell-Side');
    expect(byId.event_driven_05.bracket).toBe('EventDriven');
    expect(byId.institutions_01.bracket).toBe('Institutions');
    expect(byId.macro_02.bracket).toBe('Macro');
  });

  it('keeps per-entry signal and round_num on rationale entries', () => {
    const frame = adaptSnapshot(WIRE_SNAPSHOT);
    expect(frame.rationales).toHaveLength(2);
    const [first, second] = frame.rationales;
    expect(first.agentId).toBe('quants_01');
    expect(first.signal).toBe('buy'); // per-entry wire signal, NOT current agent state
    expect(first.round).toBe(1); // round_num from the entry, NOT current round (2)
    expect(first.text).toBe('Momentum + volume confirm the rumor priced in');
    expect(second.agentId).toBe('shorts_02');
    expect(second.signal).toBe('sell');
    expect(second.round).toBe(2);
  });

  it('maps governor metrics to slotsUsed/slotsMax/governorState', () => {
    const { telemetry } = adaptSnapshot(WIRE_SNAPSHOT);
    expect(telemetry.slotsUsed).toBe(12); // governor_metrics.active_count
    expect(telemetry.slotsMax).toBe(16); // governor_metrics.current_slots
    expect(telemetry.governorState).toBe('normal');
    expect(telemetry.memMb).toBe(61.2); // KR-41.1-04: percent, not MB
  });

  it('passes elapsed_seconds and tps through telemetry', () => {
    const { telemetry } = adaptSnapshot(WIRE_SNAPSHOT);
    expect(telemetry.elapsedSeconds).toBe(123.45);
    expect(telemetry.tps).toBe(42.7);
  });

  it('maps snake_case bracket_summaries to PascalCase BracketKeys', () => {
    const frame = adaptSnapshot(WIRE_SNAPSHOT);
    expect(frame.bracketSummaries).toHaveLength(2);
    const [sellSide, eventDriven] = frame.bracketSummaries;
    expect(sellSide.bracket).toBe('SellSide');
    expect(sellSide.display).toBe('Sell-Side');
    expect(sellSide.buy).toBe(4);
    expect(sellSide.sell).toBe(3);
    expect(sellSide.hold).toBe(3);
    expect(sellSide.total).toBe(10);
    expect(sellSide.agentCount).toBe(10);
    expect(sellSide.avgConfidence).toBe(0.61);
    expect(eventDriven.bracket).toBe('EventDriven');
    // consensus = mean of avg_sentiment across brackets: (0.1 + -0.2) / 2
    expect(frame.consensus).toBeCloseTo(-0.05, 10);
  });

  it('passes the data_source_audit slice through to camelCase views', () => {
    const frame = adaptSnapshot(WIRE_SNAPSHOT);
    expect(frame.dataSourceAudit).toEqual([
      {
        ts: 1765432100.5,
        source: 'yfinance',
        query: 'AAPL 1d OHLCV',
        result: 'ok',
        used: true,
      },
    ]);
  });

  it('returns a sane frame for an empty snapshot ({})', () => {
    const frame = adaptSnapshot({});
    expect(frame.phase).toBe('idle');
    expect(frame.running).toBe(false);
    expect(frame.roundNum).toBeNull();
    expect(frame.agents).toEqual([]);
    expect(frame.bracketSummaries).toEqual([]);
    expect(frame.rationales).toEqual([]);
    expect(frame.dataSourceAudit).toEqual([]);
    expect(frame.consensus).toBeNull();
    expect(frame.cycleId).toBeNull();
    expect(frame.telemetry.slotsUsed).toBe(0);
    expect(frame.telemetry.slotsMax).toBe(0);
    expect(frame.telemetry.governorState).toBeNull();
    expect(frame.telemetry.tps).toBe(0);
    expect(frame.telemetry.elapsedSeconds).toBe(0);
  });

  it('does not throw on null/undefined or partially-missing fields', () => {
    expect(() => adaptSnapshot(null)).not.toThrow();
    expect(() => adaptSnapshot(undefined)).not.toThrow();
    expect(() =>
      adaptSnapshot({ phase: 'round_1', agent_states: { quants_01: null } }),
    ).not.toThrow();
    expect(() =>
      adaptSnapshot({ rationale_entries: [null], bracket_summaries: [{}] }),
    ).not.toThrow();
    expect(() => adaptSnapshot({ governor_metrics: null })).not.toThrow();
  });
});
