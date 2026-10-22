// @vitest-environment happy-dom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { InlineError } from '../../components/InlineError';

afterEach(cleanup);

describe('InlineError', () => {
  it('renders nothing without an error', () => {
    const { container } = render(<InlineError error={null} />);
    expect(container.innerHTML).toBe('');
  });

  it('shows the message as an alert', () => {
    render(<InlineError error="Simulation already running" />);
    expect(screen.getByRole('alert').textContent).toContain('Simulation already running');
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('offers a dismiss button when onDismiss is given', () => {
    const onDismiss = vi.fn();
    render(<InlineError error="Simulation already running" onDismiss={onDismiss} />);
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss error' }));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });
});
