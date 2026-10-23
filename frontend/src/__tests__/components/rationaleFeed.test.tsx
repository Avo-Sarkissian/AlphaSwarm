// @vitest-environment happy-dom
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { RationaleFeed } from '../../components/panels';
import type { FeedRow } from '../../lib/rationaleFeed';

const rows = (items: Array<[number, string]>): FeedRow[] =>
  items.map(([seq, text]) => ({ seq, agentId: 'quants_01', bracketDisplay: 'Quants', signal: 'buy', round: 2, text, cites: [] }));
const noop = () => {};

describe('RationaleFeed', () => {
  it('keeps existing rows mounted when a newer row arrives (keyed by seq)', () => {
    const { rerender } = render(<RationaleFeed rows={rows([[3, 'three'], [2, 'two'], [1, 'one']])} onAgentClick={noop} onCiteClick={noop} />);
    const before = screen.getByText('three').closest('.rationale-item');
    rerender(<RationaleFeed rows={rows([[4, 'four'], [3, 'three'], [2, 'two'], [1, 'one']])} onAgentClick={noop} onCiteClick={noop} />);
    expect(screen.getByText('three').closest('.rationale-item')).toBe(before);
    expect(document.querySelector('.rationale-body')?.textContent?.trim()).toBe('four');
  });

  it('shows the new round when replay restarts seq numbering', () => {
    const { container, rerender } = render(<RationaleFeed rows={rows([[2, 'r1 second'], [1, 'r1 first']])} onAgentClick={noop} onCiteClick={noop} />);
    rerender(<RationaleFeed rows={rows([[2, 'r2 second'], [1, 'r2 first']])} onAgentClick={noop} onCiteClick={noop} />);
    expect(container.textContent).toContain('r2 first');
    expect(container.textContent).not.toContain('r1 first');
  });
});
