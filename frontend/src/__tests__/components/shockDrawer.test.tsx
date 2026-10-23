// @vitest-environment happy-dom
import { fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App as DashboardShell } from '../../components/app_v2';
import { ShockDrawer } from '../../components/ShockDrawer';
import wsSnapshot from '../fixtures/ws_snapshot.json';
import { ensureResizeObserver, stubFetch } from '../helpers/fetchStub';
import { renderShell } from '../helpers/renderShell';
import { renderWithFrame } from '../helpers/renderWithFrame';

const OPEN = { shockWindowOpen: true, pendingShock: null, roundNum: 1, numRounds: 3 };
const TEXT = 'QQQX Robotics guidance cut by a third';
const input = () => screen.getByPlaceholderText(/disruptive event/i) as HTMLInputElement;
const inject = () => screen.getByRole('button', { name: /inject/i }) as HTMLButtonElement;

beforeEach(() => ensureResizeObserver());
afterEach(() => vi.unstubAllGlobals());

describe('ShockDrawer', () => {
  it('names the round the shock reaches and gates Inject on length', async () => {
    const fetchMock = stubFetch([{ method: 'POST', path: '/api/simulate/shock', body: { status: 'queued', message: 'ok' } }]);
    const onClose = vi.fn();
    renderWithFrame(<ShockDrawer onClose={onClose} />, { raw: wsSnapshot, frame: OPEN });

    expect(screen.getByText(/lands before round 2/i)).toBeTruthy();
    expect(input().maxLength).toBe(1000);
    fireEvent.change(input(), { target: { value: 'Fed cut' } });
    expect(inject().disabled).toBe(true);
    expect(screen.getByText(/at least 10 characters/i)).toBeTruthy();

    fireEvent.change(input(), { target: { value: TEXT } });
    expect(inject().disabled).toBe(false);
    fireEvent.click(inject());

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({ shock_text: TEXT });
  });

  it('explains and disables everything when the window is closed', () => {
    stubFetch([]);
    renderWithFrame(<ShockDrawer onClose={() => {}} />, { raw: wsSnapshot, frame: { ...OPEN, shockWindowOpen: false } });
    expect(screen.getByText(/window closed/i)).toBeTruthy();
    expect(input().disabled).toBe(true);
    expect(inject().disabled).toBe(true);
  });

  it('shows a queued shock and blocks a second one', () => {
    stubFetch([]);
    renderWithFrame(<ShockDrawer onClose={() => {}} />, {
      raw: wsSnapshot,
      frame: { ...OPEN, pendingShock: 'ZZZT guidance withdrawn pending review' },
    });
    expect(screen.getByText(/ZZZT guidance withdrawn pending review/)).toBeTruthy();
    fireEvent.change(input(), { target: { value: TEXT } });
    expect(inject().disabled).toBe(true);
  });

  it('stays open with the server reason when the window closed meanwhile', async () => {
    stubFetch([
      {
        method: 'POST',
        path: '/api/simulate/shock',
        status: 409,
        body: { detail: { error: 'shock_window_closed', message: 'The shock window has closed' } },
      },
    ]);
    const onClose = vi.fn();
    renderWithFrame(<ShockDrawer onClose={onClose} />, { raw: wsSnapshot, frame: OPEN });
    fireEvent.change(input(), { target: { value: TEXT } });
    fireEvent.click(inject());
    expect(await screen.findByText(/The shock window has closed/)).toBeTruthy();
    expect(onClose).not.toHaveBeenCalled();
  });

  it('shows no invented impact preview', () => {
    stubFetch([]);
    renderWithFrame(<ShockDrawer onClose={() => {}} />, { raw: wsSnapshot, frame: OPEN });
    fireEvent.change(input(), { target: { value: TEXT } });
    expect(screen.queryByText(/impact preview|agents re-evaluate/i)).toBeNull();
  });
});

describe('topbar shock button', () => {
  it('is disabled with a reason when the window is closed', () => {
    stubFetch([]);
    renderShell(<DashboardShell />, { raw: wsSnapshot, frame: { shockWindowOpen: false } });
    const button = screen.getByTitle(/shock window closed/i) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
  });
});
