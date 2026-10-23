// @vitest-environment happy-dom
import { fireEvent, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { DataSourcesTakeover } from '../../features/wire/DataSourcesTakeover';
import wsSnapshot from '../fixtures/ws_snapshot.json';
import { stubFetch } from '../helpers/fetchStub';
import { renderWithFrame } from '../helpers/renderWithFrame';
import { AUDIT } from '../fixtures/audit';

beforeEach(() => {
  stubFetch([]);
});
afterEach(() => vi.unstubAllGlobals());

describe('DataSourcesTakeover', () => {
  it('summarizes the live audit per source with no invented figures', () => {
    renderWithFrame(<DataSourcesTakeover onClose={() => {}} />, { raw: wsSnapshot, frame: { dataSourceAudit: AUDIT } });
    expect(screen.getByText('LAST 3 PROVIDER CALLS')).toBeTruthy();
    expect(screen.getByText('QQQX 1d OHLCV')).toBeTruthy();
    fireEvent.click(screen.getByText('RSS'));
    expect(screen.getByText('headlines:ZZZT')).toBeTruthy();
    expect(document.body.textContent ?? '').not.toMatch(/82\.1 MB|P95 LATENCY|EGRESS|keys\.toml|ONLINE/);
  });

  it('explains an empty audit', () => {
    renderWithFrame(<DataSourcesTakeover onClose={() => {}} />, { raw: wsSnapshot, frame: { dataSourceAudit: [] } });
    expect(screen.getByText(/No provider calls yet/)).toBeTruthy();
  });
});
