// Wire-contract tests for adaptSnapshot(). The frames come from
// src/__tests__/fixtures/, written by tests/test_wire_contract.py from a real
// StateStore and serialised exactly as the broadcaster sends them. When the
// backend frame changes, regenerate the fixtures (UPDATE_GOLDEN=1) in the same
// commit; never edit them by hand.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { adaptSnapshot, SUPPORTED_SCHEMA_VERSION } from '../adapter/frame';
import live from './fixtures/ws_snapshot.json';
import replay from './fixtures/ws_snapshot_replay.json';
import {
  AGENT_STATE_KEYS,
  APPLIED_SHOCK_KEYS,
  AUDIT_KEYS,
  BRACKET_SUMMARY_KEYS,
  FRAME_KEYS,
  GOVERNOR_KEYS,
  JOB_STATUS_KEYS,
  JOBS_KEYS,
  RATIONALE_KEYS,
  RUN_ERROR_KEYS,
} from './helpers/wireKeys';

const sorted = (keys: readonly string[]): string[] => [...keys].sort();
const keysOf = (value: object): string[] => sorted(Object.keys(value));

afterEach(() => {
  vi.restoreAllMocks();
});

describe('fixtures match the TypeScript wire mirror (types.ts)', () => {
  it.each([
    ['live', live],
    ['replay', replay],
  ] as const)('%s frame has exactly the WireStateFrame keys', (_name, frame) => {
    expect(keysOf(frame)).toEqual(sorted(FRAME_KEYS));
    expect(keysOf(frame.governor_metrics)).toEqual(sorted(GOVERNOR_KEYS));
    expect(keysOf(frame.jobs)).toEqual(sorted(JOBS_KEYS));
    expect(keysOf(frame.jobs.advisory)).toEqual(sorted(JOB_STATUS_KEYS));
    expect(keysOf(frame.jobs.report)).toEqual(sorted(JOB_STATUS_KEYS));
    for (const state of Object.values(frame.agent_states)) {
      expect(keysOf(state)).toEqual(sorted(AGENT_STATE_KEYS));
    }
    for (const entry of frame.rationale_entries) {
      expect(keysOf(entry)).toEqual(sorted(RATIONALE_KEYS));
    }
    for (const summary of frame.bracket_summaries) {
      expect(keysOf(summary)).toEqual(sorted(BRACKET_SUMMARY_KEYS));
    }
  });

  it('live frame carries one audit entry and one applied shock with the mirrored keys', () => {
    expect(live.data_source_audit).toHaveLength(1);
    expect(keysOf(live.data_source_audit[0]!)).toEqual(sorted(AUDIT_KEYS));
    expect(live.applied_shocks).toHaveLength(1);
    expect(keysOf(live.applied_shocks[0]!)).toEqual(sorted(APPLIED_SHOCK_KEYS));
  });

  it('the fixtures use the schema version this bundle supports', () => {
    expect(live.schema_version).toBe(SUPPORTED_SCHEMA_VERSION);
    expect(replay.schema_version).toBe(SUPPORTED_SCHEMA_VERSION);
  });
});

describe('adaptSnapshot — live frame (mid round 2)', () => {
  const frame = adaptSnapshot(live);

  it('maps identity, mode and versioning', () => {
    expect(frame.schemaVersion).toBe(1);
    expect(frame.mode).toBe('live');
    expect(frame.phase).toBe('round_2');
    expect(frame.roundNum).toBe(2);
    expect(frame.running).toBe(true);
    expect(frame.cycleId).toBe('00000000-0000-4000-8000-000000000001');
    expect(frame.numRounds).toBe(3);
    expect(frame.edgesVersion).toBe(0);
  });

  it('maps signal=null to thinking and keeps parse_error distinct', () => {
    const byId = Object.fromEntries(frame.agents.map((a) => [a.id, a]));
    expect(byId.sell_side_03!.thinking).toBe(true);
    expect(byId.sell_side_03!.signal).toBe('hold'); // neutral visual while thinking
    expect(byId.degens_07!.signal).toBe('parse_error');
    expect(byId.degens_07!.thinking).toBe(false);
    expect(byId.institutions_01!.signal).toBe('buy');
    expect(byId.institutions_01!.confidence).toBe(0.82);
  });

  it('maps multi-word bracket ids to BracketKeys', () => {
    const byId = Object.fromEntries(frame.agents.map((a) => [a.id, a]));
    expect(byId.sell_side_03!.bracket).toBe('SellSide');
    expect(byId.sell_side_03!.bracketDisplay).toBe('Sell-Side');
    expect(byId.event_driven_05!.bracket).toBe('EventDriven');
  });

  it('keeps per-entry signal, round, seq and ts (seconds -> ms) on rationales', () => {
    expect(frame.rationales.map((r) => [r.seq, r.agentId, r.signal, r.round, r.ts])).toEqual([
      [1, 'quants_01', 'buy', 1, 1_790_000_010_000],
      [2, 'shorts_02', 'sell', 2, 1_790_000_015_000],
    ]);
  });

  it('maps governor metrics and telemetry', () => {
    expect(frame.telemetry).toMatchObject({
      slotsUsed: 12,
      slotsMax: 16,
      governorState: 'running',
      memMb: 61.2,
      tps: 42.7,
      elapsedSeconds: 754.25,
    });
  });

  it('maps bracket summaries and the derived consensus', () => {
    expect(frame.bracketSummaries.map((b) => [b.bracket, b.display, b.total])).toEqual([
      ['SellSide', 'Sell-Side', 10],
      ['EventDriven', 'Event-Driven', 10],
    ]);
    expect(frame.consensus).toBeCloseTo(-0.05, 10);
  });

  it('maps jobs, error, shocks and the audit log', () => {
    expect(frame.jobs).toEqual({
      advisory: { state: 'idle', cycleId: null, errorCode: null },
      report: { state: 'idle', cycleId: null, errorCode: null },
    });
    expect(frame.lastError).toBeNull();
    expect(frame.pendingShock).toBe('ZZZT Holdings confirms the financing is fully committed.');
    expect(frame.appliedShocks).toEqual([
      { text: 'QQQX Robotics board rejects the offer as undervalued.', roundNum: 2 },
    ]);
    expect(frame.shockWindowOpen).toBe(true);
    expect(frame.dataSourceAudit).toEqual([
      { ts: 1_790_000_015, source: 'yfinance', query: 'ZZZT 1d OHLCV', result: 'ok', used: true },
    ]);
  });
});

describe('adaptSnapshot — replay frame', () => {
  const frame = adaptSnapshot(replay);

  it('identifies the replayed cycle and its round depth', () => {
    expect(frame.mode).toBe('replay');
    expect(frame.cycleId).toBe('00000000-0000-4000-8000-000000000002');
    expect(frame.numRounds).toBe(2);
    expect(frame.roundNum).toBe(2);
    expect(frame.edgesVersion).toBe(1);
  });

  it('carries the live job status, so a reload during replay still sees the report job', () => {
    expect(frame.jobs.report).toEqual({
      state: 'running',
      cycleId: '00000000-0000-4000-8000-000000000002',
      errorCode: null,
    });
  });

  it('numbers replay rationales 1..n with unknown time', () => {
    expect(frame.rationales.map((r) => [r.seq, r.ts])).toEqual([
      [1, 0],
      [2, 0],
    ]);
  });
});

describe('adaptSnapshot — defensive mapping', () => {
  it('maps a failed run to lastError', () => {
    const lastError = { code: 'round_failed', message: 'Round 2 failed', round_num: 2, ts: 1.5 };
    expect(keysOf(lastError)).toEqual(sorted(RUN_ERROR_KEYS));
    const frame = adaptSnapshot({ ...live, phase: 'idle', mode: 'idle', last_error: lastError });
    expect(frame.lastError).toEqual({
      code: 'round_failed',
      message: 'Round 2 failed',
      roundNum: 2,
      ts: 1.5,
    });
  });

  it.each([
    ['idle', 'idle'],
    ['seeding', 'live'],
    ['round_3', 'live'],
    ['finalizing', 'live'],
    ['complete', 'live'],
    ['replay', 'replay'],
  ])('derives mode %s -> %s when the frame has none', (phase, mode) => {
    expect(adaptSnapshot({ phase }).mode).toBe(mode);
  });

  it('returns a sane frame for an empty snapshot ({})', () => {
    const frame = adaptSnapshot({});
    expect(frame).toMatchObject({
      schemaVersion: 0,
      mode: 'idle',
      phase: 'idle',
      running: false,
      roundNum: null,
      cycleId: null,
      numRounds: 3,
      edgesVersion: 0,
      agents: [],
      bracketSummaries: [],
      rationales: [],
      dataSourceAudit: [],
      consensus: null,
      lastError: null,
      pendingShock: null,
      appliedShocks: [],
      shockWindowOpen: false,
    });
    expect(frame.jobs.report).toEqual({ state: 'idle', cycleId: null, errorCode: null });
  });

  it('does not throw on null, undefined or malformed fields', () => {
    expect(() => adaptSnapshot(null)).not.toThrow();
    expect(() => adaptSnapshot(undefined)).not.toThrow();
    expect(() =>
      adaptSnapshot({
        agent_states: { quants_01: null },
        rationale_entries: [null],
        bracket_summaries: [{}],
        governor_metrics: null,
        jobs: { report: 'running' },
        last_error: { code: 7 },
        applied_shocks: [null, { text: 3 }],
      }),
    ).not.toThrow();
  });

  it('warns once when the backend speaks a different schema_version, and still adapts', async () => {
    vi.resetModules();
    const { adaptSnapshot: fresh } = await import('../adapter/frame');
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const frame = fresh({ ...live, schema_version: 2 });
    fresh({ ...live, schema_version: 2 });
    expect(frame.schemaVersion).toBe(2);
    expect(frame.cycleId).toBe('00000000-0000-4000-8000-000000000001');
    expect(warn).toHaveBeenCalledTimes(1);
    expect(String(warn.mock.calls[0]![0])).toContain('schema_version 2');
  });
});
