// Render inside the production frame providers plus the real EdgesProvider,
// exactly as App.tsx mounts the dashboard. Edge fetches go through the
// test's fetch stub; an unstubbed /api/edges request gets a 404, which
// fetchEdges treats as "no edges yet".
import type { ReactElement } from 'react';
import { EdgesProvider } from '../../context/EdgesContext';
import { renderWithFrame, type RenderWithFrameOptions } from './renderWithFrame';

export function renderShell(ui: ReactElement, opts: RenderWithFrameOptions = {}) {
  return renderWithFrame(<EdgesProvider>{ui}</EdgesProvider>, opts);
}
