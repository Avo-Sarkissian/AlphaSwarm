// @vitest-environment happy-dom
// useFrameMeta exposes the frame's identity through the production provider stack.
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { useFrameMeta } from '../../context/FrameMetaContext';
import replayFrame from '../fixtures/ws_snapshot_replay.json';
import { renderWithFrame } from '../helpers/renderWithFrame';

function MetaProbe() {
  const meta = useFrameMeta();
  return <pre data-testid="meta">{JSON.stringify(meta)}</pre>;
}

const metaShown = (): unknown => JSON.parse(screen.getByTestId('meta').textContent ?? 'null');

describe('useFrameMeta', () => {
  it('reports the live cycle, mode, rounds and edge version', () => {
    renderWithFrame(<MetaProbe />);
    expect(metaShown()).toEqual({
      mode: 'live',
      phase: 'round_2',
      cycleId: '00000000-0000-4000-8000-000000000001',
      numRounds: 3,
      roundNum: 2,
      edgesVersion: 0,
      schemaVersion: 1,
    });
  });

  it('reports the replayed cycle during replay', () => {
    renderWithFrame(<MetaProbe />, { raw: replayFrame });
    expect(metaShown()).toMatchObject({
      mode: 'replay',
      cycleId: '00000000-0000-4000-8000-000000000002',
      numRounds: 2,
      edgesVersion: 1,
    });
  });

  it('applies view overrides on top of the fixture', () => {
    renderWithFrame(<MetaProbe />, { frame: { edgesVersion: 2, roundNum: 3, phase: 'round_3' } });
    expect(metaShown()).toMatchObject({ edgesVersion: 2, roundNum: 3, phase: 'round_3' });
  });

  it('throws a clear error outside the provider', () => {
    expect(() => render(<MetaProbe />)).toThrow('useFrameMeta outside provider');
  });
});
