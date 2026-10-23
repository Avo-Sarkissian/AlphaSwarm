// @vitest-environment happy-dom
import { screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App as DashboardShell } from '../../components/app_v2';
import wsSnapshot from '../fixtures/ws_snapshot.json';
import wsSnapshotReplay from '../fixtures/ws_snapshot_replay.json';
import { ensureResizeObserver, stubFetch } from '../helpers/fetchStub';
import { renderShell } from '../helpers/renderShell';

beforeEach(() => {
  ensureResizeObserver();
  stubFetch([]);
});
afterEach(() => vi.unstubAllGlobals());

describe('no placebo controls', () => {
  it('the live dashboard has no round tabs, Inspire button or invented entity count', () => {
    const { container } = renderShell(<DashboardShell />, { raw: wsSnapshot });
    expect(container.querySelector('.round-tabs')).toBeNull();
    expect(screen.queryByTitle(/inspire/i)).toBeNull();
    expect(screen.queryByText(/\d+ entities/)).toBeNull();
  });

  it('the replay bar has no disabled Rewind button', () => {
    renderShell(<DashboardShell />, { raw: wsSnapshotReplay });
    expect(screen.queryByTitle(/rewind/i)).toBeNull();
  });
});
