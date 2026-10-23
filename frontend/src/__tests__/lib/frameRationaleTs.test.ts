import { afterEach, describe, expect, it, vi } from 'vitest';
import { adaptSnapshot } from '../../adapter/frame';

afterEach(() => vi.useRealTimers());

describe('rationale timestamps', () => {
  it('are taken from the wire and never invented per frame', () => {
    vi.useFakeTimers();
    const raw = {
      phase: 'round_1',
      rationale_entries: [{ agent_id: 'quants_01', signal: 'buy', rationale: 'ZZZT momentum', round_num: 1, seq: 4 }],
    };
    vi.setSystemTime(1_000_000);
    const a = adaptSnapshot(raw);
    vi.setSystemTime(9_000_000);
    const b = adaptSnapshot(raw);
    expect(b.rationales[0]?.ts).toBe(a.rationales[0]?.ts);
    expect(a.rationales[0]?.seq).toBe(4);
  });
});
