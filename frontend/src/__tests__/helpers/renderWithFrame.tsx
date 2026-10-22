// Render a component inside the production frame-context stack (FrameProviders).
// The frame starts from the backend-written live fixture, adapted by the real
// adapter; `raw` replaces the wire frame, `frame` overrides adapted view fields.
// Callers mark their test file `// @vitest-environment happy-dom`.
import { render } from '@testing-library/react';
import type { RenderResult } from '@testing-library/react';
import type { ReactElement } from 'react';
import { adaptSnapshot } from '../../adapter/frame';
import { FrameProviders } from '../../context/FrameProviders';
import type { StateFrame } from '../../types';
import liveFrame from '../fixtures/ws_snapshot.json';

export interface RenderWithFrameOptions {
  frame?: Partial<StateFrame>;
  raw?: unknown;
}

/** `ui` inside FrameProviders on the frame `opts` describes (for render or rerender). */
export function withFrame(ui: ReactElement, opts: RenderWithFrameOptions = {}): ReactElement {
  const frame: StateFrame = { ...adaptSnapshot(opts.raw ?? liveFrame), ...opts.frame };
  return (
    <FrameProviders frame={frame} connected reconnectFailed={false}>
      {ui}
    </FrameProviders>
  );
}

export function renderWithFrame(ui: ReactElement, opts: RenderWithFrameOptions = {}): RenderResult {
  return render(withFrame(ui, opts));
}
