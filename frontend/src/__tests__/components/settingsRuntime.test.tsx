// @vitest-environment happy-dom
import { screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Settings } from '../../features/settings/Settings';
import wsSnapshot from '../fixtures/ws_snapshot.json';
import { stubFetch } from '../helpers/fetchStub';
import { renderWithFrame } from '../helpers/renderWithFrame';

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('Settings runtime section', () => {
  it('offers no UI tweaks that nothing reads and stores nothing in the browser', () => {
    stubFetch([]);
    const setItem = vi.spyOn(Storage.prototype, 'setItem');
    renderWithFrame(<Settings onClose={() => {}} />, { raw: wsSnapshot });
    for (const title of ['Display density', 'Layout', 'Theme', 'First-run hints']) {
      expect(screen.queryByText(title)).toBeNull();
    }
    expect(setItem).not.toHaveBeenCalled();
  });
});
