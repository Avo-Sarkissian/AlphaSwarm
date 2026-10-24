// @vitest-environment happy-dom
import { renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { useFlipMarkedAgents } from '../../hooks/useFlipMarkedAgents';
import { forgetRounds } from '../../lib/flips';
import type { AgentSignal, StateFrame } from '../../types';
import { makeAgent } from '../helpers/agents';

type FrameSlice = Pick<StateFrame, 'agents' | 'cycleId' | 'roundNum'>;

function slice(roundNum: number, signals: Record<string, AgentSignal | null>, cycleId = 'cyc-flips'): FrameSlice {
  return { cycleId, roundNum, agents: Object.entries(signals).map(([id, s]) => makeAgent(id, s)) };
}

function mount(first: FrameSlice) {
  return renderHook((props: { frame: FrameSlice }) => useFlipMarkedAgents(props.frame), {
    initialProps: { frame: first },
  });
}

afterEach(() => forgetRounds());

describe('useFlipMarkedAgents', () => {
  it('rings an agent whose signal changed since the previous round', () => {
    const view = mount(slice(1, { quants_01: 'buy', degens_01: 'sell' }));
    view.rerender({ frame: slice(2, { quants_01: 'sell', degens_01: 'sell' }) });
    expect(view.result.current[0]).toMatchObject({ id: 'quants_01', flipped: 1, flippedFrom: 'buy' });
    expect(view.result.current[1]?.flipped).toBe(0);
  });

  it('shows no flip when the previous round was never seen', () => {
    const view = mount(slice(1, { quants_01: 'buy' }));
    view.rerender({ frame: slice(3, { quants_01: 'sell' }) });
    expect(view.result.current[0]?.flipped).toBe(0);
  });

  it('keeps cycles apart', () => {
    const view = mount(slice(1, { quants_01: 'buy' }, 'cyc-a'));
    view.rerender({ frame: slice(2, { quants_01: 'sell' }, 'cyc-b') });
    expect(view.result.current[0]?.flipped).toBe(0);
  });

  it('works backwards too: scrubbing R3 -> R2 compares with R1', () => {
    const view = mount(slice(1, { quants_01: 'buy' }));
    view.rerender({ frame: slice(2, { quants_01: 'hold' }) });
    view.rerender({ frame: slice(3, { quants_01: 'sell' }) });
    view.rerender({ frame: slice(2, { quants_01: 'hold' }) });
    expect(view.result.current[0]).toMatchObject({ flipped: 1, flippedFrom: 'buy' });
  });

  it('returns the frame agents unchanged when nothing flipped', () => {
    const first = slice(1, { quants_01: 'buy' });
    const view = mount(first);
    expect(view.result.current).toBe(first.agents);
  });
});
