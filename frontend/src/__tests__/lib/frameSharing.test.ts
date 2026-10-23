// adaptSnapshot(raw, prev) reuses unchanged objects so memoized panels skip
// re-rendering (docs/DECISIONS.md#adr-frontend-quant-terminal).
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { adaptSnapshot } from '../../adapter/frame';
import liveFrame from '../fixtures/ws_snapshot.json';

interface RawFrame {
  agent_states: Record<string, { signal: string | null; confidence: number }>;
  rationale_entries: Array<Record<string, unknown>>;
  governor_metrics: Record<string, unknown>;
  [key: string]: unknown;
}

const clone = (): RawFrame => structuredClone(liveFrame) as unknown as RawFrame;

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date('2026-10-05T12:00:00Z'));
});

afterEach(() => {
  vi.useRealTimers();
});

describe('adaptSnapshot structural sharing', () => {
  it('returns the previous frame for an equal wire frame', () => {
    const prev = adaptSnapshot(clone());
    expect(adaptSnapshot(clone(), prev)).toBe(prev);
  });

  it('builds a fresh frame without a previous one', () => {
    const first = adaptSnapshot(clone());
    const second = adaptSnapshot(clone(), null);
    expect(second).not.toBe(first);
    expect(second).toEqual(first);
  });

  it('replaces only the agent that changed', () => {
    const prev = adaptSnapshot(clone());
    const raw = clone();
    const ids = Object.keys(raw.agent_states);
    expect(ids.length).toBeGreaterThan(1);
    const changedId = ids[0] ?? '';
    raw.agent_states[changedId] = { signal: 'sell', confidence: 0.123 };
    const next = adaptSnapshot(raw, prev);
    expect(next.agents).not.toBe(prev.agents);
    for (const agent of next.agents) {
      const before = prev.agents.find((a) => a.id === agent.id);
      if (agent.id === changedId) expect(agent).not.toBe(before);
      else expect(agent).toBe(before);
    }
    expect(next.bracketSummaries).toBe(prev.bracketSummaries);
    expect(next.rationales).toBe(prev.rationales);
  });

  it('shares every slice but telemetry when only memory changed', () => {
    const prev = adaptSnapshot(clone());
    const raw = clone();
    raw.governor_metrics.memory_percent = Number(raw.governor_metrics.memory_percent) + 1;
    const next = adaptSnapshot(raw, prev);
    expect(next).not.toBe(prev);
    expect(next.telemetry).not.toBe(prev.telemetry);
    expect(next.agents).toBe(prev.agents);
    expect(next.rationales).toBe(prev.rationales);
    expect(next.bracketSummaries).toBe(prev.bracketSummaries);
  });

  it('reuses rationale entries by seq when the window shifts', () => {
    const prev = adaptSnapshot(clone());
    const raw = clone();
    const entries = raw.rationale_entries;
    expect(entries.length).toBeGreaterThan(0);
    const last = entries[entries.length - 1] ?? {};
    raw.rationale_entries = [
      ...entries.slice(1),
      { ...last, seq: Number(last['seq']) + 1, agent_id: 'quants_09', rationale: 'ZZZT terms look rich.' },
    ];
    const next = adaptSnapshot(raw, prev);
    expect(next.rationales).not.toBe(prev.rationales);
    const dropped = prev.rationales.find((r) => !next.rationales.some((n) => n.seq === r.seq));
    for (const entry of prev.rationales) {
      if (entry === dropped) continue;
      expect(next.rationales.find((r) => r.seq === entry.seq)).toBe(entry);
    }
  });

  it('reuses agents by id when their order changes', () => {
    const prev = adaptSnapshot(clone());
    const raw = clone();
    raw.agent_states = Object.fromEntries(Object.entries(raw.agent_states).reverse());
    const next = adaptSnapshot(raw, prev);
    for (const agent of next.agents) {
      expect(agent).toBe(prev.agents.find((a) => a.id === agent.id));
    }
  });
});
