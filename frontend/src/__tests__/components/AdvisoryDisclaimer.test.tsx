// @vitest-environment happy-dom
// The advisory always shows the not-investment-advice banner, in every state and tab.
import { fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AdvisoryV2 as AdvisoryPanel } from '../../features/advisory/AdvisoryPanel';
import { AdvisoryDisclaimer } from '../../features/advisory/AdvisoryDisclaimer';
import { ADVISORY_DISCLAIMER } from '../../features/advisory/disclaimer';
import { renderWithFrame } from '../helpers/renderWithFrame';

const disclaimer = () => screen.getByRole('note', { name: 'Disclaimer' });

describe('AdvisoryDisclaimer', () => {
  it('renders the fixed text as a labelled note', () => {
    const { asFragment } = render(<AdvisoryDisclaimer />);
    expect(asFragment()).toMatchInlineSnapshot(`
      <DocumentFragment>
        <div
          aria-label="Disclaimer"
          class="adv-disclaimer"
          role="note"
        >
          LLM-generated simulation output for research and education; not investment advice.
        </div>
      </DocumentFragment>
    `);
  });
});

describe('AdvisoryPanel', () => {
  beforeEach(() => {
    // Every request stays pending, so the panel renders its loading or no-cycle state.
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(() => undefined)));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('shows the disclaimer before any advisory has loaded', () => {
    renderWithFrame(<AdvisoryPanel onClose={vi.fn()} />);
    expect(disclaimer().textContent).toBe(ADVISORY_DISCLAIMER);
  });

  it('keeps the disclaimer on every tab', () => {
    const { container } = renderWithFrame(<AdvisoryPanel onClose={vi.fn()} />);
    const tabs = Array.from(container.querySelectorAll<HTMLElement>('[role="tab"], .adv-tab'));
    expect(tabs.length).toBeGreaterThan(0);
    for (const tab of tabs) {
      fireEvent.click(tab);
      expect(disclaimer().textContent).toBe(ADVISORY_DISCLAIMER);
    }
  });

  it('offers no way to dismiss the disclaimer', () => {
    renderWithFrame(<AdvisoryPanel onClose={vi.fn()} />);
    expect(within(disclaimer()).queryByRole('button')).toBeNull();
  });
});
