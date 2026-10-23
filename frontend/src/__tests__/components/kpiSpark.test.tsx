// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AppShell as DashboardShell } from '../../app/AppShell';
import wsSnapshot from '../fixtures/ws_snapshot.json';
import { ensureResizeObserver, stubFetch } from '../helpers/fetchStub';
import { renderShell } from '../helpers/renderShell';

beforeEach(() => {
  ensureResizeObserver();
  stubFetch([]);
});
afterEach(() => vi.unstubAllGlobals());

describe('TPS sparkline', () => {
  it('draws one bar per observed frame instead of 22 invented bars', () => {
    const { container } = renderShell(<DashboardShell />, { raw: wsSnapshot });
    const bars = container.querySelectorAll('.spark span').length;
    expect(bars).toBeGreaterThanOrEqual(1);
    expect(bars).toBeLessThanOrEqual(2); // 2 only if the helper renders in StrictMode
  });
});
