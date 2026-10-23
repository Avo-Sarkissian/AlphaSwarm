// @vitest-environment happy-dom
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ConnectionBanner } from '../../app/ConnectionBanner';

describe('ConnectionBanner', () => {
  it.each(['open', 'connecting'] as const)('renders nothing while %s', (status) => {
    const { container } = render(<ConnectionBanner status={status} />);
    expect(container.innerHTML).toBe('');
  });

  it('explains a stalled channel', () => {
    render(<ConnectionBanner status="stale" />);
    expect(screen.getByRole('status').textContent).toMatch(/no update from the backend/i);
  });

  it('explains a lost connection', () => {
    render(<ConnectionBanner status="closed" />);
    expect(screen.getByRole('status').textContent).toMatch(/connection to the backend lost/i);
  });
});
