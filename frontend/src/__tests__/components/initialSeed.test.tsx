// @vitest-environment happy-dom
import { screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App as DashboardShell } from '../../components/app_v2';
import wsSnapshot from '../fixtures/ws_snapshot.json';
import { ensureResizeObserver, stubFetch } from '../helpers/fetchStub';
import { renderShell } from '../helpers/renderShell';

const SEED = 'ZZZT Holdings is in late-stage talks to acquire QQQX Robotics for $4.2B in cash.';

beforeEach(() => {
  ensureResizeObserver();
  stubFetch([]);
});
afterEach(() => vi.unstubAllGlobals());

describe('dashboard initial seed', () => {
  it('shows the seed that was typed during onboarding', () => {
    renderShell(<DashboardShell initialSeed={SEED} />, { raw: wsSnapshot });
    expect(screen.getAllByDisplayValue(SEED).length).toBeGreaterThan(0);
  });
});
